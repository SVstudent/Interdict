"""Nothing that reaches a prompt may vary between two runs of the same beat.

The replay cache keys on `(agent, model, instruction, observations)`. If any of those carries a
value that is fresh on every run — a uuid, an arrival order, a wall-clock reading — that agent's
key never repeats and its response can never be served from the cache. The failure is quiet and
badly signposted: replay mode raises `ReplayMiss` naming the agent that MISSED, which is the
agent downstream of the one that introduced the randomness.

That is exactly how this shipped. `build_finding` minted a `uuid4` per finding and
`sentry.open_case` minted one per case, and both ids flowed into the Challenger's observations —
directly, and through the attribution finding's evidence, which quotes the prior case it
recognised an operation from. So the Challenger's hash differed every run, `make rehearse` and
credential-free CI could not complete a single scenario, and the 503 pointed at the Challenger.

These tests fail on the randomness rather than on its downstream symptom.
"""
from __future__ import annotations

import hashlib
import re

from app.agents.base import TOOL_PROTOCOL, InterdictAgent
from app.agents.challenger import ChallengerAgent
from app.agents.sentry import SentryAgent
from app.config import Settings
from app.demo.replay import prompt_hash
from app.models.domain import EvidenceRef, Finding

UUID_HEX = re.compile(r"[0-9a-f]{8,}")


def _finding(agent: str, signal: str, verdict: str = "contradicts") -> Finding:
    return Finding(
        finding_id=f"F-{agent}-{signal[:6]}",
        agent=agent,
        agent_version="1.0.0",
        signal=signal,
        verdict=verdict,
        confidence=0.9,
        evidence=[EvidenceRef(source="test", locator=agent, excerpt="observed")],
        reasoning=f"{agent} reasoning",
    )


# --- identifiers ----------------------------------------------------------------------------


def test_a_finding_id_is_derived_not_random():
    """Two agents of the same class, same signal, must mint the same finding id."""
    settings = Settings()

    class _Probe(InterdictAgent):
        name = "provenance"
        version = "1.1.0"
        signal = "artifact_forensics"

    evidence = [EvidenceRef(source="email_headers", locator="Reply-To", excerpt="observed")]
    first = _Probe(settings).build_finding(
        verdict="contradicts", confidence=0.9, reasoning="r", evidence=evidence, latency_ms=1,
    )
    second = _Probe(settings).build_finding(
        verdict="contradicts", confidence=0.9, reasoning="r", evidence=evidence, latency_ms=1,
    )
    assert first.finding_id == second.finding_id, (
        "finding ids are random again; the Challenger's prompt hash will change every run and "
        "replay mode will 503 on the Challenger rather than on this"
    )


async def test_a_case_id_is_derived_from_its_request(repo, clock, world):
    """The case id propagates into evidence excerpts, so it has to be reproducible."""
    request = world["request"]
    settings = Settings()
    sentry = SentryAgent(settings)

    expected = hashlib.sha256(request.request_id.encode()).hexdigest()[:6].upper()
    assert f"CASE-{expected}".startswith("CASE-")

    from app.agents.base import AgentContext

    ctx = AgentContext(case_id="", repo=repo, clock=clock, settings=settings,
                       replay=None, telemetry=None, llm=None)
    one = await sentry.open_case(ctx, request)
    two = await sentry.open_case(ctx, request)
    assert one.case_id == two.case_id == f"CASE-{expected}", (
        "case ids are random again; every evidence locator built from one will differ per run"
    )


# --- ordering -------------------------------------------------------------------------------


async def test_the_challenger_hashes_the_same_findings_in_any_arrival_order(repo, clock):
    """The four lanes are concurrent, so arrival order is nondeterministic. It must not matter."""
    settings = Settings()
    challenger = ChallengerAgent(settings)

    findings = [
        _finding("provenance", "artifact_forensics"),
        _finding("ledger", "relationship_baseline"),
        _finding("registry-check", "entity_attestation"),
        _finding("callback", "out_of_band_confirmation"),
    ]

    seen: set[str] = set()
    captured: list[dict] = []

    async def capture(ctx, prompt, observations):  # noqa: ANN001
        captured.append(observations)
        seen.add(prompt_hash(challenger.name, challenger.model, prompt, observations))
        return {"strongest_legitimate_explanation": "an acquisition would explain it",
                "rebuttals": [], "survived": False, "reasoning": "defeated on the evidence"}

    challenger.infer = capture  # type: ignore[method-assign]

    from app.agents.base import AgentContext
    from app.platform.telemetry import LocalTelemetry

    ctx = AgentContext(case_id="CASE-TEST", repo=repo, clock=clock, settings=settings,
                       replay=None, telemetry=LocalTelemetry(), llm=None,
                       payload={"claimed_reason": "treasury consolidation"})

    await challenger.review(ctx, list(findings))
    await challenger.review(ctx, list(reversed(findings)))

    assert len(seen) == 1, (
        "the Challenger's prompt hash depends on the order its findings arrived in; the fan-out "
        "is concurrent, so that order is whatever the network returned and the cache will miss"
    )
    ordering = [f["agent"] for f in captured[0]["findings"]]
    assert ordering == sorted(ordering), "findings reach the model unsorted"


# --- the instruction ------------------------------------------------------------------------


def test_the_hashed_instruction_is_the_one_the_model_receives():
    """The tool protocol is appended to every prompt, so it must be inside the key.

    Hashing the bare prompt while sending prompt + protocol would let a cached response be
    served for an instruction the model never saw — the precise failure CACHE.md forbids.
    """
    prompt = "You are Provenance."
    bare = prompt_hash("provenance", "gemini-3.6-flash", prompt, {})
    effective = prompt_hash("provenance", "gemini-3.6-flash", f"{prompt}\n{TOOL_PROTOCOL}", {})
    assert bare != effective, (
        "the tool protocol does not affect the cache key; changing it would silently reuse "
        "responses recorded under different instructions"
    )


def test_no_agent_prompt_carries_a_hex_blob():
    """A uuid inside a prompt is the tell for the whole bug class."""
    from app.agents import (adjudicator, callback, challenger, hunter, ledger, precedent,
                            provenance, redteam, registry_check, scribe, sentry)

    offenders: list[str] = []
    for module in (adjudicator, callback, challenger, hunter, ledger, precedent,
                   provenance, redteam, registry_check, scribe, sentry):
        for attr in dir(module):
            if not attr.isupper():
                continue
            value = getattr(module, attr)
            if isinstance(value, str) and UUID_HEX.search(value):
                offenders.append(f"{module.__name__}.{attr}")
    assert not offenders, f"prompt constants contain hex blobs: {offenders}"
