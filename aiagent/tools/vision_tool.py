from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .registry import registry
from ..vision import (
    VisionAnalyzer,
    VisionConfigError,
    VisionInputError,
    local_image_source,
    url_image_source,
)


_vision_config: dict[str, Any] = {}
_workspace: str | None = None


def configure_vision_tool(
    workspace: str | None,
    vision_config: dict[str, Any] | None,
) -> None:
    global _workspace, _vision_config
    _workspace = os.path.abspath(workspace or os.getcwd())
    _vision_config = vision_config if isinstance(vision_config, dict) else {}


VISION_ANALYZE_PARAMETERS = {
    "type": "object",
    "properties": {
        "image_path": {
            "type": "string",
            "description": (
                "Workspace-relative or absolute local image path, such as uploads/photo.png. "
                "Use this for images uploaded in the web UI or files found in the workspace."
            ),
        },
        "image_url": {
            "type": "string",
            "description": "HTTP/HTTPS image URL. Use this only when the model provider can fetch the URL.",
        },
        "question": {
            "type": "string",
            "description": "What Sierra should inspect or answer about the image.",
        },
        "detail": {
            "type": "string",
            "enum": ["auto", "low", "high"],
            "description": "Image detail level for providers that support it. Defaults to auto.",
        },
    },
}


def vision_analyze(
    image_path: str = "",
    image_url: str = "",
    question: str = "",
    detail: str = "auto",
) -> str:
    """Analyze an image with the configured auxiliary vision model."""
    try:
        analyzer = VisionAnalyzer(_vision_config)
        if image_path and image_url:
            return _json_error("Provide either image_path or image_url, not both.")
        if image_path:
            resolved = _resolve_image_path(image_path)
            source = local_image_source(resolved, max_bytes=analyzer.max_image_bytes)
            source_payload = {"image_path": str(resolved)}
        elif image_url:
            source = url_image_source(image_url)
            source_payload = {"image_url": image_url}
        else:
            return _json_error("Provide image_path or image_url.")

        result = analyzer.analyze(
            source=source,
            question=question,
            detail=detail,
        )
        result.update(source_payload)
        return json.dumps(result, ensure_ascii=False)
    except (VisionConfigError, VisionInputError, PermissionError) as exc:
        return _json_error(str(exc))
    except Exception as exc:
        return _json_error(f"vision analysis failed: {exc}")


def vision_status() -> dict[str, Any]:
    analyzer = VisionAnalyzer(_vision_config)
    return {
        "enabled": analyzer.enabled,
        "provider": analyzer.provider,
        "route": analyzer.route,
        "model": analyzer.model,
        "base_url_set": bool(analyzer.base_url),
        "api_key_set": bool(analyzer.api_key),
        "max_image_bytes": analyzer.max_image_bytes,
    }


def _json_error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _resolve_image_path(path: str) -> Path:
    raw = str(path or "").strip()
    expanded = os.path.expanduser(os.path.expandvars(raw))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        base = Path(_workspace or os.getcwd())
        candidate = base / candidate
    return candidate.resolve()


registry.register(
    name="vision_analyze",
    description=(
        "Analyze a PNG, JPEG, WebP, or GIF image. Sierra uses the active model's native "
        "vision when it is marked supports_vision=true; otherwise it falls back to "
        "auxiliary.vision. "
        "Use this when the user uploads an image, references an image file, asks about a screenshot, "
        "or wants visual details extracted. It sends the image to the configured external vision provider."
    ),
    parameters=VISION_ANALYZE_PARAMETERS,
    handler=vision_analyze,
    toolset="vision",
    emoji="👁️",
    max_result_size_chars=12000,
)
