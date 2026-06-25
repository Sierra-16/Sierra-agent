from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3


class AuditLogger:
    """Append-only JSONL audit log with simple size-based rotation."""

    def __init__(
        self,
        log_path: str | Path | None = None,
        enabled: bool = True,
        max_bytes: int = DEFAULT_MAX_BYTES,
        backup_count: int = DEFAULT_BACKUP_COUNT,
    ):
        project_root = Path(__file__).resolve().parent.parent
        self.log_path = Path(log_path) if log_path else project_root / "logs" / "tool_audit.jsonl"
        self.enabled = bool(enabled)
        self.max_bytes = max(int(max_bytes), 1024)
        self.backup_count = max(int(backup_count), 0)
        self._lock = threading.Lock()

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any] | None,
        base_dir: str | Path | None = None,
    ) -> "AuditLogger":
        config = config or {}
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        configured_path = Path(str(config.get("path", "logs/tool_audit.jsonl")))
        log_path = configured_path if configured_path.is_absolute() else root / configured_path
        return cls(
            log_path=log_path,
            enabled=config.get("enabled", True) is not False,
            max_bytes=config.get("max_bytes", DEFAULT_MAX_BYTES),
            backup_count=config.get("backup_count", DEFAULT_BACKUP_COUNT),
        )

    def log(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded_size = len(line.encode("utf-8"))

        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(encoded_size)
            with self.log_path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(line)

        return record

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.enabled or limit <= 0:
            return []

        records: list[dict[str, Any]] = []
        with self._lock:
            for path in self._log_paths_oldest_first():
                if not path.exists():
                    continue
                try:
                    with path.open("r", encoding="utf-8") as file:
                        for line in file:
                            try:
                                value = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(value, dict):
                                records.append(value)
                except OSError:
                    continue

        return records[-limit:]

    def _rotate_if_needed(self, incoming_size: int) -> None:
        if not self.log_path.exists():
            return
        if self.log_path.stat().st_size + incoming_size <= self.max_bytes:
            return

        if self.backup_count == 0:
            self.log_path.unlink(missing_ok=True)
            return

        for index in range(self.backup_count, 0, -1):
            source = self.log_path if index == 1 else self._backup_path(index - 1)
            destination = self._backup_path(index)
            if not source.exists():
                continue
            destination.unlink(missing_ok=True)
            source.replace(destination)

    def _backup_path(self, index: int) -> Path:
        return self.log_path.with_name(f"{self.log_path.name}.{index}")

    def _log_paths_oldest_first(self) -> list[Path]:
        backups = [
            self._backup_path(index)
            for index in range(self.backup_count, 0, -1)
        ]
        return [*backups, self.log_path]
