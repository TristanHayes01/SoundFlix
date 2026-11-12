"""Pure, configurable artist-list normalization. Safe to unit test without a GUI."""
from __future__ import annotations
import re
from dataclasses import dataclass, field


@dataclass
class TextCleaner:
    # Parenthesized event programming is deleted before collaboration splitting.
    noise_patterns: list[str] = field(default_factory=lambda: [
        r"\([^)]*(?:\b(?:\d+\s*HOUR|DETOX|DJ|LIVE|SPECIAL\s+GUEST|SET)\b)[^)]*\)",
        r"\b(?:PRESENTS|LIVE|SPECIAL\s+GUEST|DJ\s+SET)\b",
    ])
    # BZB is accepted as a common shorthand for B2B. The expression remains
    # general: it does not contain a list of artist names or special cases.
    collaboration_pattern: str = r"\s+(?:B\s*[2Z]\s*B|FT\.?|FEAT\.?|&)\s+"

    def clean(self, text: str) -> list[str]:
        """Return unique, printable artist candidates while preserving input order."""
        result: list[str] = []
        seen: set[str] = set()
        for original_line in text.splitlines():
            line = original_line.strip()
            # Skip stage counters and damaged date fragments, but retain names such as ZOEY808.
            if re.fullmatch(r"\d+", line) or re.fullmatch(r"[A-Za-z]{1,3}\s+\d+[A-Za-z]?\d*", line):
                continue
            for pattern in self.noise_patterns:
                line = re.sub(pattern, " ", line, flags=re.IGNORECASE)
            # Lists often use pipes, slashes, or middle dots as visual delimiters.
            line = re.sub(r"[|•·]+", "\n", line)
            for visual_line in line.splitlines():
                for candidate in re.split(self.collaboration_pattern, visual_line, flags=re.IGNORECASE):
                    # Keep artist punctuation; remove visual decoration and whitespace.
                    candidate = re.sub(r"[^\w\s&'\-.]", " ", candidate, flags=re.UNICODE)
                    candidate = re.sub(r"\s+", " ", candidate).strip(" .-_\t")
                    # Repeated adjacent entries collapse to one artist name.
                    words = candidate.split()
                    if len(words) % 2 == 0 and words[:len(words) // 2] == words[len(words) // 2:]:
                        candidate = " ".join(words[:len(words) // 2])
                    if not candidate:
                        continue
                    fingerprint = candidate.casefold()
                    if fingerprint not in seen:
                        seen.add(fingerprint)
                        result.append(candidate)
        return result

    def clean_as_text(self, text: str) -> str:
        return "\n".join(self.clean(text))
