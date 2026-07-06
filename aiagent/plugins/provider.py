from __future__ import annotations

from abc import ABC
from typing import Any


class CapabilityProvider(ABC):
    """Base class for plugin-backed non-core capabilities."""

    kind: str = "capability"
    name: str = "provider"
    title: str = ""

    def status(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = config if isinstance(config, dict) else {}
        enabled = bool(config.get("enabled", False))
        return {
            "kind": self.kind,
            "name": self.name,
            "title": self.title or self.name,
            "enabled": enabled,
            "available": True,
            "issues": [],
        }

    def close(self) -> None:
        """Release provider resources when needed."""


def model_backed_status(
    *,
    kind: str,
    name: str,
    title: str,
    config: dict[str, Any] | None,
    require_base_url: bool = True,
    require_api_key: bool = True,
    require_model: bool = True,
) -> dict[str, Any]:
    config = config if isinstance(config, dict) else {}
    enabled = bool(config.get("enabled", False))
    issues = []
    if enabled and require_model and not str(config.get("model") or "").strip():
        issues.append("missing_model")
    if enabled and require_base_url and not str(config.get("base_url") or "").strip():
        issues.append("missing_base_url")
    if enabled and require_api_key and not str(config.get("api_key") or "").strip():
        issues.append("missing_api_key")
    return {
        "kind": kind,
        "name": name,
        "title": title,
        "enabled": enabled,
        "available": not issues,
        "issues": issues,
        "model": str(config.get("model") or ""),
        "base_url_set": bool(str(config.get("base_url") or "").strip()),
        "api_key_set": bool(str(config.get("api_key") or "").strip()),
        "provider": str(config.get("provider") or name),
    }
