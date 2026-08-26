from __future__ import annotations

import time

from ..models.domain import EvidenceRef, Finding
from .base import VERDICT_RUBRIC, AgentContext, InterdictAgent

PROMPT = """You are Callback, the out-of-band verification agent.

You dial ONLY the vendor contact number held in the system of record. If the request supplied its
own phone number, that fact is a signal you must report — and that number is never dialled.

An unanswered callback is "inconclusive". It is never "supports". Silence is not confirmation.

An unanswered callback is "inconclusive" — never "supports".
""" + VERDICT_RUBRIC


class CallbackAgent(InterdictAgent):
    name = "callback"
    version = "1.2.1"
    signal = "out_of_band_confirmation"

    async def evaluate(self, ctx: AgentContext) -> Finding:
        started = time.perf_counter()
        vendor = await ctx.repo.get_vendor(ctx.payload["vendor_id"])
        request = await ctx.repo.get_request(ctx.payload["request_id"])

        contact = await self.call_tool(
            ctx, "contact_of_record", vendor=vendor,
            supplied_phone=request.artifact_metadata.get("supplied_phone"),
        )
        # Supplied by the demo control plane or the scheduler when a vendor calls back.
        response = ctx.payload.get("callback_response")

        evidence = [EvidenceRef(
            source="vendor_master", locator="contact_phone_of_record",
            excerpt=contact["dialing"])]
        if contact["request_supplied_its_own_number"]:
            evidence.append(EvidenceRef(
                source="inbound_artifact", locator="supplied phone number",
                excerpt=f"{contact['request_supplied_phone']} — supplied by the request, not dialled"))
        if response:
            evidence.append(EvidenceRef(
                source="callback_log", locator=contact["dialing"],
                excerpt=f"vendor {response} the change on the number of record"))

        result = await self.infer(
            ctx, PROMPT, {"contact": contact, "callback_response": response or "no answer"}
        )
        verdict = result["verdict"]
        # Hard rail: no model output may turn an unanswered callback into confirmation.
        if not response and verdict == "supports":
            verdict = "inconclusive"

        return self.build_finding(
            verdict=verdict, confidence=float(result["confidence"]) if response else 0.0,
            reasoning=result["reasoning"], evidence=evidence if verdict != "inconclusive" else [],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
