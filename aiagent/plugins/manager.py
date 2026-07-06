from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context import PluginContext
from .manifest import PluginManifest, PluginManifestError
from .registry import ProviderRegistry


logger = logging.getLogger(__name__)


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    context: PluginContext | None = None
    enabled: bool = False
    loaded: bool = False
    error: str = ""

    def public_dict(self) -> dict[str, Any]:
        item = self.manifest.public_dict()
        item.update({
            "enabled": self.enabled,
            "loaded": self.loaded,
            "error": self.error,
            "registered_tools": list(self.context.registered_tools) if self.context else [],
            "registered_providers": list(self.context.registered_providers) if self.context else [],
            "capabilities": list(self.context.capabilities) if self.context else [],
        })
        return item


@dataclass
class PluginConfig:
    enabled: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()
    roots: tuple[str, ...] = ("plugins",)
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Any) -> "PluginConfig":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            enabled=_string_tuple(raw.get("enabled")),
            disabled=_string_tuple(raw.get("disabled")),
            roots=_string_tuple(raw.get("roots")) or ("plugins",),
            config=raw.get("config") if isinstance(raw.get("config"), dict) else {},
        )


class PluginManager:
    """Discover and load Sierra plugins through manifest-defined entrypoints."""

    def __init__(
        self,
        *,
        config: PluginConfig | None = None,
        sierra_dir: str | Path = ".",
        workspace: str | Path = ".",
        tool_registry: Any = None,
        app_config: dict[str, Any] | None = None,
    ) -> None:
        self.config = config or PluginConfig()
        self.sierra_dir = Path(sierra_dir).resolve()
        self.workspace = Path(workspace).resolve()
        self.tool_registry = tool_registry
        self.app_config = app_config if isinstance(app_config, dict) else {}
        self.provider_registry = ProviderRegistry()
        self._plugins: dict[str, LoadedPlugin] = {}
        self._errors: list[dict[str, str]] = []

    @classmethod
    def from_config(
        cls,
        raw_config: Any,
        *,
        sierra_dir: str | Path = ".",
        workspace: str | Path = ".",
        tool_registry: Any = None,
        app_config: dict[str, Any] | None = None,
    ) -> "PluginManager":
        return cls(
            config=PluginConfig.from_raw(raw_config),
            sierra_dir=sierra_dir,
            workspace=workspace,
            tool_registry=tool_registry,
            app_config=app_config,
        )

    @property
    def plugins(self) -> tuple[LoadedPlugin, ...]:
        return tuple(sorted(self._plugins.values(), key=lambda item: item.manifest.id))

    def discover(self) -> list[LoadedPlugin]:
        self._plugins.clear()
        self._errors.clear()
        for manifest_path, builtin in self._manifest_paths():
            try:
                manifest = PluginManifest.from_file(manifest_path, builtin=builtin)
            except PluginManifestError as exc:
                self._errors.append({"path": str(manifest_path), "error": str(exc)})
                continue
            self._plugins[manifest.id] = LoadedPlugin(
                manifest=manifest,
                enabled=self._is_enabled(manifest),
            )
        return list(self.plugins)

    def load_enabled(self) -> None:
        if not self._plugins:
            self.discover()
        for loaded in self._plugins.values():
            if not loaded.enabled:
                continue
            self._load_one(loaded)

    def discover_and_load(self) -> "PluginManager":
        self.discover()
        self.load_enabled()
        return self

    def status(self, auxiliary_config: dict[str, Any] | None = None) -> dict[str, Any]:
        items = [plugin.public_dict() for plugin in self.plugins]
        providers = self.provider_registry.status(auxiliary_config)
        return {
            "total": len(items),
            "enabled": len([item for item in items if item.get("enabled")]),
            "loaded": len([item for item in items if item.get("loaded")]),
            "failed": len([item for item in items if item.get("error")]),
            "items": items,
            "errors": list(self._errors),
            "providers": providers,
        }

    def close(self) -> None:
        if self.tool_registry is not None:
            for plugin in self.plugins:
                context = plugin.context
                if not context:
                    continue
                for tool_name in context.registered_tools:
                    try:
                        self.tool_registry.unregister(tool_name)
                    except Exception:
                        pass
        self.provider_registry.close()

    def _load_one(self, loaded: LoadedPlugin) -> None:
        manifest = loaded.manifest
        context = PluginContext(
            manifest=manifest,
            provider_registry=self.provider_registry,
            tool_registry=self.tool_registry,
            workspace=str(self.workspace),
            sierra_dir=str(self.sierra_dir),
            app_config=self.app_config,
            plugin_config=self.config.config.get(manifest.id, {}),
        )
        try:
            entrypoint = self._resolve_entrypoint(manifest)
            entrypoint(context)
            loaded.context = context
            loaded.loaded = True
            loaded.error = ""
        except Exception as exc:
            logger.warning("Plugin '%s' failed to load: %s", manifest.id, exc)
            loaded.context = context
            loaded.loaded = False
            loaded.error = str(exc)

    def _resolve_entrypoint(self, manifest: PluginManifest):
        if manifest.module:
            module = importlib.import_module(manifest.module)
        else:
            module = self._import_from_source(manifest)
        entrypoint = getattr(module, manifest.entrypoint, None)
        if not callable(entrypoint):
            raise RuntimeError(f"entrypoint '{manifest.entrypoint}' is not callable")
        return entrypoint

    def _import_from_source(self, manifest: PluginManifest):
        if manifest.source_dir is None:
            raise RuntimeError("manifest has no source directory")
        source_file = manifest.source_dir / "provider.py"
        if not source_file.exists():
            source_file = manifest.source_dir / "__init__.py"
        if not source_file.exists():
            raise RuntimeError("plugin has no module and no provider.py")
        module_name = "aiagent_dynamic_plugin_" + manifest.id.replace(".", "_").replace("-", "_")
        spec = importlib.util.spec_from_file_location(module_name, source_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to import plugin module from {source_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _manifest_paths(self) -> list[tuple[Path, bool]]:
        paths: list[tuple[Path, bool]] = []
        builtin_root = Path(__file__).resolve().parent / "builtin"
        if builtin_root.exists():
            paths.extend((path, True) for path in sorted(builtin_root.rglob("plugin.json")))
        for root in self._configured_roots():
            if root.exists():
                paths.extend((path, False) for path in sorted(root.rglob("plugin.json")))
        seen = set()
        deduped = []
        for path, builtin in paths:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            deduped.append((resolved, builtin))
        return deduped

    def _configured_roots(self) -> list[Path]:
        roots = []
        for raw in self.config.roots:
            path = Path(raw)
            if not path.is_absolute():
                path = self.sierra_dir / path
            roots.append(path.resolve())
        return roots

    def _is_enabled(self, manifest: PluginManifest) -> bool:
        aliases = {manifest.id.lower(), manifest.name.lower()}
        disabled = {item.lower() for item in self.config.disabled}
        enabled = {item.lower() for item in self.config.enabled}
        if aliases & disabled:
            return False
        if aliases & enabled:
            return True
        return bool(manifest.enabled_by_default)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    try:
        return tuple(str(item).strip() for item in value if str(item).strip())
    except TypeError:
        text = str(value).strip()
        return (text,) if text else ()
