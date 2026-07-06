from __future__ import annotations

from typing import Any

from aiagent.plugins.context import PluginContext
from aiagent.plugins.provider import CapabilityProvider


class LocalSpeechToTextProvider(CapabilityProvider):
    kind = "stt"
    name = "local"
    title = "Local speech to text"

    def status(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = config if isinstance(config, dict) else {}
        enabled = bool(config.get("enabled", False))
        issues = []
        if enabled and not str(config.get("model") or "").strip():
            issues.append("missing_model")
        return {
            "kind": self.kind,
            "name": self.name,
            "title": self.title,
            "enabled": enabled,
            "available": bool(enabled and not issues),
            "issues": issues,
            "model": str(config.get("model") or ""),
            "language": str(config.get("language") or "auto"),
            "provider": str(config.get("provider") or self.name),
            "runtime": "reserved",
            "routes": ["web", "tui", "gateway"],
        }


def register(context: PluginContext) -> None:
    context.register_provider(
        kind="stt",
        name="local",
        factory=LocalSpeechToTextProvider,
        title=LocalSpeechToTextProvider.title,
        description="Transcribe voice input through a local speech provider.",
        metadata={"config_path": "auxiliary.stt"},
    )
    context.register_capability(
        name="stt",
        title="Speech to text",
        kind="auxiliary",
        description="Lets Sierra receive voice input when a speech provider is configured.",
        metadata={"provider": "local"},
    )
