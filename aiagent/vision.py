from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI


SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
}


@dataclass(frozen=True)
class VisionSource:
    kind: str
    value: str
    mime_type: str = ""
    size_bytes: int = 0


class VisionConfigError(RuntimeError):
    pass


class VisionInputError(RuntimeError):
    pass


class VisionAnalyzer:
    def __init__(self, config: dict[str, Any]):
        self.config = config if isinstance(config, dict) else {}
        self.enabled = bool(self.config.get("enabled"))
        self.provider = str(self.config.get("provider") or "openai_compatible").strip()
        self.route = str(self.config.get("route") or "auxiliary_vision").strip()
        self.model = str(self.config.get("model") or "").strip()
        self.base_url = str(self.config.get("base_url") or "").strip()
        self.api_key = str(self.config.get("api_key") or "").strip()
        self.timeout = _coerce_int(self.config.get("timeout"), 30, minimum=1, maximum=300)
        self.max_tokens = _coerce_int(self.config.get("max_tokens"), 2048, minimum=1, maximum=200000)
        self.temperature = _coerce_float(self.config.get("temperature"), 0.1, minimum=0.0, maximum=2.0)
        self.max_image_bytes = _coerce_int(
            self.config.get("max_image_bytes"),
            20 * 1024 * 1024,
            minimum=1024,
            maximum=80 * 1024 * 1024,
        )

    def analyze(
        self,
        *,
        source: VisionSource,
        question: str,
        detail: str = "auto",
    ) -> dict[str, Any]:
        self._validate_config()
        question = str(question or "").strip() or "请描述这张图片，并提取对当前任务有用的信息。"
        detail = _normalize_detail(detail)
        image_url = source.value if source.kind == "url" else _data_url(source)
        content = [
            {
                "type": "text",
                "text": (
                    "请用中文回答。先直接回答用户问题，再列出你从图片中看到的关键证据。"
                    f"\n\n用户问题：{question}"
                ),
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": image_url,
                    "detail": detail,
                },
            },
        ]
        client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Sierra's vision module. Analyze images carefully, "
                        "avoid hallucinating unseen details, and answer in Chinese unless asked otherwise."
                    ),
                },
                {"role": "user", "content": content},
            ],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        message = response.choices[0].message
        usage = response.usage
        return {
            "ok": True,
            "provider": self.provider,
            "route": self.route,
            "model": self.model,
            "source": _source_summary(source),
            "answer": message.content or "",
            "usage": {
                "input": usage.prompt_tokens if usage else 0,
                "output": usage.completion_tokens if usage else 0,
            },
        }

    def _validate_config(self) -> None:
        if not self.enabled:
            raise VisionConfigError("vision is disabled; enable auxiliary.vision in config.json")
        if not self.model:
            raise VisionConfigError("auxiliary.vision.model is not configured")
        if not self.base_url:
            raise VisionConfigError("auxiliary.vision.base_url is not configured")
        if not self.api_key:
            raise VisionConfigError("auxiliary.vision.api_key is not configured")
        if self.provider not in {"openai_compatible", "auto", "main", "model", "custom"}:
            raise VisionConfigError(f"unsupported vision provider: {self.provider}")


def local_image_source(path: str | Path, *, max_bytes: int = 20 * 1024 * 1024) -> VisionSource:
    image_path = Path(path).resolve()
    if not image_path.is_file():
        raise VisionInputError(f"image file not found: {path}")
    size = image_path.stat().st_size
    if size > max_bytes:
        raise VisionInputError(f"image file is too large: {size} bytes; limit is {max_bytes} bytes")
    mime_type = guess_image_mime_type(image_path)
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise VisionInputError(
            f"unsupported image type: {mime_type or image_path.suffix or 'unknown'}"
        )
    raw = image_path.read_bytes()
    return VisionSource(
        kind="data",
        value=base64.b64encode(raw).decode("ascii"),
        mime_type=mime_type,
        size_bytes=size,
    )


def url_image_source(url: str) -> VisionSource:
    value = str(url or "").strip()
    if not value.lower().startswith(("http://", "https://")):
        raise VisionInputError("image_url must start with http:// or https://")
    return VisionSource(kind="url", value=value)


def guess_image_mime_type(path: str | Path) -> str:
    mime_type, _encoding = mimetypes.guess_type(str(path))
    return str(mime_type or "").lower()


def is_supported_image_path(path: str | Path) -> bool:
    return guess_image_mime_type(path) in SUPPORTED_IMAGE_MIME_TYPES


def _data_url(source: VisionSource) -> str:
    return f"data:{source.mime_type};base64,{source.value}"


def _source_summary(source: VisionSource) -> dict[str, Any]:
    if source.kind == "url":
        return {"kind": "url", "url": source.value}
    return {
        "kind": "file",
        "mime_type": source.mime_type,
        "size_bytes": source.size_bytes,
    }


def _normalize_detail(value: str) -> str:
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in {"auto", "low", "high"} else "auto"


def _coerce_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _coerce_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)
