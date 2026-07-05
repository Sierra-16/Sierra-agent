from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from ..auxiliary_config import MODEL_BACKED_PROVIDERS, redact_capability_config


@dataclass(frozen=True)
class CapabilityDefinition:
    name: str
    title: str
    domain: str
    kind: str
    description: str


CAPABILITY_DEFINITIONS: dict[str, CapabilityDefinition] = {
    "vision": CapabilityDefinition(
        name="vision",
        title="Vision",
        domain="media",
        kind="auxiliary",
        description="Understand uploaded images and screenshots.",
    ),
    "web_extract": CapabilityDefinition(
        name="web_extract",
        title="Web extraction",
        domain="research",
        kind="auxiliary",
        description="Read and summarize web pages with an auxiliary model.",
    ),
    "compression": CapabilityDefinition(
        name="compression",
        title="Context compression",
        domain="context",
        kind="auxiliary",
        description="Summarize old conversation turns when the context gets large.",
    ),
    "title": CapabilityDefinition(
        name="title",
        title="Conversation title",
        domain="conversation",
        kind="auxiliary",
        description="Generate short titles for conversations.",
    ),
    "session_search": CapabilityDefinition(
        name="session_search",
        title="Session search",
        domain="memory",
        kind="auxiliary",
        description="Find relevant previous conversations.",
    ),
    "tts": CapabilityDefinition(
        name="tts",
        title="Text to speech",
        domain="voice",
        kind="auxiliary",
        description="Speak Sierra responses through a voice provider.",
    ),
    "stt": CapabilityDefinition(
        name="stt",
        title="Speech to text",
        domain="voice",
        kind="auxiliary",
        description="Transcribe voice input into text.",
    ),
    "image_generation": CapabilityDefinition(
        name="image_generation",
        title="Image generation",
        domain="media",
        kind="auxiliary",
        description="Generate images from Sierra responses or user prompts.",
    ),
    "tools": CapabilityDefinition(
        name="tools",
        title="Tool runtime",
        domain="tools",
        kind="runtime",
        description="Registered local tools, bridge tools, and permission-aware actions.",
    ),
    "mcp": CapabilityDefinition(
        name="mcp",
        title="MCP servers",
        domain="integrations",
        kind="integration",
        description="External MCP servers and their exposed tools.",
    ),
    "memory": CapabilityDefinition(
        name="memory",
        title="Memory",
        domain="memory",
        kind="runtime",
        description="Curated and vector memory providers.",
    ),
    "skills": CapabilityDefinition(
        name="skills",
        title="Skills",
        domain="skills",
        kind="runtime",
        description="Progressively disclosed workflow instructions and resources.",
    ),
    "gateway": CapabilityDefinition(
        name="gateway",
        title="Gateway",
        domain="platform",
        kind="runtime",
        description="Unified entry point for Web, TUI, and future platform adapters.",
    ),
    "tasks": CapabilityDefinition(
        name="tasks",
        title="Tasks",
        domain="planning",
        kind="runtime",
        description="Task plans, checkpoints, and interrupted task recovery.",
    ),
    "cron": CapabilityDefinition(
        name="cron",
        title="Reminders",
        domain="planning",
        kind="runtime",
        description="Scheduled reminders while Sierra is running.",
    ),
    "background": CapabilityDefinition(
        name="background",
        title="Background jobs",
        domain="runtime",
        kind="runtime",
        description="Deferred maintenance jobs such as memory review and indexing.",
    ),
}


STATUS_LABELS = {
    "ready": "Ready",
    "partial": "Partial",
    "needs_config": "Needs config",
    "disabled": "Disabled",
    "unknown": "Unknown",
}


class CapabilityRegistry:
    """Build one UI/API-safe snapshot for Sierra's capabilities."""

    def __init__(
        self,
        *,
        auxiliary_config: dict[str, Any] | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> None:
        self.auxiliary_config = auxiliary_config if isinstance(auxiliary_config, dict) else {}
        self._items = items if isinstance(items, list) else []

    @classmethod
    def from_agent(cls, agent: Any) -> "CapabilityRegistry":
        auxiliary_config = getattr(agent, "auxiliary_config", {})
        items = []
        for name, config in sorted((auxiliary_config if isinstance(auxiliary_config, dict) else {}).items()):
            if isinstance(config, dict):
                items.append(_auxiliary_item(name, config))

        items.extend(
            [
                _tools_item(getattr(agent, "tools", None)),
                _mcp_item(_safe_call(agent, "mcp_status", default={})),
                _memory_item(_safe_call(agent, "memory_status", default={})),
                _skills_item(_safe_call(agent, "skill_summaries", default=[], include_unavailable=True)),
                _gateway_item(agent),
                _tasks_item(
                    current=_safe_call(agent, "task_status", default=None),
                    recovery=_safe_call(agent, "task_recovery", default=None),
                ),
                _cron_item(_safe_call(agent, "cron_status", default={})),
                _background_item(_safe_call(agent, "background_jobs_status", 8, default={})),
            ]
        )
        return cls(auxiliary_config=auxiliary_config, items=items)

    @classmethod
    def from_parts(
        cls,
        *,
        auxiliary_config: dict[str, Any] | None = None,
        tools: Any = None,
        mcp_status: dict[str, Any] | None = None,
        memory_status: dict[str, Any] | None = None,
        skill_summaries: list[dict[str, Any]] | None = None,
        task_status: dict[str, Any] | None = None,
        task_recovery: dict[str, Any] | None = None,
        cron_status: dict[str, Any] | None = None,
        background_status: dict[str, Any] | None = None,
        gateway_enabled: bool = True,
    ) -> "CapabilityRegistry":
        items = []
        for name, config in sorted((auxiliary_config if isinstance(auxiliary_config, dict) else {}).items()):
            if isinstance(config, dict):
                items.append(_auxiliary_item(name, config))
        items.extend(
            [
                _tools_item(tools),
                _mcp_item(mcp_status or {}),
                _memory_item(memory_status or {}),
                _skills_item(skill_summaries or []),
                _gateway_item(None, enabled=gateway_enabled),
                _tasks_item(current=task_status, recovery=task_recovery),
                _cron_item(cron_status or {}),
                _background_item(background_status or {}),
            ]
        )
        return cls(auxiliary_config=auxiliary_config, items=items)

    def get(self, name: str) -> dict[str, Any] | None:
        normalized = str(name or "").strip().lower()
        return next((item for item in self._items if item.get("name") == normalized), None)

    def payload(self) -> dict[str, Any]:
        items = [copy.deepcopy(item) for item in self._items]
        return {
            "summary": _summary(items),
            "items": items,
            "capabilities": items,
            "by_name": {item["name"]: item for item in items if item.get("name")},
        }

    def auxiliary_payload(self) -> dict[str, Any]:
        items = [
            copy.deepcopy(item)
            for item in self._items
            if item.get("kind") == "auxiliary"
        ]
        return {
            "enabled_count": sum(1 for item in items if item.get("enabled")),
            "total": len(items),
            "capabilities": items,
        }

    def prompt_context(self) -> str:
        items = self.payload()["items"]
        lines = ["# Capability Center"]
        for item in items:
            if item.get("kind") != "auxiliary":
                continue
            status = item.get("status", "unknown")
            name = item.get("name", "capability")
            if not item.get("enabled"):
                lines.append(f"- {name}: disabled")
                continue
            route = item.get("route") or item.get("provider") or "unknown"
            model = item.get("model") or item.get("metadata", {}).get("voice") or "unknown"
            lines.append(f"- {name}: {status} via {route} using {model}")

        vision = next((item for item in items if item.get("name") == "vision"), None)
        if vision and vision.get("enabled") and vision.get("available"):
            lines.append(
                "- When the user uploads, references, or asks about an image, call vision_analyze with the image path or URL."
            )
            lines.append("- Ignore older conversation turns that say vision was disabled; use the current capability status above.")
        else:
            lines.append("- vision: disabled or unavailable. Do not claim you inspected image content unless vision_analyze succeeds.")
        return "\n".join(lines)


def _auxiliary_item(name: str, config: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(name, kind="auxiliary")
    redacted = redact_capability_config(config)
    provider = str(config.get("provider") or redacted.get("provider") or "").strip().lower()
    route = str(config.get("route") or redacted.get("route") or provider or "").strip()
    enabled = bool(config.get("enabled"))
    issues: list[str] = []

    if enabled and _is_model_backed(provider, config):
        if not str(config.get("model") or "").strip():
            issues.append("missing_model")
        if provider not in {"main", "model"} and not str(config.get("base_url") or "").strip():
            issues.append("missing_base_url")
        if _requires_api_key(provider, config) and not str(config.get("api_key") or "").strip():
            issues.append("missing_api_key")

    available = bool(enabled and not issues)
    status = _status(enabled=enabled, available=available, issues=issues)
    item = {
        **redacted,
        "name": name,
        "title": definition.title,
        "domain": definition.domain,
        "kind": definition.kind,
        "description": definition.description,
        "enabled": enabled,
        "configured": bool(enabled and not issues),
        "available": available,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "issues": issues,
        "metadata": {
            "format": config.get("format"),
            "voice": config.get("voice"),
            "language": config.get("language"),
            "supports_vision": config.get("supports_vision"),
            "main_supports_vision": config.get("main_supports_vision"),
        },
    }
    item["metadata"] = {key: value for key, value in item["metadata"].items() if value not in ("", None)}
    if route:
        item["route"] = route
    return item


def _tools_item(tools: Any) -> dict[str, Any]:
    names: list[str] = []
    available_names: list[str] = []
    enabled_names: list[str] = []
    toolsets: dict[str, int] = {}
    unavailable: list[str] = []
    disabled: list[str] = []
    direct_count = 0
    deferred_count = 0
    toolset_status: dict[str, Any] = {}
    if tools is not None:
        try:
            names = list(tools.names())
        except Exception:
            names = []
        for name in names:
            try:
                enabled = bool(tools.is_tool_enabled(name))
            except Exception:
                enabled = True
            try:
                available = bool(tools.is_tool_available(name))
            except Exception:
                available = True
            if enabled:
                enabled_names.append(name)
            else:
                disabled.append(name)
            if available:
                available_names.append(name)
            elif enabled:
                unavailable.append(name)
        for name in names:
            try:
                entry = tools.get_entry(name)
            except Exception:
                entry = None
            toolset = str(getattr(entry, "toolset", "core") or "core")
            toolsets[toolset] = toolsets.get(toolset, 0) + 1
        try:
            definitions = tools.get_definitions()
            direct_count = len([item for item in definitions if isinstance(item, dict)])
        except Exception:
            direct_count = len(names)
        deferred_count = max(0, len(names) - direct_count)
        try:
            toolset_status = tools.toolset_status()
        except Exception:
            toolset_status = {}

    issues = [] if names else ["no_tools_registered"]
    return _runtime_item(
        "tools",
        enabled=True,
        available=bool(names),
        issues=issues,
        metadata={
            "total": len(names),
            "enabled": len(enabled_names),
            "disabled": len(disabled),
            "available": len(available_names),
            "unavailable": len(unavailable),
            "direct": direct_count,
            "deferred": deferred_count,
            "toolsets": toolsets,
            "toolset_config": {
                "enabled": toolset_status.get("enabled", []),
                "disabled": toolset_status.get("disabled", []),
                "counts": toolset_status.get("counts", {}),
                "unknown_toolsets": toolset_status.get("unknown_toolsets", []),
            } if isinstance(toolset_status, dict) else {},
        },
    )


def _mcp_item(status: dict[str, Any]) -> dict[str, Any]:
    servers = status.get("servers") if isinstance(status, dict) else []
    servers = servers if isinstance(servers, list) else []
    tools = status.get("tools") if isinstance(status, dict) else []
    tools = tools if isinstance(tools, list) else []
    enabled_servers = [server for server in servers if server.get("enabled", True) is not False]
    running_servers = [server for server in enabled_servers if str(server.get("status") or "").lower() == "running" or server.get("running") is True]
    failed_servers = [server for server in enabled_servers if str(server.get("status") or "").lower() == "failed"]
    issues = []
    if enabled_servers and not running_servers:
        issues.append("no_running_servers")
    if failed_servers:
        issues.append("server_failed")
    return _runtime_item(
        "mcp",
        enabled=bool(enabled_servers),
        available=bool(running_servers or tools),
        issues=issues,
        metadata={
            "servers": len(servers),
            "enabled_servers": len(enabled_servers),
            "running_servers": len(running_servers),
            "failed_servers": len(failed_servers),
            "tools": len(tools),
        },
    )


def _memory_item(status: dict[str, Any]) -> dict[str, Any]:
    providers = status.get("providers") if isinstance(status, dict) else []
    providers = providers if isinstance(providers, list) else []
    available_providers = [
        provider
        for provider in providers
        if isinstance(provider, dict) and provider.get("available", True) is not False
    ]
    issues = [] if available_providers else ["no_available_provider"]
    return _runtime_item(
        "memory",
        enabled=bool(providers),
        available=bool(available_providers),
        issues=issues,
        metadata={
            "providers": len(providers),
            "available_providers": len(available_providers),
            "curated_chars": len(str(status.get("curated") or "")) if isinstance(status, dict) else 0,
        },
    )


def _skills_item(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = summaries if isinstance(summaries, list) else []
    available = [
        item
        for item in summaries
        if not isinstance(item, dict) or item.get("available", True) is not False
    ]
    issues = [] if summaries else ["no_skills_loaded"]
    return _runtime_item(
        "skills",
        enabled=True,
        available=bool(summaries),
        issues=issues,
        metadata={
            "total": len(summaries),
            "available": len(available),
        },
    )


def _gateway_item(agent: Any, *, enabled: bool = True) -> dict[str, Any]:
    workspace = getattr(agent, "workspace", "") if agent is not None else ""
    return _runtime_item(
        "gateway",
        enabled=enabled,
        available=enabled,
        metadata={
            "channels": ["web", "tui"],
            "workspace": workspace,
        },
    )


def _tasks_item(current: dict[str, Any] | None, recovery: dict[str, Any] | None) -> dict[str, Any]:
    enabled = current is not None or recovery is not None
    active = isinstance(current, dict) and bool(current)
    recoverable = isinstance(recovery, dict) and bool(recovery)
    return _runtime_item(
        "tasks",
        enabled=enabled,
        available=enabled,
        metadata={
            "active": active,
            "recoverable": recoverable,
            "status": current.get("status") if isinstance(current, dict) else "",
        },
    )


def _cron_item(status: dict[str, Any]) -> dict[str, Any]:
    tasks = status.get("tasks") if isinstance(status, dict) else []
    tasks = tasks if isinstance(tasks, list) else []
    enabled = bool(status.get("enabled")) if isinstance(status, dict) else False
    return _runtime_item(
        "cron",
        enabled=enabled,
        available=enabled,
        metadata={"tasks": len(tasks)},
    )


def _background_item(status: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(status.get("enabled", False)) if isinstance(status, dict) else False
    pending = int(status.get("pending_count", 0) or 0) if isinstance(status, dict) else 0
    running = int(status.get("running_count", 0) or 0) if isinstance(status, dict) else 0
    failed = int(status.get("failed_count", 0) or 0) if isinstance(status, dict) else 0
    issues = ["jobs_failed"] if failed else []
    return _runtime_item(
        "background",
        enabled=enabled,
        available=enabled,
        issues=issues,
        metadata={
            "pending": pending,
            "running": running,
            "failed": failed,
        },
    )


def _runtime_item(
    name: str,
    *,
    enabled: bool,
    available: bool,
    issues: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = _definition(name, kind="runtime")
    issue_list = list(issues or [])
    status = _status(enabled=enabled, available=available, issues=issue_list)
    return {
        "name": name,
        "title": definition.title,
        "domain": definition.domain,
        "kind": definition.kind,
        "description": definition.description,
        "enabled": bool(enabled),
        "configured": bool(enabled and not issue_list),
        "available": bool(available),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "issues": issue_list,
        "metadata": metadata or {},
    }


def _definition(name: str, *, kind: str) -> CapabilityDefinition:
    normalized = str(name or "").strip().lower()
    definition = CAPABILITY_DEFINITIONS.get(normalized)
    if definition is not None:
        return definition
    return CapabilityDefinition(
        name=normalized,
        title=normalized.replace("_", " ").title() or "Capability",
        domain="custom",
        kind=kind,
        description="Custom Sierra capability.",
    )


def _status(*, enabled: bool, available: bool, issues: list[str]) -> str:
    if not enabled:
        return "disabled"
    if available and not issues:
        return "ready"
    if available and issues:
        return "partial"
    return "needs_config"


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    domains: dict[str, int] = {}
    statuses: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for item in items:
        domain = str(item.get("domain") or "unknown")
        status = str(item.get("status") or "unknown")
        kind = str(item.get("kind") or "unknown")
        domains[domain] = domains.get(domain, 0) + 1
        statuses[status] = statuses.get(status, 0) + 1
        kinds[kind] = kinds.get(kind, 0) + 1

    return {
        "total": len(items),
        "enabled": sum(1 for item in items if item.get("enabled")),
        "ready": statuses.get("ready", 0),
        "partial": statuses.get("partial", 0),
        "needs_config": statuses.get("needs_config", 0),
        "disabled": statuses.get("disabled", 0),
        "domains": domains,
        "statuses": statuses,
        "kinds": kinds,
    }


def _is_model_backed(provider: str, config: dict[str, Any]) -> bool:
    normalized = str(provider or "").strip().lower()
    return (
        normalized in MODEL_BACKED_PROVIDERS
        or bool(config.get("credentials_model"))
        or bool(config.get("base_url"))
    )


def _requires_api_key(provider: str, config: dict[str, Any]) -> bool:
    if config.get("api_key_optional") is True:
        return False
    normalized = str(provider or "").strip().lower()
    return normalized in {"openai_compatible", "custom"}


def _safe_call(obj: Any, method: str, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    func = getattr(obj, method, None)
    if not callable(func):
        return default
    try:
        return func(*args, **kwargs)
    except Exception:
        return default
