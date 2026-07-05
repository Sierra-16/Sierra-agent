from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ToolsetDefinition = dict[str, Any]


TOOLSETS: dict[str, ToolsetDefinition] = {
    "core": {
        "description": "Small always-useful utilities and bridge helpers.",
        "tools": ["calculator", "get_time", "tool_search", "tool_describe", "tool_call"],
        "includes": [],
    },
    "file": {
        "description": "Read, inspect, search, extract, and modify workspace files.",
        "tools": [
            "list_directory",
            "file_info",
            "read_file",
            "read_document",
            "search_files",
            "write_file",
            "patch_file",
            "delete_path",
            "move_path",
            "copy_path",
            "make_directory",
        ],
        "includes": [],
    },
    "file_readonly": {
        "description": "Read-only workspace file listing, inspection, extraction, and search.",
        "tools": ["list_directory", "file_info", "read_file", "read_document", "search_files"],
        "includes": [],
    },
    "web": {
        "description": "Web search, fetch, and extraction tools.",
        "tools": ["web_search", "web_fetch", "web_extract", "browser_fetch"],
        "includes": [],
    },
    "browser": {
        "description": "Real browser navigation and interaction tools.",
        "tools": [
            "browser_fetch",
            "browser_navigate",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_back",
            "browser_press",
            "browser_screenshot",
            "browser_console",
            "browser_close",
        ],
        "includes": [],
    },
    "terminal": {
        "description": "Shell and process tools with permission checks.",
        "tools": ["powershell", "terminal", "process"],
        "includes": [],
    },
    "code_execution": {
        "description": "Sandboxed Python snippets for data and file processing.",
        "tools": ["execute_code"],
        "includes": [],
    },
    "git": {
        "description": "Read-only Git repository inspection.",
        "tools": ["git_inspect"],
        "includes": [],
    },
    "project": {
        "description": "Workspace/project structure inspection.",
        "tools": ["project_inspect"],
        "includes": [],
    },
    "memory": {
        "description": "Curated and vector memory management.",
        "tools": ["save_memory", "delete_memory"],
        "includes": [],
    },
    "session": {
        "description": "Search and load past Sierra sessions.",
        "tools": ["session_search", "session_load"],
        "includes": [],
    },
    "skills": {
        "description": "Progressive Skill discovery, viewing, telemetry, and management.",
        "tools": [
            "skills_list",
            "skill_view",
            "skill_render_template",
            "skill_run_script",
            "skill_reload",
            "skill_manage",
            "skill_usage_stats",
        ],
        "includes": [],
    },
    "planning": {
        "description": "User clarification, task planning, and recovery state.",
        "tools": ["request_user_input", "update_plan", "get_plan", "resolve_task_execution"],
        "includes": [],
    },
    "cron": {
        "description": "Scheduled reminders while Sierra is running.",
        "tools": ["cron_list", "cron_add", "cron_remove"],
        "includes": [],
    },
    "vision": {
        "description": "Image understanding through the main multimodal model or auxiliary vision.",
        "tools": ["vision_analyze"],
        "includes": [],
    },
    "mcp": {
        "description": "External MCP server tools exposed through Sierra.",
        "tools": ["mcp__*"],
        "includes": [],
    },
    "companion": {
        "description": "Companion-focused context, memory, web, vision, and reminders.",
        "tools": [],
        "includes": ["core", "web", "memory", "session", "vision", "planning", "cron"],
    },
    "coding": {
        "description": "Coding-focused workspace tools.",
        "tools": [],
        "includes": [
            "core",
            "file",
            "git",
            "project",
            "terminal",
            "code_execution",
            "web",
            "browser",
            "skills",
            "planning",
            "mcp",
        ],
    },
    "default": {
        "description": "Default Sierra toolset for local interactive use.",
        "tools": [],
        "includes": [
            "core",
            "file",
            "web",
            "browser",
            "terminal",
            "code_execution",
            "git",
            "project",
            "memory",
            "session",
            "skills",
            "planning",
            "cron",
            "vision",
            "mcp",
        ],
    },
}


@dataclass(frozen=True)
class ToolsetSelection:
    enabled: tuple[str, ...] = ("all",)
    disabled: tuple[str, ...] = ()
    additional_tools: tuple[str, ...] = ()
    disabled_tools: tuple[str, ...] = ()
    custom_toolsets: dict[str, ToolsetDefinition] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Any) -> "ToolsetSelection":
        if raw is None:
            return cls()
        if raw is True:
            return cls(enabled=("all",))
        if raw is False:
            return cls(enabled=())
        if isinstance(raw, str):
            return cls(enabled=_as_tuple([raw]))
        if isinstance(raw, (list, tuple, set)):
            return cls(enabled=_as_tuple(raw))
        if not isinstance(raw, dict):
            return cls()

        enabled_raw = _first_present(raw, ("enabled", "allow", "include", "active"), default=("all",))
        if enabled_raw is True:
            enabled = ("all",)
        elif enabled_raw is False:
            enabled = ()
        else:
            enabled = _as_tuple(enabled_raw)

        return cls(
            enabled=enabled,
            disabled=_as_tuple(_first_present(raw, ("disabled", "exclude"), default=())),
            additional_tools=_as_tuple(_first_present(raw, ("additional_tools", "extra_tools", "tools"), default=())),
            disabled_tools=_as_tuple(_first_present(raw, ("disabled_tools", "blocked_tools"), default=())),
            custom_toolsets=_normalize_custom_toolsets(
                _first_present(raw, ("custom", "custom_toolsets"), default={})
            ),
        )


def get_toolset(name: str, custom_toolsets: dict[str, ToolsetDefinition] | None = None) -> ToolsetDefinition | None:
    toolsets = _merged_toolsets(custom_toolsets)
    item = toolsets.get(str(name or "").strip())
    if not item:
        return None
    return {
        "description": str(item.get("description") or ""),
        "tools": list(item.get("tools") or []),
        "includes": list(item.get("includes") or []),
    }


def get_all_toolsets(custom_toolsets: dict[str, ToolsetDefinition] | None = None) -> dict[str, ToolsetDefinition]:
    return {
        name: get_toolset(name, custom_toolsets) or {"description": "", "tools": [], "includes": []}
        for name in sorted(_merged_toolsets(custom_toolsets))
    }


def get_toolset_names(custom_toolsets: dict[str, ToolsetDefinition] | None = None) -> list[str]:
    return sorted(_merged_toolsets(custom_toolsets))


def validate_toolset(name: str, custom_toolsets: dict[str, ToolsetDefinition] | None = None) -> bool:
    normalized = str(name or "").strip()
    if normalized in {"all", "*"}:
        return True
    return normalized in _merged_toolsets(custom_toolsets)


def resolve_toolset(
    name: str,
    *,
    registered_names: list[str] | tuple[str, ...] | set[str] | None = None,
    custom_toolsets: dict[str, ToolsetDefinition] | None = None,
    visited: set[str] | None = None,
) -> list[str]:
    normalized = str(name or "").strip()
    registered = sorted(str(item) for item in (registered_names or []))
    if normalized in {"all", "*"}:
        return registered or sorted(
            {
                tool
                for toolset_name in get_toolset_names(custom_toolsets)
                for tool in resolve_toolset(
                    toolset_name,
                    registered_names=registered,
                    custom_toolsets=custom_toolsets,
                )
            }
        )

    if visited is None:
        visited = set()
    if normalized in visited:
        return []
    visited.add(normalized)

    definition = get_toolset(normalized, custom_toolsets)
    if not definition:
        return []

    tools = set(expand_tool_patterns(definition.get("tools") or [], registered))
    for included in definition.get("includes") or []:
        tools.update(
            resolve_toolset(
                included,
                registered_names=registered,
                custom_toolsets=custom_toolsets,
                visited=visited,
            )
        )
    return sorted(tools)


def resolve_multiple_toolsets(
    names: list[str] | tuple[str, ...] | set[str],
    *,
    registered_names: list[str] | tuple[str, ...] | set[str] | None = None,
    custom_toolsets: dict[str, ToolsetDefinition] | None = None,
) -> list[str]:
    tools: set[str] = set()
    for name in names:
        tools.update(
            resolve_toolset(
                str(name),
                registered_names=registered_names,
                custom_toolsets=custom_toolsets,
            )
        )
    return sorted(tools)


def create_custom_toolset(
    name: str,
    description: str,
    tools: list[str] | None = None,
    includes: list[str] | None = None,
) -> None:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("toolset name is required")
    TOOLSETS[normalized] = {
        "description": str(description or ""),
        "tools": list(tools or []),
        "includes": list(includes or []),
    }


def get_toolset_info(
    name: str,
    *,
    registered_names: list[str] | tuple[str, ...] | set[str] | None = None,
    custom_toolsets: dict[str, ToolsetDefinition] | None = None,
) -> dict[str, Any] | None:
    definition = get_toolset(name, custom_toolsets)
    if not definition:
        return None
    resolved = resolve_toolset(name, registered_names=registered_names, custom_toolsets=custom_toolsets)
    return {
        "name": str(name),
        "description": definition["description"],
        "direct_tools": definition["tools"],
        "includes": definition["includes"],
        "resolved_tools": resolved,
        "tool_count": len(resolved),
        "is_composite": bool(definition["includes"]),
    }


def expand_tool_patterns(
    patterns: list[str] | tuple[str, ...] | set[str],
    registered_names: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    registered = sorted(str(item) for item in (registered_names or []))
    registered_set = set(registered)
    expanded: set[str] = set()
    for pattern in _as_tuple(patterns):
        if pattern in {"*", "all"}:
            expanded.update(registered)
            continue
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            expanded.update(name for name in registered if name.startswith(prefix))
            continue
        if not registered or pattern in registered_set:
            expanded.add(pattern)
    return sorted(expanded)


def unmatched_tool_patterns(
    patterns: list[str] | tuple[str, ...] | set[str],
    registered_names: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    registered = sorted(str(item) for item in (registered_names or []))
    unmatched = []
    for pattern in _as_tuple(patterns):
        if pattern in {"*", "all"}:
            if not registered:
                unmatched.append(pattern)
            continue
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            if not any(name.startswith(prefix) for name in registered):
                unmatched.append(pattern)
            continue
        if pattern not in registered:
            unmatched.append(pattern)
    return unmatched


def _merged_toolsets(custom_toolsets: dict[str, ToolsetDefinition] | None = None) -> dict[str, ToolsetDefinition]:
    merged = dict(TOOLSETS)
    if custom_toolsets:
        merged.update(_normalize_custom_toolsets(custom_toolsets))
    return merged


def _normalize_custom_toolsets(raw: Any) -> dict[str, ToolsetDefinition]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, ToolsetDefinition] = {}
    for name, value in raw.items():
        key = str(name or "").strip()
        if not key:
            continue
        if isinstance(value, dict):
            normalized[key] = {
                "description": str(value.get("description") or f"Custom toolset: {key}"),
                "tools": _as_tuple(value.get("tools", ())),
                "includes": _as_tuple(value.get("includes", ())),
            }
        elif isinstance(value, (list, tuple, set, str)):
            normalized[key] = {
                "description": f"Custom toolset: {key}",
                "tools": _as_tuple(value),
                "includes": [],
            }
    return normalized


def _first_present(raw: dict[str, Any], keys: tuple[str, ...], *, default: Any) -> Any:
    for key in keys:
        if key in raw:
            return raw[key]
    return default


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, dict):
        return tuple(str(key).strip() for key in value if str(key).strip())
    try:
        return tuple(str(item).strip() for item in value if str(item).strip())
    except TypeError:
        text = str(value).strip()
        return (text,) if text else ()
