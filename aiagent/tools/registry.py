from __future__ import annotations

import asyncio
import json
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from ..toolsets import (
    SIERRA_CORE_TOOLS,
    ToolsetSelection,
    expand_tool_patterns,
    get_all_toolsets,
    resolve_multiple_toolsets,
    unmatched_tool_patterns,
    validate_toolset,
)


TOOL_SEARCH_NAME = "tool_search"
TOOL_DESCRIBE_NAME = "tool_describe"
TOOL_CALL_NAME = "tool_call"
BRIDGE_TOOL_NAMES = {TOOL_SEARCH_NAME, TOOL_DESCRIBE_NAME, TOOL_CALL_NAME}


CHECK_FN_TTL_SECONDS = 30.0
CHARS_PER_SCHEMA_TOKEN = 4.0


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
        "check_fn",
        "requires_env",
        "is_async",
        "dynamic_schema_overrides",
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
        check_fn=None,
        requires_env=None,
        is_async=False,
        dynamic_schema_overrides=None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.toolset = toolset
        self.emoji = emoji
        self.max_result_size_chars = max_result_size_chars
        self.check_fn = check_fn
        self.requires_env = requires_env or []
        self.is_async = bool(is_async)
        self.dynamic_schema_overrides = dynamic_schema_overrides

    def definition(self) -> dict[str, Any]:
        function = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        if self.dynamic_schema_overrides is not None:
            try:
                overrides = self.dynamic_schema_overrides()
                if isinstance(overrides, dict):
                    function.update(overrides)
            except Exception:
                pass
        return {
            "type": "function",
            "function": function,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}
        self._tool_search_config = ToolSearchConfig()
        self._toolset_selection = ToolsetSelection()
        self._last_deferred_names: set[str] = set()
        self._last_tool_search_active = False
        self._check_fn_cache: dict[Callable[..., Any], tuple[float, bool]] = {}
        self._check_fn_cache_lock = threading.Lock()

    def configure_tools(self, config: Any = None, *, context_window: int | None = None) -> None:
        self.configure_tool_search(config, context_window=context_window)
        self.configure_toolsets(config)

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

    def configure_toolsets(self, config: Any = None) -> None:
        if isinstance(config, dict):
            raw = config.get("toolsets")
        else:
            raw = config
        self._toolset_selection = ToolsetSelection.from_raw(raw)
        self._last_deferred_names.clear()
        self._last_tool_search_active = False

    def register(
        self,
        name,
        description,
        parameters,
        handler,
        toolset="core",
        emoji="",
        max_result_size_chars=None,
        check_fn=None,
        requires_env=None,
        is_async=False,
        dynamic_schema_overrides=None,
    ):
        self._tools[name] = ToolEntry(
            name,
            description,
            parameters,
            handler,
            toolset=toolset,
            emoji=emoji,
            max_result_size_chars=max_result_size_chars,
            check_fn=check_fn,
            requires_env=requires_env,
            is_async=is_async,
            dynamic_schema_overrides=dynamic_schema_overrides,
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

    def invalidate_availability_cache(self) -> None:
        with self._check_fn_cache_lock:
            self._check_fn_cache.clear()

    def is_tool_available(self, name: str) -> bool:
        entry = self.get_entry(name)
        return bool(entry and self._entry_enabled(entry) and self._entry_available(entry))

    def is_tool_runtime_available(self, name: str) -> bool:
        entry = self.get_entry(name)
        return bool(entry and self._entry_available(entry))

    def is_tool_enabled(self, name: str) -> bool:
        entry = self.get_entry(name)
        return bool(entry and self._entry_enabled(entry))

    def available_names(self) -> list[str]:
        return [
            entry.name
            for entry in self._tools.values()
            if self._entry_enabled(entry) and self._entry_available(entry)
        ]

    def enabled_names(self, *, include_unavailable: bool = True) -> list[str]:
        return [
            entry.name
            for entry in self._tools.values()
            if self._entry_enabled(entry)
            and (include_unavailable or self._entry_available(entry))
        ]

    def get_max_result_size(self, name, default=None):
        real_name, _, _ = self.resolve_invocation(name, {})
        entry = self.get_entry(real_name)
        if entry is not None and entry.max_result_size_chars is not None:
            return entry.max_result_size_chars
        return default

    def get_definitions(
        self,
        skip_tool_search_assembly: bool = False,
        include_unavailable: bool = False,
    ):
        entries = self._available_entries() if not include_unavailable else self._enabled_entries()
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

    def tool_search_status(self) -> dict[str, Any]:
        entries = self._available_entries()
        direct_entries, deferred_entries = self._partition_entries(entries)
        deferred_tokens = _estimate_schema_tokens(deferred_entries)
        direct_tokens = _estimate_schema_tokens(direct_entries)
        config = self._tool_search_config
        threshold_tokens = max(
            1,
            int(config.context_window * (config.threshold_pct / 100.0)),
        )
        active = self._should_activate_tool_search(deferred_entries)
        bridge_count = 3 if active and deferred_entries else 0
        return {
            "enabled": config.enabled,
            "active": active,
            "context_budget": config.context_window,
            "threshold_pct": config.threshold_pct,
            "threshold_tokens": threshold_tokens,
            "registered": len(entries),
            "direct_count": len(direct_entries),
            "deferred_count": len(deferred_entries),
            "model_visible_count": len(direct_entries) + bridge_count if active else len(entries),
            "direct_schema_tokens": direct_tokens,
            "deferred_schema_tokens": deferred_tokens,
            "estimated_schema_tokens_saved": deferred_tokens if active else 0,
        }

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
        entry = self._tools[name]
        if not self._entry_enabled(entry):
            return json.dumps({"error": f"Tool is disabled by current toolset: {name}"}, ensure_ascii=False)
        if not self._entry_available(entry):
            return json.dumps({"error": f"Tool is unavailable: {name}"}, ensure_ascii=False)
        try:
            if entry.is_async:
                return _run_async_handler(entry.handler, arguments or {})
            return entry.handler(**(arguments or {}))
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
        if not self._entry_enabled(self._tools[requested]):
            return requested, {}, f"Tool is disabled by current toolset: {requested}"
        if not self._entry_available(self._tools[requested]):
            return requested, {}, f"Tool is unavailable: {requested}"
        if not self._is_tool_search_active_for(requested):
            return requested, {}, f"Tool is not in the deferred catalog: {requested}"

        raw_args = arguments.get("arguments") or {}
        if not isinstance(raw_args, dict):
            return requested, {}, "tool_call.arguments must be an object"
        return requested, raw_args, ""

    def unwrap_invocation(self, name: str, arguments: dict[str, Any] | None):
        return self.resolve_invocation(name, arguments)

    def check_tool_availability(self) -> tuple[list[str], list[dict[str, Any]]]:
        available_toolsets = []
        unavailable = []
        seen = set()
        for entry in self._tools.values():
            toolset = str(entry.toolset or "core")
            if toolset in seen:
                continue
            seen.add(toolset)
            tool_entries = [
                candidate
                for candidate in self._tools.values()
                if str(candidate.toolset or "core") == toolset
            ]
            enabled_entries = [candidate for candidate in tool_entries if self._entry_enabled(candidate)]
            available = any(self._entry_available(candidate) for candidate in enabled_entries)
            if available:
                available_toolsets.append(toolset)
            else:
                requirements = []
                for candidate in tool_entries:
                    for env_name in candidate.requires_env:
                        if env_name not in requirements:
                            requirements.append(env_name)
                unavailable.append({
                    "name": toolset,
                    "env_vars": requirements,
                    "tools": sorted(candidate.name for candidate in tool_entries),
                    "enabled": bool(enabled_entries),
                })
        return sorted(available_toolsets), unavailable

    def get_available_toolsets(self) -> dict[str, dict[str, Any]]:
        toolsets: dict[str, dict[str, Any]] = {}
        for entry in self._tools.values():
            toolset = str(entry.toolset or "core")
            item = toolsets.setdefault(
                toolset,
                {
                    "available": False,
                    "enabled": False,
                    "runtime_available": False,
                    "tools": [],
                    "requirements": [],
                    "description": "",
                },
            )
            item["tools"].append(entry.name)
            enabled = self._entry_enabled(entry)
            runtime_available = self._entry_available(entry)
            item["enabled"] = item["enabled"] or enabled
            item["runtime_available"] = item["runtime_available"] or runtime_available
            item["available"] = item["available"] or (enabled and runtime_available)
            for env_name in entry.requires_env:
                if env_name not in item["requirements"]:
                    item["requirements"].append(env_name)
        for item in toolsets.values():
            item["tools"] = sorted(item["tools"])
        return toolsets

    def get_toolset_requirements(self) -> dict[str, dict[str, Any]]:
        requirements: dict[str, dict[str, Any]] = {}
        for entry in self._tools.values():
            toolset = str(entry.toolset or "core")
            item = requirements.setdefault(
                toolset,
                {
                    "name": toolset,
                    "env_vars": [],
                    "tools": [],
                },
            )
            if entry.name not in item["tools"]:
                item["tools"].append(entry.name)
            for env_name in entry.requires_env:
                if env_name not in item["env_vars"]:
                    item["env_vars"].append(env_name)
        for item in requirements.values():
            item["tools"] = sorted(item["tools"])
        return requirements

    def toolset_status(self) -> dict[str, Any]:
        selection = self._toolset_selection
        registered_names = self.names()
        custom_toolsets = self._runtime_toolsets()
        selected_names = set(self._selected_tool_names())
        disabled_toolset_tools = set(
            resolve_multiple_toolsets(
                selection.disabled,
                registered_names=registered_names,
                custom_toolsets=custom_toolsets,
            )
        )
        disabled_tools = set(expand_tool_patterns(selection.disabled_tools, registered_names))
        all_toolsets = get_all_toolsets(custom_toolsets)
        toolset_items = []
        for name, definition in all_toolsets.items():
            resolved = set(
                resolve_multiple_toolsets(
                    [name],
                    registered_names=registered_names,
                    custom_toolsets=custom_toolsets,
                )
            )
            if not resolved and name not in selection.enabled and name not in selection.disabled:
                continue
            toolset_items.append(
                {
                    "name": name,
                    "description": str(definition.get("description") or ""),
                    "includes": list(definition.get("includes") or []),
                    "tools": sorted(resolved),
                    "tool_count": len(resolved),
                    "enabled": bool(resolved & selected_names),
                    "configured": name in selection.enabled,
                    "disabled": name in selection.disabled,
                }
            )

        unknown_toolsets = [
            name
            for name in [*selection.enabled, *selection.disabled]
            if not validate_toolset(name, custom_toolsets)
        ]
        configured_patterns = [
            *selection.additional_tools,
            *selection.disabled_tools,
        ]
        return {
            "enabled": list(selection.enabled),
            "disabled": list(selection.disabled),
            "additional_tools": list(selection.additional_tools),
            "disabled_tools": list(selection.disabled_tools),
            "custom": sorted(selection.custom_toolsets),
            "visible_tools": sorted(selected_names),
            "hidden_tools": sorted(set(registered_names) - selected_names),
            "counts": {
                "registered": len(registered_names),
                "visible": len(selected_names),
                "hidden": max(0, len(registered_names) - len(selected_names)),
                "disabled_by_toolset": len(disabled_toolset_tools),
                "disabled_by_tool": len(disabled_tools),
            },
            "toolsets": sorted(toolset_items, key=lambda item: item["name"]),
            "unknown_toolsets": sorted(set(unknown_toolsets)),
            "unmatched_patterns": unmatched_tool_patterns(configured_patterns, registered_names),
        }

    def _enabled_entries(self) -> list[ToolEntry]:
        return [
            entry
            for entry in self._tools.values()
            if self._entry_enabled(entry)
        ]

    def _available_entries(self) -> list[ToolEntry]:
        return [
            entry
            for entry in self._tools.values()
            if self._entry_enabled(entry) and self._entry_available(entry)
        ]

    def _entry_enabled(self, entry: ToolEntry) -> bool:
        return entry.name in self._selected_tool_names()

    def _selected_tool_names(self) -> set[str]:
        selection = self._toolset_selection
        registered_names = self.names()
        custom_toolsets = self._runtime_toolsets()
        selected = set(
            resolve_multiple_toolsets(
                selection.enabled,
                registered_names=registered_names,
                custom_toolsets=custom_toolsets,
            )
        )
        selected.update(expand_tool_patterns(selection.additional_tools, registered_names))
        selected.difference_update(
            resolve_multiple_toolsets(
                selection.disabled,
                registered_names=registered_names,
                custom_toolsets=custom_toolsets,
            )
        )
        selected.difference_update(expand_tool_patterns(selection.disabled_tools, registered_names))
        return selected

    def _runtime_toolsets(self) -> dict[str, dict[str, Any]]:
        toolsets = dict(self._toolset_selection.custom_toolsets)
        grouped: dict[str, list[str]] = {}
        for entry in self._tools.values():
            toolset = str(entry.toolset or "core")
            if not toolset:
                continue
            grouped.setdefault(toolset, []).append(entry.name)
        for toolset, names in grouped.items():
            if toolset in toolsets:
                continue
            toolsets[toolset] = {
                "description": f"Registered toolset: {toolset}",
                "tools": sorted(set(names)),
                "includes": [],
            }
        return toolsets

    def _entry_available(self, entry: ToolEntry) -> bool:
        if entry.check_fn is None:
            return True
        return self._check_fn_cached(entry.check_fn)

    def _check_fn_cached(self, check_fn: Callable[..., Any]) -> bool:
        now = time.monotonic()
        with self._check_fn_cache_lock:
            cached = self._check_fn_cache.get(check_fn)
            if cached is not None:
                checked_at, value = cached
                if now - checked_at < CHECK_FN_TTL_SECONDS:
                    return value
        try:
            value = bool(check_fn())
        except Exception:
            value = False
        with self._check_fn_cache_lock:
            self._check_fn_cache[check_fn] = (now, value)
        return value

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
        if entry.name in BRIDGE_TOOL_NAMES:
            return False
        if entry.name in SIERRA_CORE_TOOLS:
            return False
        return True

    def _should_activate_tool_search(self, deferred_entries: list[ToolEntry]) -> bool:
        config = self._tool_search_config
        if config.enabled == "off" or not deferred_entries:
            return False
        if config.enabled == "on":
            return True
        schema_token_estimate = _estimate_schema_tokens(deferred_entries)
        threshold_tokens = int(config.context_window * (config.threshold_pct / 100.0))
        return schema_token_estimate >= max(1, threshold_tokens)

    def _current_deferred_entries(self) -> list[ToolEntry]:
        _, deferred_entries = self._partition_entries(self._available_entries())
        return deferred_entries

    def _is_tool_search_active_for(self, name: str) -> bool:
        if name in self._last_deferred_names:
            return True
        config = self._tool_search_config
        if config.enabled == "off":
            return False
        entry = self._tools.get(name)
        if (
            entry is None
            or not self._entry_enabled(entry)
            or not self._entry_available(entry)
            or not self._is_deferrable(entry)
        ):
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
        if not self._entry_enabled(entry):
            return json.dumps({"error": f"Tool is disabled by current toolset: {name}"}, ensure_ascii=False)
        if not self._entry_available(entry):
            return json.dumps({"error": f"Tool is unavailable: {name}"}, ensure_ascii=False)
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


def _estimate_schema_tokens(entries: list[ToolEntry]) -> int:
    total_chars = 0
    for entry in entries:
        try:
            total_chars += len(
                json.dumps(
                    entry.definition(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError):
            total_chars += len(str(entry.definition()))
    return int(math.ceil(total_chars / CHARS_PER_SCHEMA_TOKEN)) if total_chars else 0


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


def _run_async_handler(handler: Callable[..., Any], arguments: dict[str, Any]) -> str:
    result = handler(**arguments)
    if not hasattr(result, "__await__"):
        return result
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(result)
    raise RuntimeError("Async tool handlers cannot run inside an active event loop")


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
