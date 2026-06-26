from __future__ import annotations

from typing import Any

from .context_compaction import SUMMARY_OPEN
from .token_utils import estimate_tokens


def prepare_conversation_messages_for_request(
    messages: list[dict[str, Any]],
    *,
    old_tool_result_max_chars: int = 2400,
    recent_tool_result_max_chars: int = 12000,
    recent_message_count: int = 8,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Copy conversation messages and shrink bulky tool results for the request.

    Persisted history stays untouched. Recent tool results get a larger cap so
    the model can still use the output it just asked for, while older tool
    outputs are reduced to compact references.
    """
    old_limit = max(500, int(old_tool_result_max_chars or 2400))
    recent_limit = max(old_limit, int(recent_tool_result_max_chars or 12000))
    recent_start = max(0, len(messages) - max(0, int(recent_message_count or 0)))
    prepared = []
    truncated_tool_results = 0
    omitted_chars = 0

    for index, message in enumerate(messages):
        copied = dict(message)
        if copied.get("role") == "tool":
            limit = recent_limit if index >= recent_start else old_limit
            content = copied.get("content")
            if not isinstance(content, str):
                content = str(content or "")
            if len(content) > limit:
                copied["content"] = _truncate_tool_result(content, limit)
                truncated_tool_results += 1
                omitted_chars += len(content) - len(copied["content"])
        prepared.append(copied)

    return prepared, {
        "truncated_tool_results": truncated_tool_results,
        "omitted_tool_result_chars": max(0, omitted_chars),
    }


def fit_messages_to_budget(
    system_messages: list[dict[str, Any]],
    conversation_messages: list[dict[str, Any]],
    *,
    tools=None,
    max_tokens: int,
) -> tuple[list[dict[str, Any]], int]:
    """Return request messages bounded to the latest complete turns.

    This is a send-side guardrail: it does not mutate persisted conversation
    history. It keeps system context, any compacted summary messages that fit,
    and as many recent user-turn ranges as possible.
    """
    max_tokens = max(1, int(max_tokens or 1))
    full_messages = [*system_messages, *conversation_messages]
    if estimate_tokens(full_messages, tools=tools) <= max_tokens:
        return full_messages, 0

    fixed_tokens = estimate_tokens(system_messages, tools=tools)
    conversation_budget = max(1, max_tokens - fixed_tokens)
    selected_indices: set[int] = set()
    used_tokens = 0

    for index, message in enumerate(conversation_messages):
        if not _is_summary_message(message):
            continue
        message_tokens = estimate_tokens([message])
        if used_tokens + message_tokens > conversation_budget:
            continue
        selected_indices.add(index)
        used_tokens += message_tokens

    ranges = _turn_ranges(conversation_messages)
    selected_turns = 0
    for start, end in reversed(ranges):
        turn_indices = set(range(start, end))
        if turn_indices.issubset(selected_indices):
            continue
        turn_messages = conversation_messages[start:end]
        turn_tokens = estimate_tokens(turn_messages)
        if selected_turns > 0 and used_tokens + turn_tokens > conversation_budget:
            break
        selected_indices.update(turn_indices)
        used_tokens += turn_tokens
        selected_turns += 1

    if not selected_indices and conversation_messages:
        selected_indices.add(len(conversation_messages) - 1)

    bounded_conversation = [
        message
        for index, message in enumerate(conversation_messages)
        if index in selected_indices
    ]
    omitted = max(0, len(conversation_messages) - len(bounded_conversation))
    return [*system_messages, *bounded_conversation], omitted


def _turn_ranges(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
    user_starts = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user"
    ]
    if not user_starts:
        return [(index, index + 1) for index in range(len(messages))]
    return [
        (
            start,
            user_starts[position + 1]
            if position + 1 < len(user_starts)
            else len(messages),
        )
        for position, start in enumerate(user_starts)
    ]


def _is_summary_message(message: dict[str, Any]) -> bool:
    return (
        message.get("role") == "system"
        and SUMMARY_OPEN in str(message.get("content") or "")
    )


def _truncate_tool_result(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    marker = "\n... tool output truncated to save context ...\n"
    if limit <= len(marker) + 200:
        return content[:limit]
    head = max(100, (limit - len(marker)) * 2 // 3)
    tail = max(100, limit - len(marker) - head)
    return content[:head] + marker + content[-tail:]
