"""Precedent — the fleet learns the organisation's risk appetite.

The gap this closes: an ESCALATE dead-ends at a human. They decide, the money moves or does not,
and their reasoning walks out of the building with them. The next structurally identical case
escalates again, and the fleet is exactly as ignorant as it was the first time.

A precedent is that reasoning made durable: {what the case looked like, what the human chose, why}.
Later cases are matched against the book and cite it, so the adjudicator can say "this district
released a case exactly like this one, and here is who decided and why" instead of asking again.

Same shape as `recall.py` and for the same reason: retrieval is a deterministic weighted match
over structured characteristics, so it is free, fast, and structurally incapable of inventing a
decision the organisation never made. The judgement of whether the precedent actually GOVERNS is
argued by the precedent-clerk agent on top of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from ..models.domain import (
    Case,
    Precedent,
    PrecedentKey,
    Vendor,
    exposure_band,
    tenure_band,
    verdict_pattern,
)
from ..store.base import Repository

# What each characteristic is worth. The verdict pattern dominates because it is what the fleet
# actually concluded — the substance of the decision the human was asked to overrule. Tenure is
# worth least because a five-year vendor and a six-year vendor read identically.
WEIGHTS = {
    "verdict_pattern": 0.40,
    "exposure_band": 0.30,
    "callback_resolved": 0.20,
    "vendor_tenure_band": 0.10,
}

# Deliberately far above recall's 0.45. A recall match only raises suspicion; a cited precedent
# argues for moving money, so the bar to reach for one is higher. At 0.75 the arithmetic means a
# citation requires the exposure band, the callback state and substantially the same verdict
# pattern to agree — tenure is the only characteristic allowed to differ on its own.
CITE_THRESHOLD = 0.75


def key_from_case(
    case: Case,
    vendor: Vendor | None,
    *,
    now: datetime,
    callback_threshold: Decimal,
    release_ceiling: Decimal,
) -> PrecedentKey:
    """Reduce a case to the four characteristics precedent keys on."""
    callback = case.finding_by_agent("callback")
    return PrecedentKey(
        exposure_band=exposure_band(
            case.exposure_amount,
            callback_threshold=callback_threshold,
            release_ceiling=release_ceiling,
        ),
        verdict_pattern=verdict_pattern(case.findings),
        callback_resolved=callback is not None and callback.is_committed,
        vendor_tenure_band=tenure_band(vendor.tenure_days(now) if vendor else 0),
    )


def score_precedent(candidate: PrecedentKey, prior: PrecedentKey) -> tuple[float, list[str]]:
    """How closely a live case resembles a decided one, and why.

    The verdict pattern scores by overlap rather than equality. Exact equality would mean a
    precedent is essentially never citable a second time — four lanes with three verdicts each
    is too large a space — while overlap degrades honestly: three lanes out of four agreeing is
    a weaker citation than four, and two out of four is not a citation at all.
    """
    score = 0.0
    matched: list[str] = []

    a, b = set(candidate.verdict_pattern), set(prior.verdict_pattern)
    union = a | b
    overlap = len(a & b) / len(union) if union else 0.0
    if overlap:
        score += WEIGHTS["verdict_pattern"] * overlap
        matched.append(
            f"{len(a & b)} of {len(union)} agent verdicts identical "
            f"({', '.join(sorted(a & b))})"
        )
    if candidate.exposure_band == prior.exposure_band:
        score += WEIGHTS["exposure_band"]
        matched.append(f"same exposure band '{prior.exposure_band}'")
    if candidate.callback_resolved == prior.callback_resolved:
        score += WEIGHTS["callback_resolved"]
        matched.append(
            "the vendor was reached on the number of record in both"
            if prior.callback_resolved
            else "nobody answered the callback in either"
        )
    if candidate.vendor_tenure_band == prior.vendor_tenure_band:
        score += WEIGHTS["vendor_tenure_band"]
        matched.append(f"same vendor tenure band '{prior.vendor_tenure_band}'")

    return score, matched


@dataclass
class PrecedentMatch:
    precedent_id: str
    prior_case_id: str
    outcome: str
    rationale: str
    decided_by: str
    decided_at: datetime
    score: float
    matched_on: list[str] = field(default_factory=list)
    key: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "precedent_id": self.precedent_id,
            "prior_case_id": self.prior_case_id,
            "outcome": self.outcome,
            "rationale": self.rationale,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat(),
            "score": round(self.score, 3),
            "matched_on": self.matched_on,
            "key": self.key,
        }


class PrecedentPort(Protocol):
    async def record(self, precedent: Precedent) -> None: ...
    async def match(self, key: PrecedentKey, tenant_id: str) -> list[PrecedentMatch]: ...
    async def cite(self, precedent_id: str, case_id: str) -> None: ...
    async def book(self, tenant_id: str | None = None) -> list[dict[str, Any]]: ...


class LocalPrecedent:
    """Repository-backed precedent book.

    Unlike `LocalRecall`, this holds no in-process state: a precedent is a human's decision and
    losing it to a process restart would mean asking them the same question twice. Everything
    reads through the Repository, so the Firestore implementation gets durability for free.
    """

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    async def record(self, precedent: Precedent) -> None:
        await self._repo.save_precedent(precedent)

    async def match(self, key: PrecedentKey, tenant_id: str) -> list[PrecedentMatch]:
        """Precedent is scoped to ONE tenant, always.

        This is the deliberate asymmetry with the threat exchange: tradecraft is shared between
        districts because an attacker is the same attacker everywhere, but risk appetite is not.
        One district's willingness to release at $180,000 says nothing about another's.
        """
        matches: list[PrecedentMatch] = []
        for prior in await self._repo.list_precedents(tenant_id):
            score, matched_on = score_precedent(key, prior.key)
            if score >= CITE_THRESHOLD:
                matches.append(
                    PrecedentMatch(
                        precedent_id=prior.precedent_id,
                        prior_case_id=prior.case_id,
                        outcome=prior.outcome,
                        rationale=prior.rationale,
                        decided_by=prior.decided_by,
                        decided_at=prior.decided_at,
                        score=score,
                        matched_on=matched_on,
                        key=prior.key.model_dump(mode="json"),
                    )
                )
        return sorted(matches, key=lambda m: m.score, reverse=True)

    async def cite(self, precedent_id: str, case_id: str) -> None:
        """Record that a case leaned on this precedent. The citation list is what makes the book
        auditable: a reviewer can ask which decisions a single human ruling went on to shape."""
        prior = await self._repo.get_precedent(precedent_id)
        if prior is None or case_id in prior.cited_by_case_ids:
            return
        prior.cited_by_case_ids.append(case_id)
        await self._repo.save_precedent(prior)

    async def book(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return [
            p.model_dump(mode="json") for p in await self._repo.list_precedents(tenant_id)
        ]
