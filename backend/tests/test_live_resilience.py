"""What the fleet does when a model misbehaves mid-take.

The demo is one unedited live recording, so every one of these is a scenario that would otherwise
end the take. None of them is hypothetical: Gemini 3.x Flash are thinking models driven through
ADK with tools, and a step can end having spent its output budget on reasoning and a tool call
without emitting any final text at all.

The rule these encode: a formatting miss must never be able to change an outcome or sink a case.
A genuine failure of judgment still must.
"""
from __future__ import annotations

import json

import pytest

from app.agents.base import (REPAIR_SUFFIX, AgentContext, InterdictAgent,
                             MalformedModelOutput)
from app.agents.challenger import ChallengerAgent
from app.config import Settings
from app.models.domain import ChallengeResult, EvidenceRef, Finding


class _Replay:
    """Stands in for the cache in live mode: always calls through, never stores."""

    async def resolve(self, key, call, *, label=""):  # noqa: ANN001
        return await call()


class _Telemetry:
    def __init__(self) -> None:
        self.tools: list[str] = []
        self.tokens = 0

    def tool_call(self, **kw) -> None:
        self.tools.append(kw.get("tool", ""))

    def record_tokens(self, **kw) -> None:
        self.tokens += kw.get("tokens", 0)


class _Probe(InterdictAgent):
    name = "provenance"
    version = "1.1.0"
    signal = "artifact_forensics"


def _ctx(repo, clock) -> AgentContext:
    return AgentContext(case_id="CASE-TEST", repo=repo, clock=clock, settings=Settings(),
                        replay=_Replay(), telemetry=_Telemetry(), llm=None, payload={})


def _patch_adk(monkeypatch, replies: list[str]) -> list[str]:
    """Feed `infer_via_adk` a scripted sequence of replies; record the instructions it saw."""
    seen: list[str] = []
    queue = list(replies)

    async def fake(agent, ctx, *, instruction, observations):  # noqa: ANN001
        seen.append(instruction)
        return queue.pop(0), 10, 20

    monkeypatch.setattr("app.agents.base.infer_via_adk", fake)
    return seen


# --- the parse-and-repair path ---------------------------------------------------------------


async def test_a_clean_reply_is_returned_without_a_second_call(repo, clock, monkeypatch):
    seen = _patch_adk(monkeypatch, ['{"verdict": "contradicts", "confidence": 0.9}'])
    ctx = _ctx(repo, clock)

    result = await _Probe(Settings()).infer(ctx, "PROMPT", {"a": 1})

    assert result["verdict"] == "contradicts"
    assert len(seen) == 1, "a parseable reply must not trigger a repair round-trip"
    assert REPAIR_SUFFIX not in seen[0]


async def test_an_empty_reply_is_repaired_rather_than_crashing(repo, clock, monkeypatch):
    """A thinking model that spends its whole budget on reasoning returns no text at all."""
    seen = _patch_adk(monkeypatch, ["", '{"verdict": "inconclusive", "confidence": 0.4}'])
    ctx = _ctx(repo, clock)

    result = await _Probe(Settings()).infer(ctx, "PROMPT", {"a": 1})

    assert result["verdict"] == "inconclusive"
    assert len(seen) == 2
    assert REPAIR_SUFFIX in seen[1], "the repair attempt did not carry the format correction"


async def test_prose_around_the_json_is_repaired(repo, clock, monkeypatch):
    seen = _patch_adk(monkeypatch, [
        'Certainly. Here is my analysis:\n{"verdict": "contradicts"}\nLet me know if you need more.',
        '{"verdict": "contradicts", "confidence": 0.95}',
    ])
    ctx = _ctx(repo, clock)

    result = await _Probe(Settings()).infer(ctx, "PROMPT", {"a": 1})
    assert result["confidence"] == 0.95
    assert len(seen) == 2


async def test_a_markdown_fence_is_handled_without_a_repair(repo, clock, monkeypatch):
    """Already handled by Completion.json; asserted so the repair path is not spent on it."""
    seen = _patch_adk(monkeypatch, ['```json\n{"verdict": "supports", "confidence": 0.7}\n```'])
    ctx = _ctx(repo, clock)

    result = await _Probe(Settings()).infer(ctx, "PROMPT", {"a": 1})
    assert result["verdict"] == "supports"
    assert len(seen) == 1, "a fenced reply should parse directly, not cost a round-trip"


async def test_a_json_scalar_is_not_mistaken_for_a_result(repo, clock, monkeypatch):
    """`json.loads("null")` succeeds and then every caller raises on subscripting it."""
    seen = _patch_adk(monkeypatch, ["null", '{"verdict": "inconclusive", "confidence": 0.1}'])
    ctx = _ctx(repo, clock)

    result = await _Probe(Settings()).infer(ctx, "PROMPT", {"a": 1})
    assert isinstance(result, dict)
    assert len(seen) == 2


async def test_two_bad_replies_fail_loudly_and_carry_the_raw_text(repo, clock, monkeypatch):
    """It must not loop, and the error must be diagnosable from the log during a recording."""
    _patch_adk(monkeypatch, ["not json at all", "still not json"])
    ctx = _ctx(repo, clock)

    with pytest.raises(MalformedModelOutput) as exc:
        await _Probe(Settings()).infer(ctx, "PROMPT", {"a": 1})

    assert "provenance" in str(exc.value)
    assert "still not json" in str(exc.value), "the raw reply was not carried into the error"


async def test_the_repair_round_trip_is_counted_in_tokens(repo, clock, monkeypatch):
    """A retry that is invisible in the telemetry under-reports what the case actually cost."""
    _patch_adk(monkeypatch, ["", '{"verdict": "supports"}'])
    ctx = _ctx(repo, clock)

    await _Probe(Settings()).infer(ctx, "PROMPT", {"a": 1})

    assert ctx.telemetry.tokens == 60, "repair tokens were dropped from the telemetry"
    assert "format_repair" in ctx.telemetry.tools


# --- the Challenger's narrative output --------------------------------------------------------


def _findings() -> list[Finding]:
    return [
        Finding(finding_id="F-provenance-artifa", agent="provenance", agent_version="1.1.0",
                signal="artifact_forensics", verdict="contradicts", confidence=0.98,
                evidence=[EvidenceRef(source="headers", locator="Reply-To", excerpt="lookalike")],
                reasoning="spoofed domain"),
    ]


async def _challenge(repo, clock, monkeypatch, reply: dict) -> ChallengeResult:
    challenger = ChallengerAgent(Settings())

    async def fake_infer(ctx, prompt, observations):  # noqa: ANN001
        return reply

    challenger.infer = fake_infer  # type: ignore[method-assign]
    ctx = _ctx(repo, clock)
    return await challenger.review(ctx, _findings())


async def test_the_challenge_survives_a_reply_missing_every_narrative_key(repo, clock, monkeypatch):
    """This exact KeyError would have sunk the case at the moment beat 2 peaks."""
    result = await _challenge(repo, clock, monkeypatch, {})

    assert isinstance(result, ChallengeResult)
    assert result.strongest_legitimate_explanation.strip()
    assert result.reasoning.strip()
    assert result.survived is False
    assert result.rebuttals == []


async def test_a_malformed_rebuttal_entry_is_dropped_not_fatal(repo, clock, monkeypatch):
    result = await _challenge(repo, clock, monkeypatch, {
        "strongest_legitimate_explanation": "an acquisition",
        "reasoning": "considered and rejected",
        "rebuttals": [
            "a bare string where an object belongs",
            {"finding_id": "F-does-not-exist", "argument": "irrelevant", "succeeds": True},
            {"finding_id": "F-provenance-artifa", "argument": "weak", "succeeds": False},
        ],
    })
    assert [r.finding_id for r in result.rebuttals] == ["F-provenance-artifa"]


async def test_a_rebuttal_with_no_argument_still_constructs(repo, clock, monkeypatch):
    """Rebuttal.argument is required by the model; an empty string must not fail validation."""
    result = await _challenge(repo, clock, monkeypatch, {
        "strongest_legitimate_explanation": "an acquisition",
        "reasoning": "r",
        "rebuttals": [{"finding_id": "F-provenance-artifa", "succeeds": False}],
    })
    assert len(result.rebuttals) == 1
    assert result.rebuttals[0].argument.strip()


async def test_the_challenge_cannot_invent_a_rebuttal_that_defeats_a_real_finding(
    repo, clock, monkeypatch,
):
    """The defensive reads must not have loosened the id check that keeps rebuttals honest."""
    result = await _challenge(repo, clock, monkeypatch, {
        "strongest_legitimate_explanation": "x",
        "reasoning": "r",
        "rebuttals": [{"finding_id": "F-invented", "argument": "defeated!", "succeeds": True}],
    })
    assert result.rebuttals == [], (
        "a rebuttal naming a finding that does not exist was allowed to stand"
    )
