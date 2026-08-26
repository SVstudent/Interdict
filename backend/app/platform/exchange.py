"""The threat exchange — one shared library, many districts.

The gap this closes: cross-case recall (`recall.py`) gives one district institutional memory, but
a district that has never met an operator still meets them cold. Districts are hit by the same
operators in sequence, and none of them have a security team to compare notes with.

So tenancy is deliberately asymmetric. Money, vendors, payments and cases are partitioned per
district and one tenant may never see another's. TRADECRAFT is not partitioned: when district A
blocks an operation, the fingerprint and the dossier are published to a single shared exchange,
and district B recognises the same operators on first contact, citing who contributed the entry.

What crosses the boundary is bounded by the fingerprint's own design (`recall.Fingerprint`), which
already excludes the victim vendor and the specific domain because those change per victim. What
is published is the method, never who it was used against — a district sharing intelligence must
not be publishing its own supplier list.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from .recall import Fingerprint, MATCH_THRESHOLD, score_match


@dataclass
class ExchangeMatch:
    """A hit against an entry another district contributed."""

    entry_id: str
    contributed_by_tenant_id: str
    prior_case_id: str
    designation: str
    score: float
    matched_on: list[str] = field(default_factory=list)
    fingerprint: dict[str, Any] = field(default_factory=dict)
    dossier: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "contributed_by_tenant_id": self.contributed_by_tenant_id,
            "prior_case_id": self.prior_case_id,
            "designation": self.designation,
            "score": round(self.score, 3),
            "matched_on": self.matched_on,
            "fingerprint": self.fingerprint,
            "dossier": self.dossier,
        }


class ExchangePort(Protocol):
    async def publish(self, tenant_id: str, case_id: str, fp: Fingerprint,
                      dossier: dict[str, Any], published_at: str) -> str: ...
    async def lookup(self, fp: Fingerprint, tenant_id: str) -> list[ExchangeMatch]: ...
    async def note_recognition(self, tenant_id: str, case_id: str,
                               match: ExchangeMatch, recognised_at: str) -> None: ...
    async def entries(self) -> list[dict[str, Any]]: ...
    async def recognitions(self) -> list[dict[str, Any]]: ...
    async def members(self) -> list[str]: ...


class LocalExchange:
    """In-process shared library. Scoring is `recall`'s, unchanged.

    Reusing the same weighted match matters beyond saving code: a cross-district recognition must
    be exactly as hard to earn as a within-district one, or the exchange becomes a source of
    false positives that a district cannot investigate because the prior case is not theirs.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._recognitions: list[dict[str, Any]] = []

    async def publish(self, tenant_id: str, case_id: str, fp: Fingerprint,
                      dossier: dict[str, Any], published_at: str) -> str:
        existing = next((e for e in self._entries if e["case_id"] == case_id), None)
        if existing is not None:
            return str(existing["entry_id"])
        entry_id = f"EX-{uuid.uuid4().hex[:10].upper()}"
        self._entries.append({
            "entry_id": entry_id,
            "tenant_id": tenant_id,
            "case_id": case_id,
            "designation": dossier.get("designation") or "Unnamed Operation",
            "fingerprint": fp,
            "dossier": dossier,
            "published_at": published_at,
        })
        return entry_id

    async def lookup(self, fp: Fingerprint, tenant_id: str) -> list[ExchangeMatch]:
        """Only OTHER districts' entries.

        A tenant's own blocks already reach it through `recall`; returning them here as well
        would double-count them and, worse, let the UI claim a cross-district recognition that
        never crossed a district boundary.
        """
        matches: list[ExchangeMatch] = []
        for entry in self._entries:
            if entry["tenant_id"] == tenant_id:
                continue
            score, matched_on = score_match(fp, entry["fingerprint"])
            if score >= MATCH_THRESHOLD:
                matches.append(ExchangeMatch(
                    entry_id=entry["entry_id"],
                    contributed_by_tenant_id=entry["tenant_id"],
                    prior_case_id=entry["case_id"],
                    designation=entry["designation"],
                    score=score,
                    matched_on=matched_on,
                    fingerprint=entry["fingerprint"].as_dict(),
                    dossier=entry["dossier"],
                ))
        return sorted(matches, key=lambda m: m.score, reverse=True)

    async def note_recognition(self, tenant_id: str, case_id: str,
                               match: ExchangeMatch, recognised_at: str) -> None:
        """Record that the exchange paid off. This is the measurable claim the feature makes, so
        it is a stored fact rather than something recomputed from the case list."""
        if any(r["case_id"] == case_id and r["entry_id"] == match.entry_id
               for r in self._recognitions):
            return
        self._recognitions.append({
            "case_id": case_id,
            "tenant_id": tenant_id,
            "contributed_by_tenant_id": match.contributed_by_tenant_id,
            "entry_id": match.entry_id,
            "prior_case_id": match.prior_case_id,
            "designation": match.designation,
            "score": round(match.score, 3),
            "matched_on": match.matched_on,
            "recognised_at": recognised_at,
        })

    async def entries(self) -> list[dict[str, Any]]:
        seen_by: dict[str, set[str]] = {}
        for r in self._recognitions:
            seen_by.setdefault(r["entry_id"], set()).add(r["tenant_id"])
        return [
            {
                "entry_id": e["entry_id"],
                "contributed_by_tenant_id": e["tenant_id"],
                "first_seen_case_id": e["case_id"],
                "designation": e["designation"],
                "fingerprint": e["fingerprint"].as_dict(),
                "dossier": e["dossier"],
                "published_at": e["published_at"],
                "recognised_by_tenant_ids": sorted(seen_by.get(e["entry_id"], set())),
            }
            for e in reversed(self._entries)
        ]

    async def recognitions(self) -> list[dict[str, Any]]:
        return list(reversed(self._recognitions))

    async def members(self) -> list[str]:
        return sorted({e["tenant_id"] for e in self._entries})

    def reset(self) -> None:
        self._entries.clear()
        self._recognitions.clear()
