"""Cross-case attacker recall.

The gap this closes: until now every case started from zero. The fleet could block a $340,000
attempt and then, twenty minutes later, meet the same attacker targeting a different vendor and
notice nothing. A human analyst would remember. The fleet did not.

`Recall` gives the fleet institutional memory. When a case terminates in BLOCK, the tradecraft is
distilled into a fingerprint and written to cross-session memory. Every subsequent case is checked
against that memory BEFORE the verification lanes run, so a repeat attacker is recognised on
arrival and the finding cites the earlier case by ID.

This is the durable-memory half of the GEAP Sessions binding doing something load-bearing rather
than decorative: the memory is not a transcript, it is an accumulating threat model.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..guardrails.injection import HOMOGLYPHS
from ..models.domain import DEFAULT_TENANT_ID


def _fold_confusables(text: str) -> str:
    return "".join(HOMOGLYPHS.get(c, c) for c in unicodedata.normalize("NFKC", text.lower()))


def _homoglyph_technique(observed: str, legitimate: str) -> str | None:
    """Name the substitution, e.g. 'm->rn'. The technique is more durable than the domain:
    attackers burn domains constantly but reuse tradecraft."""
    if not observed or not legitimate or observed == legitimate:
        return None
    if _fold_confusables(observed) == _fold_confusables(legitimate):
        return "unicode-confusable"
    # Latin-only typosquat: find the shortest substitution that reconciles the two.
    for span in ("rn", "vv", "cl", "ii", "nn"):
        if span in observed and span not in legitimate:
            target = {"rn": "m", "vv": "w", "cl": "d", "ii": "u", "nn": "m"}[span]
            if observed.replace(span, target) == legitimate:
                return f"{target}->{span}"
    return "typosquat"


@dataclass(frozen=True)
class Fingerprint:
    """The reusable part of an attack. Deliberately excludes the specific domain and vendor,
    because those change per victim while the tradecraft does not."""

    technique: str | None            # 'm->rn', 'unicode-confusable', 'typosquat'
    beneficiary_name: str            # the account name the attacker asked funds be sent to
    bank_name: str
    domain_age_bucket: str           # '<14d', '<30d', '<90d', 'established'
    supplied_own_contact: bool       # offered its own phone/email for "verification"
    channel: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "technique": self.technique,
            "beneficiary_name": self.beneficiary_name,
            "bank_name": self.bank_name,
            "domain_age_bucket": self.domain_age_bucket,
            "supplied_own_contact": self.supplied_own_contact,
            "channel": self.channel,
        }


@dataclass
class RecallMatch:
    prior_case_id: str
    prior_vendor_id: str | None
    prior_outcome: str
    score: float                     # 0.0-1.0
    matched_on: list[str] = field(default_factory=list)
    fingerprint: dict[str, Any] = field(default_factory=dict)
    # The dossier Scribe wrote when this operation was first blocked. Carrying it here is what
    # lets the Attribution agent reason about a named adversary rather than a bag of features.
    dossier: dict[str, Any] = field(default_factory=dict)

    @property
    def designation(self) -> str:
        return str(self.dossier.get("designation") or "Unnamed Operation")

    def as_dict(self) -> dict[str, Any]:
        return {
            "prior_case_id": self.prior_case_id,
            "prior_vendor_id": self.prior_vendor_id,
            "prior_outcome": self.prior_outcome,
            "score": round(self.score, 3),
            "matched_on": self.matched_on,
            "fingerprint": self.fingerprint,
            "dossier": self.dossier,
            "designation": self.designation,
        }


# What each signal is worth. Beneficiary name and technique carry the most weight because they
# are the hardest parts of the operation for an attacker to vary cheaply.
WEIGHTS = {
    "beneficiary_name": 0.40,
    "technique": 0.30,
    "bank_name": 0.15,
    "domain_age_bucket": 0.10,
    "supplied_own_contact": 0.05,
}

# Below this, a "match" is coincidence — two unrelated attacks both using a new domain.
MATCH_THRESHOLD = 0.45


def _normalise_entity(name: str) -> str:
    drop = {"llc", "inc", "ltd", "corp", "co", "group", "holdings", "partners", "the"}
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w and w not in drop]
    return " ".join(words)


def score_match(candidate: Fingerprint, prior: Fingerprint) -> tuple[float, list[str]]:
    score = 0.0
    matched: list[str] = []

    if _normalise_entity(candidate.beneficiary_name) == _normalise_entity(prior.beneficiary_name):
        score += WEIGHTS["beneficiary_name"]
        matched.append(f"same beneficiary name '{prior.beneficiary_name}'")
    if candidate.technique and candidate.technique == prior.technique:
        score += WEIGHTS["technique"]
        matched.append(f"same domain technique '{prior.technique}'")
    if candidate.bank_name == prior.bank_name:
        score += WEIGHTS["bank_name"]
        matched.append(f"same receiving bank '{prior.bank_name}'")
    if candidate.domain_age_bucket == prior.domain_age_bucket == "<14d":
        score += WEIGHTS["domain_age_bucket"]
        matched.append("both used a domain registered within 14 days")
    if candidate.supplied_own_contact and prior.supplied_own_contact:
        score += WEIGHTS["supplied_own_contact"]
        matched.append("both supplied their own contact number")

    return score, matched


class RecallPort(Protocol):
    async def remember(self, case_id: str, vendor_id: str | None, outcome: str,
                       fp: Fingerprint, dossier: dict[str, Any] | None = None,
                       tenant_id: str = DEFAULT_TENANT_ID) -> None: ...
    async def recall(self, fp: Fingerprint,
                     tenant_id: str = DEFAULT_TENANT_ID) -> list[RecallMatch]: ...
    async def known_count(self, tenant_id: str | None = None) -> int: ...
    async def library(self, tenant_id: str | None = None) -> list[dict[str, Any]]: ...


class LocalRecall:
    """In-process threat memory. The GEAP-backed variant writes the same fingerprints through
    `sessions.appendEvent` so they survive process death and are auditable per case.

    Partitioned by tenant, because a district's own memory names its own case ids and its own
    victim vendors. Tradecraft crosses a district boundary only through the exchange, which
    strips both. Reads default to the first district so every pre-tenancy caller keeps the
    behaviour it had; `tenant_id=None` on the two reporting methods means "the whole fleet".
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    async def remember(self, case_id: str, vendor_id: str | None, outcome: str,
                       fp: Fingerprint, dossier: dict[str, Any] | None = None,
                       tenant_id: str = DEFAULT_TENANT_ID) -> None:
        # Only blocked attempts are worth remembering as tradecraft. Remembering a released
        # change would teach the fleet to distrust legitimate behaviour.
        if outcome != "BLOCK":
            return
        if any(e["case_id"] == case_id for e in self._entries):
            return
        self._entries.append({
            "tenant_id": tenant_id,
            "case_id": case_id,
            "vendor_id": vendor_id,
            "outcome": outcome,
            "fingerprint": fp,
            "dossier": dossier or {},
        })

    def _scoped(self, tenant_id: str | None) -> list[dict[str, Any]]:
        if tenant_id is None:
            return list(self._entries)
        return [e for e in self._entries if e["tenant_id"] == tenant_id]

    async def recall(self, fp: Fingerprint,
                     tenant_id: str = DEFAULT_TENANT_ID) -> list[RecallMatch]:
        matches: list[RecallMatch] = []
        for e in self._scoped(tenant_id):
            score, matched_on = score_match(fp, e["fingerprint"])
            if score >= MATCH_THRESHOLD:
                matches.append(
                    RecallMatch(
                        prior_case_id=e["case_id"],
                        prior_vendor_id=e["vendor_id"],
                        prior_outcome=e["outcome"],
                        score=score,
                        matched_on=matched_on,
                        fingerprint=e["fingerprint"].as_dict(),
                        dossier=e["dossier"],
                    )
                )
        return sorted(matches, key=lambda m: m.score, reverse=True)

    async def known_count(self, tenant_id: str | None = None) -> int:
        return len(self._scoped(tenant_id))

    async def library(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """The threat library, grouped by OPERATION rather than by case.

        A second sighting of the same operators is not a second adversary. Listing one row per
        blocked case showed "Deceptive Transit" twice, which reads as two separate groups when
        it is one group hitting two victims — and the sighting count is the more interesting
        number anyway, because it says they are still active.
        """
        grouped: dict[str, dict[str, Any]] = {}
        for e in reversed(self._scoped(tenant_id)):
            name = e["dossier"].get("designation") or "Unnamed Operation"
            entry = grouped.get(name)
            if entry is None:
                grouped[name] = {
                    "designation": name,
                    "dossier": e["dossier"],
                    "first_seen_case_id": e["dossier"].get("first_seen_case_id") or e["case_id"],
                    "sightings": [
                        {"case_id": e["case_id"], "vendor_id": e["vendor_id"],
                         "fingerprint": e["fingerprint"].as_dict()}
                    ],
                    # Kept for consumers that predate grouping.
                    "case_id": e["case_id"],
                    "vendor_id": e["vendor_id"],
                    "fingerprint": e["fingerprint"].as_dict(),
                }
            else:
                entry["sightings"].append(
                    {"case_id": e["case_id"], "vendor_id": e["vendor_id"],
                     "fingerprint": e["fingerprint"].as_dict()}
                )
        for entry in grouped.values():
            entry["sighting_count"] = len(entry["sightings"])
            entry["victims"] = sorted(
                {s["vendor_id"] for s in entry["sightings"] if s["vendor_id"]}
            )
        return list(grouped.values())

    def reset(self) -> None:
        self._entries.clear()


def fingerprint_from_request(
    *, proposed_account_name: str, proposed_bank: str, reply_to_domain: str,
    vendor_domain: str, domain_age_days: int | None, supplied_phone: str | None, channel: str,
) -> Fingerprint:
    if domain_age_days is None:
        bucket = "established"
    elif domain_age_days < 14:
        bucket = "<14d"
    elif domain_age_days < 30:
        bucket = "<30d"
    elif domain_age_days < 90:
        bucket = "<90d"
    else:
        bucket = "established"

    return Fingerprint(
        technique=_homoglyph_technique(reply_to_domain, vendor_domain),
        beneficiary_name=proposed_account_name,
        bank_name=proposed_bank,
        domain_age_bucket=bucket,
        supplied_own_contact=bool(supplied_phone),
        channel=channel,
    )
