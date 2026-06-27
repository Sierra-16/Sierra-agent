from __future__ import annotations

import re
from typing import Any


CONTEXT_OVERFLOW = "context_overflow"
PAYLOAD_TOO_LARGE = "payload_too_large"
OUTPUT_LIMIT = "output_limit"
OTHER = "other"


_CONTEXT_PATTERNS = (
    "context length",
    "context window",
    "maximum context",
    "max context",
    "too many tokens",
    "prompt is too long",
    "input is too long",
    "input length",
    "tokens exceed",
    "exceeds the context",
    "exceed context",
)

_OUTPUT_PATTERNS = (
    "max_tokens",
    "max output",
    "output tokens",
    "completion tokens",
    "available tokens",
    "requested output",
)


def classify_llm_error(error: Exception) -> str:
    status = getattr(error, "status_code", None)
    text = _error_text(error)
    lowered = text.lower()
    if status == 413 or "payload too large" in lowered or "request entity too large" in lowered:
        return PAYLOAD_TOO_LARGE
    has_context_hint = any(pattern in lowered for pattern in _CONTEXT_PATTERNS)
    has_output_hint = any(pattern in lowered for pattern in _OUTPUT_PATTERNS)
    if has_output_hint and (
        "max_tokens" in lowered
        or "available" in lowered
        or "requested output" in lowered
    ) and (
        "too large" in lowered
        or "exceed" in lowered
        or "available" in lowered
        or "maximum" in lowered
    ):
        return OUTPUT_LIMIT
    if has_context_hint:
        return CONTEXT_OVERFLOW
    if has_output_hint and (
        "too large" in lowered
        or "exceed" in lowered
        or "available" in lowered
        or "maximum" in lowered
    ):
        return OUTPUT_LIMIT
    return OTHER


def extract_context_window(error: Exception) -> int | None:
    text = _error_text(error)
    candidates = []
    for pattern in (
        r"(?:context|window|limit|maximum|max)[^\d]{0,40}([\d,]{4,})",
        r"([\d,]{4,})[^\n]{0,40}(?:tokens|token)[^\n]{0,40}(?:context|window|limit|max)",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _parse_int(match.group(1))
            if value and value >= 4096:
                candidates.append(value)
    return min(candidates) if candidates else None


def extract_available_output_tokens(error: Exception) -> int | None:
    text = _error_text(error)
    for pattern in (
        r"available(?:_|\s|-)?tokens?[^\d]{0,20}([\d,]{1,8})",
        r"available[^\d]{0,20}([\d,]{1,8})[^\n]{0,20}tokens?",
        r"can(?:not|'t)?\s+generate[^\d]{0,40}([\d,]{1,8})",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _parse_int(match.group(1))
            if value and value > 0:
                return value
    return None


def _parse_int(value: str) -> int | None:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _error_text(error: Exception) -> str:
    parts = [str(error)]
    response = getattr(error, "response", None)
    if response is not None:
        try:
            parts.append(str(response.text))
        except Exception:
            pass
        try:
            payload: Any = response.json()
            parts.append(str(payload))
        except Exception:
            pass
    return "\n".join(part for part in parts if part)
