"""Inbound artifact screening.

Every artifact is screened before any agent sees it. What gets removed is recorded verbatim,
with its offset and the technique that produced it, because Posture renders that literal text
struck through and it is one of the highest-value frames in the demo (beat 3).

The inherited version used `re.findall`, which returns the *capture group* rather than the whole
match on any pattern containing one — so it logged "previous" instead of the injected sentence.
Everything here uses `finditer` + `group(0)`. See DECISIONS D-001.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Technique(str, Enum):
    INSTRUCTION_OVERRIDE = "instruction_override"
    AUTHORITY_SPOOF = "authority_spoof"
    URGENCY_COERCION = "urgency_coercion"
    HIDDEN_TEXT = "hidden_text"
    ZERO_WIDTH = "zero_width"
    HOMOGLYPH = "homoglyph"
    METADATA_INSTRUCTION = "metadata_instruction"


# Ordered most-specific first so a phrase is attributed to the sharpest technique that matches.
PATTERNS: list[tuple[Technique, re.Pattern[str]]] = [
    (Technique.INSTRUCTION_OVERRIDE, re.compile(
        r"ignore\s+(?:all\s+)?(?:prior|previous|above|preceding)\s+instructions?[^.\n]*", re.I)),
    (Technique.INSTRUCTION_OVERRIDE, re.compile(
        r"disregard\s+(?:all\s+)?(?:prior|previous|earlier)\s+[^.\n]*", re.I)),
    (Technique.AUTHORITY_SPOOF, re.compile(
        r"(?:\[)?system(?:\s+prompt)?(?:\])?\s*:\s*you\s+(?:must|should|will)\s+[^.\n]*", re.I)),
    (Technique.AUTHORITY_SPOOF, re.compile(
        r"this\s+(?:vendor|payee|request)\s+(?:is|has\s+been)\s+pre-?(?:approved|verified|cleared)[^.\n]*", re.I)),
    (Technique.AUTHORITY_SPOOF, re.compile(
        r"(?:verification|callback|review)\s+(?:is\s+)?(?:not\s+required|already\s+completed|waived)[^.\n]*", re.I)),
    (Technique.URGENCY_COERCION, re.compile(
        r"release\s+(?:the\s+)?(?:payment|funds|immediately|without\s+delay)[^.\n]*", re.I)),
    (Technique.URGENCY_COERCION, re.compile(
        r"override\s+(?:the\s+)?(?:safety|security|fraud)\s+checks?[^.\n]*", re.I)),
]

ZERO_WIDTH_CHARS = {
    "​": "ZERO WIDTH SPACE",
    "‌": "ZERO WIDTH NON-JOINER",
    "‍": "ZERO WIDTH JOINER",
    "⁠": "WORD JOINER",
    "﻿": "ZERO WIDTH NO-BREAK SPACE",
    "­": "SOFT HYPHEN",
}

# Cyrillic and Greek characters that render identically to Latin in most typefaces.
HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "х": "x", "у": "y", "і": "i", "ј": "j", "һ": "h",
    "ο": "o", "α": "a", "ρ": "p", "ԁ": "d",
}

# Text made invisible in the rendered artifact but still present to a parser.
HIDDEN_TEXT_PATTERNS = [
    re.compile(r"<[^>]*style\s*=\s*[\"'][^\"']*(?:color\s*:\s*#?(?:fff(?:fff)?|white)|"
               r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0)[^\"']*[\"'][^>]*>(.*?)</[^>]+>",
               re.I | re.S),
    re.compile(r"%%\s*PDF-HIDDEN\s*:(.*?)(?:%%|$)", re.I | re.S),
]

METADATA_KEYS_TO_SCREEN = ("subject", "x-note", "producer", "title", "keywords", "comments")


@dataclass
class Neutralization:
    """One removed thing, with enough detail for Posture to render it honestly."""

    technique: Technique
    excerpt: str          # the literal text that was removed, verbatim
    location: str         # "body", "metadata:producer", ...
    offset: int = -1
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "technique": self.technique.value,
            "excerpt": self.excerpt,
            "location": self.location,
            "offset": self.offset,
            "detail": self.detail,
        }


@dataclass
class ScreeningResult:
    original: str
    sanitized: str
    neutralizations: list[Neutralization] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.neutralizations

    @property
    def techniques(self) -> list[str]:
        # Stable order, de-duplicated, for display and for the audit record.
        seen: list[str] = []
        for n in self.neutralizations:
            if n.technique.value not in seen:
                seen.append(n.technique.value)
        return seen

    def as_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "techniques": self.techniques,
            "neutralizations": [n.as_dict() for n in self.neutralizations],
            "removed_count": len(self.neutralizations),
        }


REDACTION = "[NEUTRALIZED]"


class InjectionGuardrail:
    """Screens an artifact and returns the sanitized text plus what was taken out.

    Nothing is silently dropped: every removal is reported so the operator can see what the
    attacker tried, and so the case proceeds on genuine evidence rather than on the attack.
    """

    def screen(self, artifact: str, metadata: dict[str, Any] | None = None) -> ScreeningResult:
        result = ScreeningResult(original=artifact, sanitized=artifact, metadata=metadata or {})

        self._strip_hidden_markup(result)
        self._strip_instruction_patterns(result)
        self._strip_zero_width(result)
        self._flag_homoglyphs(result)
        self._screen_metadata(result)

        return result

    # --- individual screens ---------------------------------------------------------

    def _strip_hidden_markup(self, result: ScreeningResult) -> None:
        for pattern in HIDDEN_TEXT_PATTERNS:
            while True:
                match = pattern.search(result.sanitized)
                if match is None:
                    break
                inner = (match.group(1) or "").strip()
                result.neutralizations.append(
                    Neutralization(
                        technique=Technique.HIDDEN_TEXT,
                        excerpt=inner or match.group(0).strip(),
                        location="body",
                        offset=match.start(),
                        detail="text present in the artifact but invisible when rendered",
                    )
                )
                result.sanitized = (
                    result.sanitized[: match.start()] + REDACTION + result.sanitized[match.end():]
                )

    def _strip_instruction_patterns(self, result: ScreeningResult) -> None:
        for technique, pattern in PATTERNS:
            while True:
                match = pattern.search(result.sanitized)
                if match is None:
                    break
                # group(0) — the whole matched phrase, not a capture group.
                result.neutralizations.append(
                    Neutralization(
                        technique=technique,
                        excerpt=match.group(0).strip(),
                        location="body",
                        offset=match.start(),
                        detail="instruction addressed to the model rather than to a person",
                    )
                )
                result.sanitized = (
                    result.sanitized[: match.start()] + REDACTION + result.sanitized[match.end():]
                )

    def _strip_zero_width(self, result: ScreeningResult) -> None:
        found: dict[str, int] = {}
        for ch in result.sanitized:
            if ch in ZERO_WIDTH_CHARS:
                found[ch] = found.get(ch, 0) + 1
        if not found:
            return
        for ch, count in found.items():
            result.neutralizations.append(
                Neutralization(
                    technique=Technique.ZERO_WIDTH,
                    excerpt=repr(ch).strip("'"),
                    location="body",
                    detail=f"{count}x {ZERO_WIDTH_CHARS[ch]} (U+{ord(ch):04X}) removed",
                )
            )
        for ch in found:
            result.sanitized = result.sanitized.replace(ch, "")

    def _flag_homoglyphs(self, result: ScreeningResult) -> None:
        """Homoglyphs are reported but NOT rewritten.

        Silently 'correcting' a lookalike domain would destroy the very evidence Provenance
        needs to cite. The agent must see the artifact as it actually arrived.
        """
        hits: dict[str, str] = {}
        for ch in result.sanitized:
            if ch in HOMOGLYPHS:
                hits[ch] = HOMOGLYPHS[ch]
        for ch, latin in hits.items():
            try:
                name = unicodedata.name(ch)
            except ValueError:  # pragma: no cover - defensive
                name = "UNNAMED"
            result.neutralizations.append(
                Neutralization(
                    technique=Technique.HOMOGLYPH,
                    excerpt=ch,
                    location="body",
                    detail=f"{name} (U+{ord(ch):04X}) renders as Latin '{latin}' — flagged, not rewritten",
                )
            )

    def _screen_metadata(self, result: ScreeningResult) -> None:
        for key in METADATA_KEYS_TO_SCREEN:
            value = result.metadata.get(key)
            if not isinstance(value, str):
                continue
            for technique, pattern in PATTERNS:
                for match in pattern.finditer(value):
                    result.neutralizations.append(
                        Neutralization(
                            technique=Technique.METADATA_INSTRUCTION,
                            excerpt=match.group(0).strip(),
                            location=f"metadata:{key}",
                            offset=match.start(),
                            detail=f"instruction-shaped string in {key} metadata "
                                   f"(original technique: {technique.value})",
                        )
                    )


guardrail = InjectionGuardrail()
