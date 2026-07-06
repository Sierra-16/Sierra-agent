from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .manifest import PluginManifest
from .registry import ProviderRegistry


@dataclass
class PluginContext:
    manifest: PluginManifest
    provider_registry: ProviderRegistry
    tool_registry: Any = None
    workspace: str = "."
    sierra_dir: str = "."
    app_config: dict[str, Any] = field(default_factory=dict)
    plugin_config: dict[str, Any] = field(default_factory=dict)
    registered_tools: list[str] = field(default_factory=list)
    registered_providers: list[str] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)

    @property
    def source_dir(self) -> Path | None:
        return self.manifest.source_dir

    def register_provider(
        self,
        *,
        kind: str,
        name: str,
        factory: Callable[[], Any],
        title: str = "",
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        registration = self.provider_registry.register(
            kind=kind,
            name=name,
            plugin_id=self.manifest.id,
            factory=factory,
            title=title,
            description=description,
            metadata=metadata,
        )
        self.registered_providers.append(registration.key)

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., str],
        toolset: str | None = None,
        emoji: str = "",
        max_result_size_chars: int | None = None,
        check_fn: Callable[[], bool] | None = None,
        requires_env: list[str] | None = None,
        is_async: bool = False,
        dynamic_schema_overrides: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if self.tool_registry is None:
            raise RuntimeError("tool registry is not available for this plugin")
        self.tool_registry.register(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            toolset=toolset or f"plugin:{self.manifest.id}",
            emoji=emoji,
            max_result_size_chars=max_result_size_chars,
            check_fn=check_fn,
            requires_env=requires_env,
            is_async=is_async,
            dynamic_schema_overrides=dynamic_schema_overrides,
        )
        self.registered_tools.append(name)

    def register_capability(
        self,
        *,
        name: str,
        title: str,
        kind: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.capabilities.append({
            "name": str(name),
            "title": str(title),
            "kind": str(kind),
            "description": str(description),
            "metadata": dict(metadata or {}),
            "plugin_id": self.manifest.id,
        })
