from __future__ import annotations

from typing import Any

from aiagent.plugins.context import PluginContext
from aiagent.plugins.provider import CapabilityProvider


class EdgeTextToSpeechProvider(CapabilityProvider):
    kind = "tts"
    name = "edge"
    title = "Edge text to speech"

    def status(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = config if isinstance(config, dict) else {}
        enabled = bool(config.get("enabled", False))
        issues = []
        if enabled and not str(config.get("voice") or "").strip():
            issues.append("missing_voice")
        if enabled and not str(config.get("format") or "").strip():
            issues.append("missing_format")
        return {
            "kind": self.kind,
            "name": self.name,
            "title": self.title,
            "enabled": enabled,
            "available": bool(enabled and not issues),
            "issues": issues,
            "voice": str(config.get("voice") or ""),
            "format": str(config.get("format") or ""),
            "provider": str(config.get("provider") or self.name),
            "runtime": "reserved",
            "routes": ["web", "tui", "gateway"],
        }


def register(context: PluginContext) -> None:
    context.register_provider(
        kind="tts",
        name="edge",
        factory=EdgeTextToSpeechProvider,
        title=EdgeTextToSpeechProvider.title,
        description="Speak Sierra responses through an Edge-style voice provider.",
        metadata={"config_path": "auxiliary.tts"},
    )
    context.register_capability(
        name="tts",
        title="Text to speech",
        kind="auxiliary",
        description="Lets Sierra speak responses when a voice provider is configured.",
        metadata={"provider": "edge"},
    )
