from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class CronTask:
    id: str
    prompt: str
    interval_minutes: int
    enabled: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0
    last_run_at: float | None = None
    next_run_at: float | None = None


class CronStore:
    def __init__(self, path: str, *, base_dir: str):
        self.path = Path(path if os.path.isabs(path) else os.path.join(base_dir, path))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None, *, base_dir: str) -> "CronStore | None":
        config = config if isinstance(config, dict) else {}
        if config.get("enabled", True) is False:
            return None
        return cls(config.get("path", "tasks/cron_tasks.json"), base_dir=base_dir)

    def list(self) -> list[dict[str, Any]]:
        return [asdict(task) for task in self._load()]

    def add(self, prompt: str, interval_minutes: int) -> dict[str, Any]:
        now = time.time()
        task = CronTask(
            id=f"cron-{uuid.uuid4().hex[:10]}",
            prompt=str(prompt).strip(),
            interval_minutes=max(1, int(interval_minutes or 1)),
            created_at=now,
            updated_at=now,
            next_run_at=now + max(1, int(interval_minutes or 1)) * 60,
        )
        tasks = self._load()
        tasks.append(task)
        self._save(tasks)
        return asdict(task)

    def remove(self, task_id: str) -> bool:
        tasks = self._load()
        next_tasks = [task for task in tasks if task.id != task_id]
        if len(next_tasks) == len(tasks):
            return False
        self._save(next_tasks)
        return True

    def due(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        due_tasks = []
        tasks = self._load()
        changed = False
        for task in tasks:
            if not task.enabled:
                continue
            next_run_at = task.next_run_at or task.created_at
            if next_run_at <= now:
                due_tasks.append(asdict(task))
                task.last_run_at = now
                task.next_run_at = now + task.interval_minutes * 60
                task.updated_at = now
                changed = True
        if changed:
            self._save(tasks)
        return due_tasks

    def _load(self) -> list[CronTask]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        tasks = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or not item.get("id") or not item.get("prompt"):
                continue
            tasks.append(CronTask(
                id=str(item.get("id")),
                prompt=str(item.get("prompt")),
                interval_minutes=max(1, int(item.get("interval_minutes", 60) or 60)),
                enabled=item.get("enabled", True) is not False,
                created_at=float(item.get("created_at", 0) or 0),
                updated_at=float(item.get("updated_at", 0) or 0),
                last_run_at=item.get("last_run_at"),
                next_run_at=item.get("next_run_at"),
            ))
        return tasks

    def _save(self, tasks: list[CronTask]) -> None:
        payload = [asdict(task) for task in tasks]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
