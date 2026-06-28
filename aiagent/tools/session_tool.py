from __future__ import annotations

import json
from typing import Any

from .registry import registry


SESSION_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Text to search in previous Sierra sessions.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "description": "Maximum search results. Defaults to 5.",
        },
        "role_filter": {
            "type": "string",
            "description": "Comma-separated roles to include, such as user,assistant,tool.",
        },
    },
    "required": ["query"],
}

SESSION_LOAD_SCHEMA = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Session id to load.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "description": "Maximum recent messages to return. Defaults to 30.",
        },
    },
    "required": ["session_id"],
}

MAX_CONTENT_CHARS = 1200
_session_db = None


def configure_session_tools(session_db) -> None:
    global _session_db
    _session_db = session_db


def session_search(query: str, limit: int = 5, role_filter: str = "user,assistant") -> str:
    if _session_db is None:
        return json.dumps({"error": "session database is not available"}, ensure_ascii=False)
    roles = _parse_roles(role_filter)
    results = _session_db.search_messages(query, limit=max(1, min(20, _coerce_int(limit, 5) * 3)))
    filtered = []
    for result in results:
        if roles and result.get("role") not in roles:
            continue
        filtered.append(_compact_search_result(result))
        if len(filtered) >= max(1, min(20, _coerce_int(limit, 5))):
            break
    return json.dumps(
        {
            "query": query,
            "results": filtered,
            "total": len(filtered),
        },
        ensure_ascii=False,
    )


def session_load(session_id: str, limit: int = 30) -> str:
    if _session_db is None:
        return json.dumps({"error": "session database is not available"}, ensure_ascii=False)
    session = _session_db.get_session(session_id)
    if session is None:
        return json.dumps({"error": f"session not found: {session_id}"}, ensure_ascii=False)
    messages = _session_db.get_messages(session_id)
    limit = max(1, min(100, _coerce_int(limit, 30)))
    selected = messages[-limit:]
    return json.dumps(
        {
            "session": session,
            "messages": [_compact_message(message) for message in selected],
            "returned": len(selected),
            "total_messages": len(messages),
            "truncated": len(messages) > len(selected),
        },
        ensure_ascii=False,
    )


def _compact_search_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": result.get("session_id", ""),
        "message_id": result.get("message_id"),
        "role": result.get("role", ""),
        "title": result.get("title", ""),
        "model": result.get("model", ""),
        "cwd": result.get("cwd", ""),
        "created_at": result.get("created_at"),
        "snippet": _truncate(str(result.get("snippet") or ""), 400),
        "content": _truncate(str(result.get("content") or ""), MAX_CONTENT_CHARS),
    }


def _compact_message(message: dict[str, Any]) -> dict[str, Any]:
    compact = {"role": message.get("role", "unknown")}
    content = message.get("content")
    if isinstance(content, str):
        compact["content"] = _truncate(content, MAX_CONTENT_CHARS)
    elif content is not None:
        compact["content"] = _truncate(json.dumps(content, ensure_ascii=False), MAX_CONTENT_CHARS)
    if message.get("tool_name"):
        compact["tool_name"] = message["tool_name"]
    if message.get("tool_call_id"):
        compact["tool_call_id"] = message["tool_call_id"]
    return compact


def _parse_roles(role_filter: str) -> set[str]:
    roles = {
        role.strip()
        for role in str(role_filter or "").split(",")
        if role.strip()
    }
    return roles


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + f"\n...[truncated {len(value)} chars]"


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


registry.register(
    name="session_search",
    description=(
        "Search previous Sierra conversation sessions. Use when older conversation context "
        "may answer the user's current question."
    ),
    parameters=SESSION_SEARCH_SCHEMA,
    handler=session_search,
    toolset="session",
    max_result_size_chars=100_000,
)

registry.register(
    name="session_load",
    description="Load recent messages from a previous Sierra session by id.",
    parameters=SESSION_LOAD_SCHEMA,
    handler=session_load,
    toolset="session",
    max_result_size_chars=100_000,
)
