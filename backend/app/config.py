"""Settings and the injected Clock.

The Clock is injected, never global-imported into domain code. Every timestamp in Interdict
reads from it so that `POST /api/demo/advance_clock` can move the whole system four days forward
without touching the wall clock (demo beat 5). `tests/test_no_wallclock.py` enforces that no
module under `app/` calls `datetime.now()` directly.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic_settings import BaseSettings, SettingsConfigDict

# Single source of truth for provider identity. Defining a parallel enum here caused
# `settings.LLM_PROVIDER is Provider.X` to be permanently False.
from .llm.provider import Provider as LLMProviderChoice


class DemoMode(str, Enum):
    LIVE = "live"
    REPLAY = "replay"
    RECORD = "record"


class PlatformBackend(str, Enum):
    LOCAL = "local"
    GEAP = "geap"


@runtime_checkable
class Clock(Protocol):
    """The only sanctioned source of time."""

    def now(self) -> datetime: ...


class SystemClock:
    """Wall clock. Production default."""

    def now(self) -> datetime:
        # The single sanctioned call site. The grep test allowlists this file.
        return datetime.now(UTC)


class OffsetClock:
    """Wall clock plus an operator-adjustable offset. The live-mode default.

    A live run needs two properties at once and the two obvious clocks each supply only one.
    `SystemClock` gives real elapsed time — which the trace tree's per-node latency depends on —
    but cannot be moved, so `advance_clock` 409s and beat 5 (the wake) is unrecordable. A
    `FrozenClock` can be moved but reports zero elapsed time, so every latency reads 0ms.

    This one keeps real duration and adds a settable delta. Advancing it is a demo control over
    *time*, not over work: a case woken four days on still makes real model calls and reaches
    its verdict on real evidence. Nothing about the fleet's reasoning is simulated.
    """

    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        # Sanctioned call site; the grep test allowlists this file.
        return datetime.now(UTC) + self._offset

    def set(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        self._offset = moment - datetime.now(UTC)
        return self.now()

    def advance(self, *, days: float = 0.0, seconds: float = 0.0) -> datetime:
        self._offset += timedelta(days=days, seconds=seconds)
        return self.now()

    def rewind(self) -> datetime:
        """Drop the accumulated offset. `POST /api/demo/reset` calls this between takes."""
        self._offset = timedelta(0)
        return self.now()


class FrozenClock:
    """Logical clock the demo control plane advances. Deterministic in replay."""

    def __init__(self, initial: datetime) -> None:
        if initial.tzinfo is None:
            initial = initial.replace(tzinfo=UTC)
        self._now = initial

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        self._now = moment
        return self._now

    def advance(self, *, days: float = 0.0, seconds: float = 0.0) -> datetime:
        self._now += timedelta(days=days, seconds=seconds)
        return self._now


# Fixed epoch so replay-mode runs, cached prompts, and audit hashes are byte-identical
# across machines and CI. Chosen to sit after the Nacha Phase 2 effective date (2026-06-19).
DEMO_EPOCH = datetime(2026, 8, 3, 14, 30, 0, tzinfo=UTC)


class Settings(BaseSettings):
    # Absolute, not ".env". A relative path resolves against the PROCESS CWD, and the documented
    # way to start this service is `cd backend && uvicorn app.main:app` — from there ".env" means
    # `backend/.env`, which does not exist, so the file was silently never read. Every setting
    # appeared to work only because the run commands happened to pass the same values as
    # environment variables; the first setting that lived only in .env (INBOX_SOURCE) was the one
    # that exposed it, by reporting `seed` while .env said `gmail`.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore",
    )

    # Model access. `gemini` is the ONLY provider permitted for anything that gets judged —
    # the rules mandate Gemini API or Vertex AI. `tokenrouter` is a third-party aggregator kept
    # for cheap local iteration; it must never produce a recorded artifact. See DECISIONS D-008.
    LLM_PROVIDER: LLMProviderChoice = LLMProviderChoice.VERTEX
    # `global`, NOT a region. Gemini 3.x publisher models are served from the global endpoint;
    # us-central1 returns 404 for them (D-010). This is the model endpoint only — the Agent
    # Runtime and Agent Registry locations below are different values on purpose.
    VERTEX_LOCATION: str = "global"
    TOKENROUTER_API_KEY: str = ""
    TOKENROUTER_BASE_URL: str = "https://api.tokenrouter.io/v1"
    TOKENROUTER_MODEL_PREFIX: str = "google/"

    # Models — verified available 2026-08-21, see DECISIONS D-000.
    GEMINI_API_KEY: str = ""
    # Routine agents. Rules mandate "Gemini 3.5 or newer" (D-007a).
    FLASH_MODEL: str = "gemini-3.6-flash"
    # Challenger + Adjudicator. NOT a Pro model: the only Gemini 3.x Pro is 3.1-pro-preview,
    # and 3.1 < 3.5 fails the mandated version floor. gemini-3.7-flash is the strongest
    # compliant tier, so we keep the tiering and drop the non-compliant model (D-007a).
    REASONING_MODEL: str = "gemini-3.7-flash"
    # Escape hatch only. Setting this to a 3.1/2.5 Pro model breaks rules compliance.
    PRO_MODEL: str = "gemini-3.1-pro-preview"
    USE_PRO_TIER_ACCEPTING_RULES_RISK: bool = False

    # Where the morning's post comes from. `seed` is the fixture inbox and the default
    # everywhere, including every test and every offline replay. `gmail` reads a real mailbox
    # over IMAP, read-only, so the demo can open on messages that actually arrived — see
    # platform/mailbox.py for what that does and does not make real.
    #
    # The app password is a credential and lives in .env, which is gitignored. Generate one at
    # https://myaccount.google.com/apppasswords (needs 2-Step Verification). Nothing in this
    # repository should ever contain its value.
    INBOX_SOURCE: str = "seed"
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""
    GMAIL_FOLDER: str = "INBOX"
    GMAIL_MAX_MESSAGES: int = 25

    # Demo
    DEMO_MODE: DemoMode = DemoMode.REPLAY
    PLATFORM_BACKEND: PlatformBackend = PlatformBackend.LOCAL

    # Adjudication thresholds. These are safety rails enforced in Python, never in a prompt.
    AUTO_RELEASE_CEILING: Decimal = Decimal("250000.00")
    CALLBACK_REQUIRED_THRESHOLD: Decimal = Decimal("50000.00")
    # How long a case waits on an unanswered callback before it stops waiting and decides.
    # Without this a dormant case waits forever: the runbook's beat 4 expects S3 to ESCALATE,
    # but the fan-out suspends on an unresolved callback and nothing ever wakes it, so the
    # adjudication rail that would have escalated it never runs. See D-017.
    CALLBACK_GRACE_HOURS: int = 48
    # The number Callback dials for the scenario vendors. Set this to a real phone you control
    # and the recorded demo performs a genuine out-of-band verification on camera — which is the
    # control this whole product models. Leave unset and the seeded synthetic number is used.
    CALLBACK_DEMO_PHONE: str = ""
    CONTRADICTION_BLOCK_CONFIDENCE: float = 0.85
    MIN_AGGREGATE_SUPPORT: float = 0.6

    # GCP / GEAP. Components are NOT co-located — see DECISIONS D-002a.
    GCP_PROJECT_ID: str = ""
    GEAP_RUNTIME_LOCATION: str = "us-central1"     # reasoningEngines
    GEAP_REGISTRY_LOCATION: str = "global"         # agents
    GEAP_GOVERNANCE_LOCATION: str = "us-central1"  # semanticGovernancePolicies

    # Model Armor is billed per token with 2M/month free and is confirmed working on this
    # project, so it is switchable on its own — we do not have to flip the whole platform to
    # GEAP (which would pull in components with unresolved fixed costs) to use it. See D-013.
    USE_MODEL_ARMOR: bool = True
    MODEL_ARMOR_LOCATION: str = "us-central1"
    MODEL_ARMOR_TEMPLATE: str = "interdict-inbound"

    # Local emulators
    FIRESTORE_EMULATOR_HOST: str | None = None
    PUBSUB_EMULATOR_HOST: str | None = None
    FIRESTORE_DATABASE: str = "(default)"

    def reasoning_model(self) -> str:
        """Model for Challenger and Adjudicator. Defaults to the strongest rules-compliant tier."""
        if self.USE_PRO_TIER_ACCEPTING_RULES_RISK:
            return self.PRO_MODEL
        return self.REASONING_MODEL

    def is_offline(self) -> bool:
        """True when no external model call may be made."""
        return self.DEMO_MODE is DemoMode.REPLAY


def make_clock(settings: Settings) -> Clock:
    """Replay and record runs pin a fixed epoch; live runs track the wall clock but stay movable.

    Live mode used to return a bare `SystemClock`, which made `POST /api/demo/advance_clock`
    return 409 and beats 4 and 5 impossible to record — while the runbook says the recorded
    demo runs live. `OffsetClock` keeps real elapsed time and accepts the advance.
    """
    if settings.DEMO_MODE is DemoMode.LIVE:
        return OffsetClock()
    return FrozenClock(DEMO_EPOCH)
