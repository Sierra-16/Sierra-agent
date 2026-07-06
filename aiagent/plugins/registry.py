from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ProviderFactory = Callable[[], Any]


@dataclass
class ProviderRegistration:
    kind: str
    name: str
    plugin_id: str
    factory: ProviderFactory
    title: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.name}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "plugin_id": self.plugin_id,
            "title": self.title or self.name,
            "description": self.description,
            "metadata": self.metadata,
        }


class ProviderRegistry:
    """Runtime registry for plugin-backed providers."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderRegistration] = {}
        self._instances: dict[str, Any] = {}

    def register(
        self,
        *,
        kind: str,
        name: str,
        plugin_id: str,
        factory: ProviderFactory,
        title: str = "",
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProviderRegistration:
        registration = ProviderRegistration(
            kind=_clean(kind),
            name=_clean(name),
            plugin_id=plugin_id,
            factory=factory,
            title=title,
            description=description,
            metadata=dict(metadata or {}),
        )
        if not registration.kind or not registration.name:
            raise ValueError("provider kind and name are required")
        self._providers[registration.key] = registration
        self._instances.pop(registration.key, None)
        return registration

    def registrations(self, kind: str | None = None) -> list[ProviderRegistration]:
        if not kind:
            return sorted(self._providers.values(), key=lambda item: item.key)
        normalized = _clean(kind)
        return sorted(
            [item for item in self._providers.values() if item.kind == normalized],
            key=lambda item: item.key,
        )

    def get(self, kind: str, name: str) -> ProviderRegistration | None:
        return self._providers.get(f"{_clean(kind)}:{_clean(name)}")

    def instance(self, registration: ProviderRegistration) -> Any:
        if registration.key not in self._instances:
            self._instances[registration.key] = registration.factory()
        return self._instances[registration.key]

    def status(self, auxiliary_config: dict[str, Any] | None = None) -> dict[str, Any]:
        auxiliary_config = auxiliary_config if isinstance(auxiliary_config, dict) else {}
        items = []
        for registration in self.registrations():
            config = auxiliary_config.get(registration.kind)
            has_config = isinstance(config, dict)
            if not has_config:
                config = {}
            active_provider = str(config.get("provider") or registration.name).strip().lower()
            active = bool(has_config) and active_provider == registration.name
            provider_config = config if active else {**config, "enabled": False}
            item = registration.public_dict()
            item["active"] = active
            try:
                provider = self.instance(registration)
                if hasattr(provider, "status"):
                    provider_status = provider.status(provider_config)
                else:
                    provider_status = {"available": True, "issues": []}
                if isinstance(provider_status, dict):
                    item.update(provider_status)
            except Exception as exc:
                item.update({
                    "available": False,
                    "issues": ["provider_status_failed"],
                    "error": str(exc),
                })
            item["enabled"] = bool(item.get("enabled", False)) and active
            item.setdefault("available", True)
            item.setdefault("issues", [])
            items.append(item)

        by_kind: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_kind.setdefault(str(item.get("kind") or "provider"), []).append(item)
        return {
            "total": len(items),
            "items": items,
            "by_kind": by_kind,
        }

    def close(self) -> None:
        for instance in list(self._instances.values()):
            close = getattr(instance, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._instances.clear()


def _clean(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")
