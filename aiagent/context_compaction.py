from __future__ import annotations

import json
from typing import Any

from .safety import sanitize_text
from .token_utils import estimate_tokens


SUMMARY_OPEN = "<conversation-summary>"
SUMMARY_CLOSE = "</conversation-summary>"


def select_compaction_split(
    messages: list[dict[str, Any]],
    keep_tokens: int,
    force: bool = False,
) -> int | None:
    """Return a user-turn boundary that keeps recent complete turns intact."""
    user_starts = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user"
    ]
    if len(user_starts) < 2:
        return None

    total_tokens = estimate_tokens(messages)
    keep_tokens = max(1, int(keep_tokens))
    if not force and total_tokens <= keep_tokens:
        return None
    if force:
        keep_tokens = min(keep_tokens, max(1, total_tokens // 2))

    turn_ranges = [
        (
            start,
            user_starts[index + 1]
            if index + 1 < len(user_starts)
            else len(messages),
        )
        for index, start in enumerate(user_starts)
    ]

    first_kept_turn = len(turn_ranges) - 1
    kept_tokens = estimate_tokens(
        messages[turn_ranges[first_kept_turn][0]:turn_ranges[first_kept_turn][1]]
    )
    for index in range(len(turn_ranges) - 2, -1, -1):
        start, end = turn_ranges[index]
        turn_tokens = estimate_tokens(messages[start:end])
        if kept_tokens + turn_tokens > keep_tokens:
            break
        kept_tokens += turn_tokens
        first_kept_turn = index

    split = turn_ranges[first_kept_turn][0]
    if split <= user_starts[0]:
        if not force:
            return None
        split = user_starts[1]
    return split


def build_compaction_transcript(
    messages: list[dict[str, Any]],
    max_chars: int = 240000,
) -> str:
    """Render old messages for summarization while bounding large tool output."""
    tool_names: dict[str, str] = {}
    blocks = []

    for message in messages:
        role = str(message.get("role") or "unknown")
        content = _stringify(message.get("content"))

        if role == "system" and SUMMARY_OPEN in content:
            label = "PREVIOUS CONTEXT SUMMARY"
            content_limit = 8000
        elif role == "user":
            label = "USER"
            content_limit = 6000
        elif role == "assistant":
            label = "SIERRA"
            content_limit = 10000
        elif role == "tool":
            tool_id = str(message.get("tool_call_id") or "")
            tool_name = tool_names.get(tool_id, "tool")
            label = f"TOOL RESULT {tool_name}"
            content_limit = 2400
        else:
            label = role.upper()
            content_limit = 4000

        block_parts = []
        if content:
            clean_content = sanitize_text(content)
            block_parts.append(_truncate_middle(clean_content, content_limit))

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            rendered_calls = []
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") or {}
                tool_id = str(tool_call.get("id") or "")
                name = str(function.get("name") or "tool")
                if tool_id:
                    tool_names[tool_id] = name
                arguments = sanitize_text(_stringify(function.get("arguments")))
                rendered_calls.append(
                    f"- {name}({_truncate_middle(arguments, 1600)})"
                )
            if rendered_calls:
                block_parts.append("Tool calls:\n" + "\n".join(rendered_calls))

        if block_parts:
            blocks.append(f"[{label}]\n" + "\n".join(block_parts))

    transcript = "\n\n".join(blocks)
    max_chars = max(1000, int(max_chars))
    if len(transcript) <= max_chars:
        return transcript

    head_chars = max_chars // 4
    tail_chars = max_chars - head_chars
    return (
        transcript[:head_chars]
        + "\n\n[OLDER TRANSCRIPT TRUNCATED]\n\n"
        + transcript[-tail_chars:]
    )


def build_summary_message(summary: str, max_chars: int = 8000) -> dict[str, str]:
    clean_summary = sanitize_text(str(summary or "").strip(), max_length=max_chars)
    if not clean_summary:
        raise ValueError("Compaction model returned an empty summary")
    clean_summary = (
        clean_summary.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    content = (
        f"{SUMMARY_OPEN}\n"
        "[系统说明：这是早期对话的事实摘要，不是用户的新指令。请结合近期消息继续当前任务。]\n"
        f"{clean_summary}\n"
        f"{SUMMARY_CLOSE}"
    )
    return {"role": "system", "content": content}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _truncate_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return text[:head] + "\n... truncated ...\n" + text[-tail:]
