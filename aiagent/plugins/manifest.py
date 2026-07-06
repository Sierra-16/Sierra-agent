from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class PluginManifestError(ValueError):
    """Raised when a plugin manifest is missing required structure."""


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    kind: str
    version: str = "0.1.0"
    description: str = ""
    module: str = ""
    entrypoint: str = "register"
    enabled_by_default: bool = False
    capabilities: tuple[str, ...] = ()
    config_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_dir: Path | None = None
    builtin: bool = False

    @classmethod
    def from_file(cls, path: str | Path, *, builtin: bool = False) -> "PluginManifest":
        manifest_path = Path(path)
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PluginManifestError(
                f"{manifest_path}: invalid JSON at line {exc.lineno}, column {exc.colno}"
            ) from exc
        if not isinstance(raw, dict):
            raise PluginManifestError(f"{manifest_path}: manifest root must be an object")
        return cls.from_dict(raw, source_dir=manifest_path.parent, builtin=builtin)

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        *,
        source_dir: str | Path | None = None,
        builtin: bool = False,
    ) -> "PluginManifest":
        plugin_id = _clean_key(raw.get("id") or raw.get("name"))
        if not plugin_id:
            raise PluginManifestError("plugin manifest requires a stable id")

        name = str(raw.get("name") or plugin_id).strip()
        kind = _clean_key(raw.get("kind") or "plugin")
        if not kind:
            raise PluginManifestError(f"{plugin_id}: kind is required")

        module = str(raw.get("module") or "").strip()
        entrypoint = str(raw.get("entrypoint") or "register").strip() or "register"
        capabilities = _string_tuple(raw.get("capabilities"))
        config_schema = raw.get("config_schema") if isinstance(raw.get("config_schema"), dict) else {}
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        return cls(
            id=plugin_id,
            name=name,
            kind=kind,
            version=str(raw.get("version") or "0.1.0").strip(),
            description=str(raw.get("description") or "").strip(),
            module=module,
            entrypoint=entrypoint,
            enabled_by_default=_coerce_bool(raw.get("enabled_by_default"), default=builtin),
            capabilities=capabilities,
            config_schema=dict(config_schema),
            metadata=dict(metadata),
            source_dir=Path(source_dir).resolve() if source_dir else None,
            builtin=bool(builtin),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
            "description": self.description,
            "module": self.module,
            "entrypoint": self.entrypoint,
            "enabled_by_default": self.enabled_by_default,
            "capabilities": list(self.capabilities),
            "config_schema": self.config_schema,
            "metadata": self.metadata,
            "source_dir": str(self.source_dir) if self.source_dir else "",
            "builtin": self.builtin,
        }


def _clean_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    allowed = []
    for char in text:
        if char.isalnum() or char in {"_", "-", ".", ":"}:
            allowed.append(char)
    return "".join(allowed)


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


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    return bool(value)
