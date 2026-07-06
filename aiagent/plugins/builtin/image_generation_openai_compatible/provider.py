from __future__ import annotations

from typing import Any

from aiagent.plugins.context import PluginContext
from aiagent.plugins.provider import CapabilityProvider, model_backed_status


class OpenAICompatibleImageGenerationProvider(CapabilityProvider):
    kind = "image_generation"
    name = "openai_compatible"
    title = "OpenAI-compatible image generation"

    def status(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            **model_backed_status(
                kind=self.kind,
                name=self.name,
                title=self.title,
                config=config,
                require_base_url=True,
                require_api_key=True,
                require_model=True,
            ),
            "runtime": "reserved",
            "routes": ["web", "tui", "gateway"],
        }


def register(context: PluginContext) -> None:
    context.register_provider(
        kind="image_generation",
        name="openai_compatible",
        factory=OpenAICompatibleImageGenerationProvider,
        title=OpenAICompatibleImageGenerationProvider.title,
        description="Generate images through an OpenAI-compatible images endpoint.",
        metadata={
            "config_path": "auxiliary.image_generation",
            "credential_strategy": "direct_or_credentials_model",
        },
    )
    context.register_capability(
        name="image_generation",
        title="Image generation",
        kind="auxiliary",
        description="Lets Sierra send generated images once an image provider is configured.",
        metadata={"provider": "openai_compatible"},
    )
