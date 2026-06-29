from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


TOOL_SEARCH_NAME = "tool_search"
TOOL_DESCRIBE_NAME = "tool_describe"
TOOL_CALL_NAME = "tool_call"
BRIDGE_TOOL_NAMES = {TOOL_SEARCH_NAME, TOOL_DESCRIBE_NAME, TOOL_CALL_NAME}


CORE_TOOLSETS = {
    "browser",
    "code_execution",
    "core",
    "file",
    "git",
    "memory",
    "project",
    "session",
    "skills",
    "terminal",
    "web",
}


@dataclass
class ToolSearchConfig:
    enabled: str = "auto"
    threshold_pct: float = 10.0
    search_default_limit: int = 5
    max_search_limit: int = 20
    context_window: int = 128_000

    @classmethod
    def from_raw(cls, raw: Any, *, context_window: int = 128_000) -> "ToolSearchConfig":
        if raw is True:
            return cls(enabled="auto", context_window=context_window)
        if raw is False:
            return cls(enabled="off", context_window=context_window)
        if not isinstance(raw, dict):
            return cls(enabled="auto", context_window=context_window)
        enabled = str(raw.get("enabled", "auto")).strip().lower()
        if enabled not in {"auto", "on", "off", "true", "false"}:
            enabled = "auto"
        if enabled == "true":
            enabled = "auto"
        if enabled == "false":
            enabled = "off"
        return cls(
            enabled=enabled,
            threshold_pct=_clamp_float(raw.get("threshold_pct", 10), 0, 100, 10),
            search_default_limit=_clamp_int(raw.get("search_default_limit", 5), 1, 20, 5),
            max_search_limit=_clamp_int(raw.get("max_search_limit", 20), 1, 50, 20),
            context_window=max(1, _clamp_int(context_window, 1, 10_000_000, 128_000)),
        )


class ToolEntry:
    __slots__ = (
        "name",
        "description",
        "parameters",
        "handler",
        "toolset",
        "emoji",
        "max_result_size_chars",
    )

    def __init__(
        self,
        name,
        description,
        parameters,
        handler,
        toolset="core",
        emoji="",
        max_result_size_chars=None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.toolset = toolset
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}
        self._tool_search_config = ToolSearchConfig()
        self._last_deferred_names: set[str] = set()
        self._last_tool_search_active = False

    def configure_tool_search(self, config: Any = None, *, context_window: int | None = None) -> None:
        raw = None
        if isinstance(config, dict):
            raw = config.get("tool_search", config)
        else:
            raw = config
        self._tool_search_config = ToolSearchConfig.from_raw(
            raw,
            context_window=context_window or self._tool_search_config.context_window,
        )

    def register(
        self,
        name,
        description,
        parameters,
        handler,
        toolset="core",
        emoji="",
        max_result_size_chars=None,
    ):
        self._tools[name] = ToolEntry(
            name,
            description,
            parameters,
            handler,
            toolset=toolset,
            emoji=emoji,
            max_result_size_chars=max_result_size_chars,
        )

    def unregister(self, name):
        self._tools.pop(name, None)
        self._last_deferred_names.discard(name)

    def unregister_prefix(self, prefix):
        for name in list(self._tools):
            if name.startswith(prefix):
                self.unregister(name)

    def names(self):
        return list(self._tools)

    def get_entry(self, name):
        return self._tools.get(name)

    def get_max_result_size(self, name, default=None):
        real_name, _, _ = self.resolve_invocation(name, {})
        entry = self.get_entry(real_name)
        if entry is not None and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        return default

    def get_definitions(self, skip_tool_search_assembly: bool = False):
        entries = list(self._tools.values())
        if skip_tool_search_assembly:
            return [tool.definition() for tool in entries]

        direct_entries, deferred_entries = self._partition_entries(entries)
        active = self._should_activate_tool_search(deferred_entries)
        self._last_tool_search_active = active
        self._last_deferred_names = {entry.name for entry in deferred_entries} if active else set()
        if not active:
            return [tool.definition() for tool in entries]

        return [
            *[tool.definition() for tool in direct_entries],
            self._tool_search_definition(len(deferred_entries)),
            self._tool_describe_definition(),
            self._tool_call_definition(),
        ]

    def execute(self, name, arguments):
        if name == TOOL_SEARCH_NAME:
            return self._execute_tool_search(arguments or {})
        if name == TOOL_DESCRIBE_NAME:
            return self._execute_tool_describe(arguments or {})
        if name == TOOL_CALL_NAME:
            real_name, real_arguments, error = self.resolve_invocation(name, arguments or {})
            if error:
                return json.dumps({"error": error}, ensure_ascii=False)
            return self.execute(real_name, real_arguments)

        if name not in self._tools:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
        try:
            return self._tools[name].handler(**(arguments or {}))
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    def resolve_invocation(self, name: str, arguments: dict[str, Any] | None):
        if name != TOOL_CALL_NAME:
            return name, arguments or {}, ""
        if not isinstance(arguments, dict):
            return name, {}, "tool_call arguments must be an object"

        requested = str(arguments.get("name") or "").strip()
        if not requested:
            return name, {}, "tool_call requires a target tool name"
        if requested not in self._tools:
            return requested, {}, f"Unknown deferred tool: {requested}"
        if not self._is_tool_search_active_for(requested):
            return requested, {}, f"Tool is not in the deferred catalog: {requested}"

        raw_args = arguments.get("arguments") or {}
        if not isinstance(raw_args, dict):
            return requested, {}, "tool_call.arguments must be an object"
        return requested, raw_args, ""

    def unwrap_invocation(self, name: str, arguments: dict[str, Any] | None):
        return self.resolve_invocation(name, arguments)

    def _partition_entries(self, entries: list[ToolEntry]) -> tuple[list[ToolEntry], list[ToolEntry]]:
        direct = []
        deferred = []
        for entry in entries:
            if entry.name in BRIDGE_TOOL_NAMES:
                continue
            if self._is_deferrable(entry):
                deferred.append(entry)
            else:
                direct.append(entry)
        return direct, deferred

    def _is_deferrable(self, entry: ToolEntry) -> bool:
        if entry.name.startswith("mcp__"):
            return True
        toolset = str(entry.toolset or "core").lower()
        if toolset.startswith("mcp"):
            return True
        return toolset not in CORE_TOOLSETS

    def _should_activate_tool_search(self, deferred_entries: list[ToolEntry]) -> bool:
        config = self._tool_search_config
        if config.enabled == "off" or not deferred_entries:
            return False
        if config.enabled == "on":
            return True
        schema_chars = len(json.dumps([entry.definition() for entry in deferred_entries], ensure_ascii=False))
        schema_token_estimate = max(1, int(schema_chars * 0.35))
        threshold_tokens = int(config.context_window * (config.threshold_pct / 100.0))
        return schema_token_estimate >= max(1, threshold_tokens)

    def _current_deferred_entries(self) -> list[ToolEntry]:
        _, deferred_entries = self._partition_entries(list(self._tools.values()))
        return deferred_entries

    def _is_tool_search_active_for(self, name: str) -> bool:
        if name in self._last_deferred_names:
            return True
        config = self._tool_search_config
        if config.enabled == "off":
            return False
        entry = self._tools.get(name)
        if entry is None or not self._is_deferrable(entry):
            return False
        if config.enabled == "on":
            return True
        return self._should_activate_tool_search(self._current_deferred_entries())

    def _execute_tool_search(self, arguments: dict[str, Any]) -> str:
        query = str(arguments.get("query") or "").strip()
        limit = _clamp_int(
            arguments.get("limit", self._tool_search_config.search_default_limit),
            1,
            self._tool_search_config.max_search_limit,
            self._tool_search_config.search_default_limit,
        )
        deferred = self._current_deferred_entries()
        matches = _rank_tool_matches(query, deferred)[:limit]
        return json.dumps(
            {
                "query": query,
                "count": len(matches),
                "deferred_tools": len(deferred),
                "matches": [
                    {
                        "name": entry.name,
                        "toolset": entry.toolset,
                        "description": _truncate(entry.description, 320),
                        "parameter_names": sorted((entry.parameters.get("properties") or {}).keys()),
                        "score": round(score, 4),
                    }
                    for entry, score in matches
                ],
            },
            ensure_ascii=False,
        )

    def _execute_tool_describe(self, arguments: dict[str, Any]) -> str:
        name = str(arguments.get("name") or "").strip()
        entry = self._tools.get(name)
        if entry is None:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
        if not self._is_tool_search_active_for(name):
            return json.dumps({"error": f"Tool is not deferred: {name}"}, ensure_ascii=False)
        return json.dumps(
            {
                "name": entry.name,
                "toolset": entry.toolset,
                "description": entry.description,
                "parameters": entry.parameters,
            },
            ensure_ascii=False,
        )

    def _tool_search_definition(self, deferred_count: int) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": TOOL_SEARCH_NAME,
                "description": (
                    f"Search {deferred_count} deferred MCP/plugin tools by capability. "
                    "Use this when a needed external tool is not directly visible."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Capability or action to search for, such as 'create github issue'.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": self._tool_search_config.max_search_limit,
                            "description": "Maximum matches to return.",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def _tool_describe_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": TOOL_DESCRIBE_NAME,
                "description": "Load the full schema for one deferred tool returned by tool_search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Exact deferred tool name returned by tool_search.",
                        }
                    },
                    "required": ["name"],
                },
            },
        }

    def _tool_call_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": TOOL_CALL_NAME,
                "description": (
                    "Invoke a deferred tool by exact name. Guardrails, approvals, and audit "
                    "run against the real underlying tool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Exact deferred tool name.",
                        },
                        "arguments": {
                            "type": "object",
                            "description": "Arguments matching the schema returned by tool_describe.",
                        },
                    },
                    "required": ["name", "arguments"],
                },
            },
        }


def _rank_tool_matches(query: str, entries: list[ToolEntry]) -> list[tuple[ToolEntry, float]]:
    if not entries:
        return []
    documents = [_tool_tokens(entry) for entry in entries]
    query_tokens = _tokenize(query)
    if not query_tokens:
        return [(entry, 1.0) for entry in entries]

    doc_freq = Counter()
    for tokens in documents:
        for token in set(tokens):
            doc_freq[token] += 1

    avg_len = sum(len(tokens) for tokens in documents) / max(1, len(documents))
    scores: list[tuple[ToolEntry, float]] = []
    for entry, tokens in zip(entries, documents):
        token_counts = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            df = doc_freq.get(token, 0)
            if df == 0:
                continue
            score += _bm25(
                term_frequency=token_counts[token],
                doc_frequency=df,
                total_docs=len(documents),
                doc_len=len(tokens),
                avg_doc_len=avg_len,
            )
        name_text = entry.name.lower()
        description_text = str(entry.description or "").lower()
        if query.lower() and query.lower() in name_text:
            score += 5.0
        elif query.lower() and query.lower() in description_text:
            score += 2.0
        if score > 0:
            scores.append((entry, score))

    if not scores:
        lowered = query.lower()
        scores = [
            (entry, 1.0)
            for entry in entries
            if lowered in entry.name.lower() or lowered in str(entry.description or "").lower()
        ]
    return sorted(scores, key=lambda item: (-item[1], item[0].name))


def _tool_tokens(entry: ToolEntry) -> list[str]:
    params = entry.parameters.get("properties") if isinstance(entry.parameters, dict) else {}
    param_names = " ".join(params.keys()) if isinstance(params, dict) else ""
    text = f"{entry.name} {entry.toolset} {entry.description} {param_names}"
    return _tokenize(text)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]+", str(text or "").lower())


def _bm25(
    term_frequency: int,
    doc_frequency: int,
    total_docs: int,
    doc_len: int,
    avg_doc_len: float,
) -> float:
    if term_frequency <= 0:
        return 0.0
    k1 = 1.5
    b = 0.75
    idf = math.log(1 + (total_docs - doc_frequency + 0.5) / (doc_frequency + 0.5))
    denominator = term_frequency + k1 * (1 - b + b * (doc_len / max(avg_doc_len, 1)))
    return idf * ((term_frequency * (k1 + 1)) / max(denominator, 1e-9))


def _truncate(value: str, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 16)] + "... [truncated]"


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


registry = ToolRegistry()
