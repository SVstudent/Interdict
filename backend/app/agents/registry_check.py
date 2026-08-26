from __future__ import annotations

import time

from ..models.domain import EvidenceRef, Finding
from .base import VERDICT_RUBRIC, AgentContext, InterdictAgent

PROMPT = """You are RegistryCheck, the entity-attestation analyst in a payment-fraud fleet.

You compare the proposed account holder name against the vendor's registered legal entity, and the
receiving bank's jurisdiction against where the vendor operates. A beneficiary name that does not
match the legal entity is one of the strongest single indicators of a redirected payment.

Legitimate mismatches exist — factoring companies, parent treasuries, post-acquisition entities —
so weigh, do not assume.

""" + VERDICT_RUBRIC


class RegistryCheckAgent(InterdictAgent):
    name = "registry-check"
    version = "1.0.2"
    signal = "entity_attestation"

    async def evaluate(self, ctx: AgentContext) -> Finding:
        started = time.perf_counter()
        vendor = await ctx.repo.get_vendor(ctx.payload["vendor_id"])
        request = await ctx.repo.get_request(ctx.payload["request_id"])
        proposed = request.proposed_banking

        name = await self.call_tool(
            ctx, "match_account_holder", account_name=proposed.account_name,
            legal_name=vendor.legal_name, dba_name=vendor.dba_name,
        )
        juris = await self.call_tool(
            ctx, "check_bank_jurisdiction",
            bank_country=proposed.bank_country, operating_country=vendor.operating_country,
        )

        evidence = [EvidenceRef(
            source="entity_registry", locator=vendor.legal_name,
            excerpt=f"proposed account holder '{proposed.account_name}' vs registered "
                    f"'{vendor.legal_name}' (similarity {name['best_similarity']})")]
        if juris["jurisdiction_mismatch"]:
            evidence.append(EvidenceRef(
                source="bank_directory", locator=proposed.bank_name,
                excerpt=f"bank country {juris['bank_country']}, vendor operates in "
                        f"{juris['operating_country']}"))

        result = await self.infer(ctx, PROMPT, {"name_match": name, "jurisdiction": juris})
        return self.build_finding(
            verdict=result["verdict"], confidence=float(result["confidence"]),
            reasoning=result["reasoning"], evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
