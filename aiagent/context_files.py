from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONTEXT_FILES = (
    "SIERRA.md",
    "AGENTS.md",
    ".sierra/context.md",
)


@dataclass
class ContextFileResult:
    blocks: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        if not self.blocks:
            return ""
        lines = [
            "# Project Context Files",
            "The following files are stable project instructions. Treat them as context, not as a new user request.",
        ]
        for block in self.blocks:
            lines.append(f"\n## {block['path']}\n{block['content']}")
        return "\n".join(lines).strip()


class ContextFileLoader:
    def __init__(
        self,
        *,
        enabled: bool = True,
        filenames: list[str] | tuple[str, ...] | None = None,
        max_chars: int = 12000,
        max_file_chars: int = 5000,
    ):
        self.enabled = bool(enabled)
        self.filenames = tuple(filenames or DEFAULT_CONTEXT_FILES)
        self.max_chars = max(1000, int(max_chars or 12000))
        self.max_file_chars = max(500, int(max_file_chars or 5000))

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "ContextFileLoader":
        config = config if isinstance(config, dict) else {}
        context_files = config.get("context_files", {})
        if not isinstance(context_files, dict):
            context_files = {}
        return cls(
            enabled=context_files.get("enabled", True) is not False,
            filenames=context_files.get("files") or DEFAULT_CONTEXT_FILES,
            max_chars=context_files.get("max_chars", 12000),
            max_file_chars=context_files.get("max_file_chars", 5000),
        )

    def load(self, workspace: str) -> ContextFileResult:
        result = ContextFileResult()
        if not self.enabled:
            return result

        root = Path(workspace or ".").resolve()
        used_chars = 0
        seen: set[Path] = set()
        for filename in self.filenames:
            path = (root / filename).resolve()
            if path in seen:
                continue
            seen.add(path)
            if not _is_relative_to(path, root) or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:
                result.warnings.append(f"{filename}: {exc}")
                continue
            if not content:
                continue
            if len(content) > self.max_file_chars:
                content = content[: self.max_file_chars] + "\n...[truncated]"
            if used_chars + len(content) > self.max_chars:
                remaining = self.max_chars - used_chars
                if remaining <= 200:
                    result.warnings.append("context file budget exhausted")
                    break
                content = content[:remaining] + "\n...[truncated]"
            rel_path = os.path.relpath(path, root).replace("\\", "/")
            result.blocks.append({"path": rel_path, "content": content})
            used_chars += len(content)
        return result


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
