from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


DEFAULT_RESULT_SIZE_CHARS = 100_000
DEFAULT_PREVIEW_SIZE_CHARS = 8_000
STORAGE_DIR_NAME = "sierra-tool-results"
PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"


def maybe_persist_tool_result(
    content: str,
    *,
    tool_name: str,
    tool_call_id: str,
    threshold: int | float | None = None,
    preview_size: int = DEFAULT_PREVIEW_SIZE_CHARS,
) -> str:
    """Persist oversized tool output and return a compact preview block."""
    if not isinstance(content, str):
        content = str(content)
    effective_threshold = (
        DEFAULT_RESULT_SIZE_CHARS if threshold is None else threshold
    )
    if effective_threshold == float("inf") or len(content) <= int(effective_threshold):
        return content

    storage_dir = Path(tempfile.gettempdir()) / STORAGE_DIR_NAME
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_name = _safe_file_name(tool_call_id or tool_name or "tool-result")
    file_path = storage_dir / f"{file_name}.txt"
    file_path.write_text(content, encoding="utf-8")

    preview, has_more = generate_preview(content, preview_size)
    size_kb = len(content) / 1024
    size_text = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.1f} KB"
    message = [
        PERSISTED_OUTPUT_TAG,
        f"Tool result for {tool_name} was large ({len(content):,} chars, {size_text}).",
        f"Full output saved to: {file_path}",
        "Use read_file with this absolute path to inspect the full result if needed.",
        "",
        f"Preview (first {len(preview)} chars):",
        preview,
    ]
    if has_more:
        message.append("...")
    message.append(PERSISTED_OUTPUT_CLOSING_TAG)
    return "\n".join(message)


def generate_preview(content: str, max_chars: int = DEFAULT_PREVIEW_SIZE_CHARS) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return content, False
    truncated = content[:max_chars]
    last_newline = truncated.rfind("\n")
    if last_newline > max_chars // 2:
        truncated = truncated[:last_newline + 1]
    return truncated, True


def _safe_file_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value))
    value = value.strip("._")[:80]
    return value or "tool-result"
