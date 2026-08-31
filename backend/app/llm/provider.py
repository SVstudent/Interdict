"""Model access.

Two providers behind one Protocol:

  gemini       Direct Gemini API (google-genai). This is the COMPLIANT path and the one the
               recorded demo must run on — the competition rules mandate "Gemini 3.5 or newer
               accessed through Gemini API or Vertex AI".

  tokenrouter  OpenAI-compatible aggregator. Useful for development iteration because it does
               not burn free-tier quota or GCP credits, but it is NOT Gemini API or Vertex AI.
               Using it for the submission risks a Stage One pass/fail failure.

The split exists so prompt-tuning and scenario debugging can run cheaply while the artifact that
gets judged runs on the sanctioned path. `make rehearse` and the recording assert the provider.
"""
from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

# Vertex throttles on requests-per-minute, and the verification fan-out is bursty by design:
# four lanes fire at once, then challenger, adjudicator, scribe and attribution follow. Running
# two cases inside a minute produced a hard 429 RESOURCE_EXHAUSTED, which mid-recording would be
# fatal. Retry with full jitter so a burst spreads instead of retrying in lockstep.
RETRY_ON = ("RESOURCE_EXHAUSTED", "429", "UNAVAILABLE", "503", "500", "INTERNAL", "DEADLINE")
MAX_ATTEMPTS = 5
BASE_DELAY = 1.5


class Throttled(RuntimeError):
    """Raised when a call still fails after the retry budget is exhausted."""


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return any(token in text for token in RETRY_ON)


async def with_retry(
    call: Callable[[], Awaitable[Any]], *, label: str = "", attempts: int = MAX_ATTEMPTS
) -> Any:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001
            if not _is_retryable(exc) or attempt == attempts:
                if _is_retryable(exc):
                    raise Throttled(
                        f"{label or 'model call'} still throttled after {attempts} attempts. "
                        f"Raise the Vertex requests-per-minute quota for this project, or stagger "
                        f"the fan-out. Last error: {exc}"
                    ) from exc
                raise
            last = exc
            # Full jitter: sleep uniformly in [0, base * 2^n]. Lockstep retries would just
            # recreate the same burst that caused the throttle.
            ceiling = BASE_DELAY * (2 ** (attempt - 1))
            await asyncio.sleep(random.uniform(0, ceiling))
    raise Throttled(str(last))


class Provider(str, Enum):
    VERTEX = "vertex"          # Vertex AI via ADC — sanctioned, and same auth path as GEAP
    GEMINI = "gemini"          # Gemini Developer API via API key — sanctioned
    TOKENROUTER = "tokenrouter"  # third-party aggregator — development only


# The rules mandate "Gemini 3.5 or newer accessed through Gemini API or Vertex AI".
SANCTIONED = frozenset({Provider.VERTEX, Provider.GEMINI})


class ProviderNotCompliant(RuntimeError):
    """Raised when a non-sanctioned provider is used somewhere the rules forbid it."""


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    provider: Provider
    input_tokens: int = 0
    output_tokens: int = 0

    def json(self) -> dict[str, Any]:
        """Parse the model's reply as JSON.

        Models occasionally wrap JSON in a markdown fence despite being asked not to; strip it
        rather than failing the whole case on a formatting tic.
        """
        raw = self.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw.strip("`")
            if raw.lstrip().lower().startswith("json"):
                raw = raw.lstrip()[4:]
        return json.loads(raw.strip())


class LLMProvider(Protocol):
    name: Provider

    async def complete(
        self, *, model: str, system: str, user: str, json_mode: bool = True
    ) -> Completion: ...


class VertexProvider:
    """Gemini on Vertex AI, authenticated by Application Default Credentials.

    Preferred over the Developer API for this project: `aiplatform.googleapis.com` is already
    enabled, GEAP's Agent Runtime lives on the same API, and ADC then covers BOTH model calls and
    the platform bindings — one credential path instead of an API key plus ADC. Quota is project
    quota rather than a per-key free tier, so a concurrent fan-out will not throttle mid-beat.
    """

    name = Provider.VERTEX

    def __init__(self, project_id: str, location: str) -> None:
        if not project_id:
            raise RuntimeError(
                "GCP_PROJECT_ID is required for LLM_PROVIDER=vertex. "
                "Authenticate with `gcloud auth application-default login`."
            )
        self._project_id = project_id
        self._location = location
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=True, project=self._project_id, location=self._location
            )
        return self._client

    async def complete(
        self, *, model: str, system: str, user: str, json_mode: bool = True
    ) -> Completion:
        config: dict[str, Any] = {
            "system_instruction": system,
            # No tools are passed here — our own registry invokes tools — so silence the SDK's
            # automatic-function-calling advisory instead of logging it on every agent step.
            "automatic_function_calling": {"disable": True},
        }
        if json_mode:
            config["response_mime_type"] = "application/json"

        response = await with_retry(
            lambda: self._get_client().aio.models.generate_content(
                model=model, contents=user, config=config
            ),
            label=f"vertex:{model}",
        )
        usage = getattr(response, "usage_metadata", None)
        return Completion(
            text=response.text or "",
            model=model,
            provider=Provider.VERTEX,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )


class GeminiProvider:
    """Gemini Developer API via API key. Sanctioned; simpler, but a separate credential."""

    name = Provider.GEMINI

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required for LLM_PROVIDER=gemini. "
                "Mint one at https://aistudio.google.com/apikey (free tier available)."
            )
        self._api_key = api_key
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def complete(
        self, *, model: str, system: str, user: str, json_mode: bool = True
    ) -> Completion:
        config: dict[str, Any] = {
            "system_instruction": system,
            "automatic_function_calling": {"disable": True},
        }
        if json_mode:
            config["response_mime_type"] = "application/json"

        response = await with_retry(
            lambda: self._get_client().aio.models.generate_content(
                model=model, contents=user, config=config
            ),
            label=f"gemini:{model}",
        )
        usage = getattr(response, "usage_metadata", None)
        return Completion(
            text=response.text or "",
            model=model,
            provider=Provider.GEMINI,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )


class TokenRouterProvider:
    """OpenAI-compatible aggregator. Development only — see the module docstring."""

    name = Provider.TOKENROUTER

    def __init__(self, api_key: str, base_url: str, model_prefix: str) -> None:
        if not api_key:
            raise RuntimeError("TOKENROUTER_API_KEY is required for LLM_PROVIDER=tokenrouter.")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._prefix = model_prefix

    def _qualify(self, model: str) -> str:
        """TokenRouter namespaces models as `provider/model`."""
        return model if "/" in model else f"{self._prefix}{model}"

    async def complete(
        self, *, model: str, system: str, user: str, json_mode: bool = True
    ) -> Completion:
        import httpx

        body: dict[str, Any] = {
            "model": self._qualify(model),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            payload = response.json()

        choice = (payload.get("choices") or [{}])[0]
        usage = payload.get("usage") or {}
        return Completion(
            text=(choice.get("message") or {}).get("content") or "",
            model=payload.get("model", model),
            provider=Provider.TOKENROUTER,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


def build_provider(settings) -> LLMProvider:
    if settings.LLM_PROVIDER is Provider.VERTEX:
        return VertexProvider(settings.GCP_PROJECT_ID, settings.VERTEX_LOCATION)
    if settings.LLM_PROVIDER is Provider.TOKENROUTER:
        return TokenRouterProvider(
            settings.TOKENROUTER_API_KEY,
            settings.TOKENROUTER_BASE_URL,
            settings.TOKENROUTER_MODEL_PREFIX,
        )
    return GeminiProvider(settings.GEMINI_API_KEY)


def assert_compliant(provider: LLMProvider) -> None:
    """Guard for the recording and for `make rehearse --record`.

    The rules require Gemini API or Vertex AI. Anything else is a submission-level defect, so
    fail loudly here rather than discovering it after the video is cut.
    """
    if provider.name not in SANCTIONED:
        raise ProviderNotCompliant(
            f"LLM_PROVIDER={provider.name.value} is not permitted for artifacts that get judged. "
            "The rules mandate Gemini 3.5+ accessed through Gemini API or Vertex AI. "
            "Set LLM_PROVIDER=vertex (or gemini) before recording or populating the replay cache."
        )
