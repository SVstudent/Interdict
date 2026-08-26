---
name: add-agent
description: Add a new ADK agent to the Interdict fleet with correct scope enforcement, span attributes, registry entry, and tests. Use when adding or substantially changing any agent in backend/app/agents/.
---

# Adding an ADK agent

## Checklist
1. Module at `backend/app/agents/<name>.py`, subclassing `InterdictAgent` from `agents/base.py`.
2. Prompt in `backend/app/agents/prompts/<name>.md` — never inline a multi-line prompt in Python.
3. Declare the tool registry as a module-level constant. Tools are real ADK `FunctionTool`s.
4. Declare granted/denied scopes; the base class raises `AgentScopeError` on any out-of-scope call.
5. Model: `settings.FLASH_MODEL` unless this is Challenger or Adjudicator (`settings.PRO_MODEL`).
6. Register in `platform/registry.py` with a semantic version and a changelog line.
7. Emit a span with the full attribute set from `context/PLATFORM.md`.
8. Tests: scope violation raises; span attributes complete; finding validates; local/GEAP parity.

## Worked example

```python
# backend/app/agents/registry_check.py
from decimal import Decimal
from google.adk.tools import FunctionTool
from .base import InterdictAgent, tool_scope
from ..models import Case, Finding, EvidenceRef, Vendor
from ..config import Settings

AGENT_NAME = "registry-check"
AGENT_VERSION = "1.0.2"

GRANTED_SCOPES = frozenset({"entity:lookup", "vendor:banking:read"})
DENIED_SCOPES  = frozenset({"payments:release", "payments:block", "erp:vendor:write"})


@tool_scope("entity:lookup")
def lookup_entity(legal_name: str, country: str) -> dict:
    """Look up a legal entity in the synthetic corporate registry."""
    ...


class RegistryCheckAgent(InterdictAgent):
    def __init__(self, settings: Settings, clock, platform):
        super().__init__(
            name=AGENT_NAME,
            version=AGENT_VERSION,
            model=settings.FLASH_MODEL,
            prompt_path="prompts/registry_check.md",
            tools=[FunctionTool(lookup_entity)],
            granted_scopes=GRANTED_SCOPES,
            denied_scopes=DENIED_SCOPES,
            clock=clock,
            platform=platform,
        )

    async def evaluate(self, case: Case, vendor: Vendor) -> Finding:
        with self.span(case, step="entity_attestation") as span:
            result = await self.run(case, {"vendor": vendor.model_dump()})
            finding = Finding(
                finding_id=self.new_finding_id(case),
                agent=AGENT_NAME,
                agent_version=AGENT_VERSION,
                signal="account_holder_name_mismatch",
                verdict=result.verdict,
                confidence=result.confidence,
                evidence=[EvidenceRef(**e) for e in result.evidence],
                reasoning=result.reasoning,
                latency_ms=span.elapsed_ms(),
            )
            span.record_finding(finding)
            return finding
```

## Rules
- **Never** call GEAP directly. Go through `self.platform.*` protocols.
- **Never** call `datetime.now()`. Use `self.clock.now()`. A grep test enforces this.
- A non-inconclusive `Finding` with empty `evidence` will raise at construction. That is intended —
  fix the prompt so the model cites, do not weaken the validator.
- The `evidence[].excerpt` is the **literal observed value**, not a paraphrase.
