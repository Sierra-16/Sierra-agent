import json
import math
import unicodedata


def estimate_tokens(messages, tools=None):
    total = 0
    for message in messages:
        content = message.get("content", "") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        total += estimate_text_tokens(content)
        if "tool_calls" in message:
            total += estimate_text_tokens(
                json.dumps(
                    message["tool_calls"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        # Chat-completion role and message framing overhead.
        total += 4
    if tools:
        total += estimate_text_tokens(
            json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        )
    return max(0, int(math.ceil(total)))


def estimate_text_tokens(value):
    """Provider-neutral estimate for mixed Chinese, English, and JSON text."""
    text = str(value or "")
    ascii_chars = 0
    cjk_chars = 0
    other_chars = 0
    for char in text:
        codepoint = ord(char)
        if codepoint < 128:
            ascii_chars += 1
        elif _is_cjk(char):
            cjk_chars += 1
        else:
            other_chars += 1
    return (ascii_chars / 4.0) + cjk_chars + (other_chars / 2.0)


def _is_cjk(char):
    codepoint = ord(char)
    if (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
    ):
        return True
    return unicodedata.east_asian_width(char) in {"W", "F"}
