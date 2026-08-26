"""The competition rules mandate Gemini API or Vertex AI. These tests make that mechanical."""
from __future__ import annotations

import pytest

from app.config import DemoMode, LLMProviderChoice, Settings
from app.demo.replay import ReplayCache
from app.llm.provider import (
    Completion,
    Provider,
    ProviderNotCompliant,
    TokenRouterProvider,
    assert_compliant,
    build_provider,
)
from app.store.memory import InMemoryRepository


def test_vertex_is_the_default_provider():
    """Vertex shares an auth path with GEAP and is not subject to per-key free-tier RPM,
    so it is the default for the recorded demo."""
    assert Settings().LLM_PROVIDER is LLMProviderChoice.VERTEX


def test_vertex_passes_the_compliance_gate():
    settings = Settings(
        LLM_PROVIDER=LLMProviderChoice.VERTEX, GCP_PROJECT_ID="proj-test"
    )
    assert_compliant(build_provider(settings))  # must not raise


def test_vertex_requires_a_project_id():
    with pytest.raises(RuntimeError, match="GCP_PROJECT_ID"):
        build_provider(Settings(LLM_PROVIDER=LLMProviderChoice.VERTEX, GCP_PROJECT_ID=""))


def test_tokenrouter_is_rejected_as_compliant():
    provider = TokenRouterProvider("tr_test", "https://api.tokenrouter.io/v1", "google/")
    with pytest.raises(ProviderNotCompliant, match="Gemini API or Vertex AI"):
        assert_compliant(provider)


def test_gemini_passes_the_compliance_gate():
    settings = Settings(GEMINI_API_KEY="test-key", LLM_PROVIDER=LLMProviderChoice.GEMINI)
    assert_compliant(build_provider(settings))  # must not raise


async def test_record_mode_refuses_a_non_compliant_provider():
    """The replay cache feeds the judged recording, so it must never be populated from an
    aggregator."""
    settings = Settings(DEMO_MODE=DemoMode.RECORD)
    cache = ReplayCache(InMemoryRepository(), settings)
    provider = TokenRouterProvider("tr_test", "https://api.tokenrouter.io/v1", "google/")
    with pytest.raises(ProviderNotCompliant):
        cache.assert_recordable(provider)


async def test_replay_mode_allows_any_provider():
    """Replay makes no model calls at all, so the provider is irrelevant there."""
    settings = Settings(DEMO_MODE=DemoMode.REPLAY)
    cache = ReplayCache(InMemoryRepository(), settings)
    provider = TokenRouterProvider("tr_test", "https://api.tokenrouter.io/v1", "google/")
    cache.assert_recordable(provider)  # must not raise


def test_tokenrouter_namespaces_bare_model_ids():
    provider = TokenRouterProvider("tr_test", "https://api.tokenrouter.io/v1", "google/")
    assert provider._qualify("gemini-3.6-flash") == "google/gemini-3.6-flash"
    assert provider._qualify("google/gemini-3.6-flash") == "google/gemini-3.6-flash"


def test_completion_recovers_fenced_json():
    c = Completion(
        text='```json\n{"verdict": "contradicts", "confidence": 0.94}\n```',
        model="gemini-3.6-flash",
        provider=Provider.GEMINI,
    )
    assert c.json()["verdict"] == "contradicts"


@pytest.mark.parametrize(
    "choice,expected",
    [
        (LLMProviderChoice.VERTEX, "VertexProvider"),
        (LLMProviderChoice.GEMINI, "GeminiProvider"),
        (LLMProviderChoice.TOKENROUTER, "TokenRouterProvider"),
    ],
)
def test_every_provider_choice_routes_to_its_implementation(choice, expected):
    """Regression guard.

    config.py once defined its own LLMProviderChoice enum alongside provider.Provider. Because
    `is` compares identity, `settings.LLM_PROVIDER is Provider.TOKENROUTER` was permanently False
    and every non-Gemini branch was unreachable dead code. Assert each choice actually routes.
    """
    settings = Settings(
        LLM_PROVIDER=choice,
        GCP_PROJECT_ID="proj-test",
        GEMINI_API_KEY="key-test",
        TOKENROUTER_API_KEY="tr_test",
    )
    assert type(build_provider(settings)).__name__ == expected


def test_config_and_provider_share_one_enum():
    from app.llm.provider import Provider

    assert LLMProviderChoice is Provider


# --- throttling ---------------------------------------------------------------

async def test_retry_recovers_from_a_transient_429():
    """Vertex throttles on RPM and the fan-out is bursty by design. A 429 mid-recording would be
    fatal, so a transient throttle must be survived rather than surfaced."""
    from app.llm.provider import with_retry

    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. Resource exhausted.")
        return "ok"

    assert await with_retry(flaky, label="test", attempts=5) == "ok"
    assert attempts["n"] == 3


async def test_persistent_throttling_raises_an_actionable_error():
    from app.llm.provider import Throttled, with_retry

    async def always_throttled():
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    with pytest.raises(Throttled, match="requests-per-minute quota"):
        await with_retry(always_throttled, label="test", attempts=2)


async def test_non_retryable_errors_are_not_retried():
    """A malformed request must fail immediately; retrying it just wastes the budget."""
    from app.llm.provider import with_retry

    attempts = {"n": 0}

    async def bad_request():
        attempts["n"] += 1
        raise ValueError("400 INVALID_ARGUMENT: bad model name")

    with pytest.raises(ValueError):
        await with_retry(bad_request, label="test", attempts=5)
    assert attempts["n"] == 1, "a 400 must not be retried"
