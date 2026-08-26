"""The dormant-case wake path, and the clock that has to be movable for it to exist.

Both behaviours here shipped broken and a green 185-test suite said nothing, because no test had
ever executed either path end to end — the same failure mode DECISIONS records for D-011 and
D-012. Documented expected outcomes are not tests.

What was broken:

  1. `make_clock` returned a bare `SystemClock` in live mode, so `POST /api/demo/advance_clock`
     answered 409 and the wake beat could not be recorded at all — while the runbook says the
     recorded demo runs live.

  2. Even with a movable clock, a woken case re-entered the fan-out, found the same unanswered
     callback, and suspended again. It could never leave AWAITING_CALLBACK, so the abstention
     that is supposed to resolve into ESCALATE simply stalled forever.
"""
from __future__ import annotations

from datetime import timedelta

from app.config import DEMO_EPOCH, DemoMode, FrozenClock, OffsetClock, Settings, make_clock
from app.models.domain import CaseState


# --- the clock ------------------------------------------------------------------------------


def test_a_live_run_gets_a_clock_that_can_still_be_advanced():
    """Live mode must not hand back an immovable clock: beats 4 and 5 both depend on the wake."""
    clock = make_clock(Settings(DEMO_MODE=DemoMode.LIVE))
    assert isinstance(clock, OffsetClock), (
        "live mode returned a clock the demo control plane cannot advance; "
        "advance_clock will 409 and the dormant-case beat becomes unrecordable"
    )


def test_replay_still_pins_the_fixed_epoch():
    """Replay hashes have to stay byte-identical across machines, so it keeps the frozen clock."""
    clock = make_clock(Settings(DEMO_MODE=DemoMode.REPLAY))
    assert isinstance(clock, FrozenClock)
    assert clock.now() == DEMO_EPOCH


def test_the_offset_clock_reports_real_elapsed_time():
    """The reason live mode is not simply given a FrozenClock.

    Per-node latency on the trace tree reads from the injected clock. A frozen clock would report
    every span as 0ms, which is worse than not showing latency at all.
    """
    clock = OffsetClock()
    first = clock.now()
    for _ in range(200_000):  # cheap, deterministic, and definitely not instantaneous
        pass
    assert clock.now() > first, "a live clock that never ticks reports every latency as zero"


def test_advancing_and_rewinding_the_offset_clock():
    clock = OffsetClock()
    before = clock.now()
    after = clock.advance(days=4)
    assert after - before >= timedelta(days=4)
    # Reset between takes must not leave the next run four days in the future.
    clock.rewind()
    assert clock.now() - before < timedelta(seconds=5)


# --- the wake -------------------------------------------------------------------------------


async def _run_to_dormancy(repo, world, stub_agents, make_runner):
    """Drive a case until it parks on an unanswered callback."""
    runner = make_runner(stub_agents)
    # No callback response: nobody picked up.
    await runner.advance(world["case"].case_id, {"callback_response": None})
    case = await repo.get_case(world["case"].case_id)
    assert case.state is CaseState.AWAITING_CALLBACK, (
        f"expected the case to go dormant on silence, got {case.state}"
    )
    return case


async def test_silence_puts_the_case_to_sleep_rather_than_releasing_it(
    repo, world, stub_agents, make_runner
):
    """Silence is never confirmation. This half already worked; it is asserted so the fix below
    cannot be mistaken for 'proceed whenever the callback is unresolved'."""
    case = await _run_to_dormancy(repo, world, stub_agents, make_runner)
    assert case.decision is None


async def test_a_case_woken_before_its_grace_period_goes_straight_back_to_sleep(
    repo, world, stub_agents, make_runner
):
    """The window is what makes the abstention meaningful. Waking early must change nothing."""
    await _run_to_dormancy(repo, world, stub_agents, make_runner)

    runner = make_runner(stub_agents)
    await runner.advance(world["case"].case_id, {"callback_response": None})

    case = await repo.get_case(world["case"].case_id)
    assert case.state is CaseState.AWAITING_CALLBACK
    assert case.decision is None


async def test_a_lapsed_callback_window_lets_the_case_decide(
    repo, world, stub_agents, make_runner
):
    """THE REGRESSION. Without `callback_window_expired` the case never leaves dormancy.

    The flag has to do two things at once, and the bug needed both: let the fan-out stop
    suspending, AND change the step's checkpoint input. Without the second, the woken run hashes
    identically to the run that put the case to sleep and is skipped as already-done, so the
    outcome is the same stall by a different route.
    """
    await _run_to_dormancy(repo, world, stub_agents, make_runner)

    runner = make_runner(stub_agents)
    await runner.advance(
        world["case"].case_id,
        {"callback_response": None, "callback_window_expired": True},
    )

    case = await repo.get_case(world["case"].case_id)
    assert case.state is not CaseState.AWAITING_CALLBACK, (
        "the grace period lapsed and the case still refused to decide — waiting forever is a "
        "stall, not an abstention"
    )
    assert case.decision is not None, "a woken case reached a terminal state with no decision"


async def test_the_woken_case_still_carries_its_unresolved_callback(
    repo, world, stub_agents, make_runner
):
    """It must decide *because* nobody called back, not by pretending somebody did.

    If the wake path ever synthesised a callback verdict to get the case moving, this is the
    assertion that catches it.
    """
    await _run_to_dormancy(repo, world, stub_agents, make_runner)

    runner = make_runner(stub_agents)
    await runner.advance(
        world["case"].case_id,
        {"callback_response": None, "callback_window_expired": True},
    )

    case = await repo.get_case(world["case"].case_id)
    callback = case.finding_by_agent("callback")
    assert callback is not None
    assert callback.verdict == "inconclusive", (
        f"the wake path invented a callback outcome ({callback.verdict}); silence must stay "
        "silence all the way into adjudication"
    )
