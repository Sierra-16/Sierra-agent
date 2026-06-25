from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TASK_STATUSES = {"active", "interrupted", "completed", "cancelled"}
STEP_STATUSES = {"pending", "in_progress", "completed"}
EXECUTION_STATUSES = {
    "started",
    "completed",
    "failed",
    "denied",
    "uncertain",
}


class TaskCheckpointStore:
    """Transactional task plans and tool execution checkpoints."""

    def __init__(self, path: str | Path):
        self.path = os.path.abspath(str(path))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    workspace TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    explanation TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    current_step_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_workspace_status
                ON tasks(workspace, status, updated_at DESC);

                CREATE INDEX IF NOT EXISTS idx_tasks_conversation
                ON tasks(conversation_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS task_steps (
                    task_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    step TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, id),
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_task_steps_order
                ON task_steps(task_id, position);

                CREATE TABLE IF NOT EXISTS task_executions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_id TEXT,
                    tool_call_id TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL,
                    risk TEXT NOT NULL DEFAULT '',
                    arguments TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    result_summary TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_task_executions_status
                ON task_executions(task_id, status, started_at DESC);
                """
            )

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any] | None,
        base_dir: str | Path | None = None,
    ) -> "TaskCheckpointStore":
        config = config or {}
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        configured_path = Path(str(config.get("path", "tasks/task_checkpoints.sqlite3")))
        path = configured_path if configured_path.is_absolute() else root / configured_path
        return cls(path)

    def update_plan(
        self,
        task_id: str,
        conversation_id: str,
        workspace: str,
        objective: str,
        explanation: str,
        steps: list[dict[str, str]],
    ) -> dict[str, Any]:
        now = _utc_now()
        existing = self.get_task(task_id)
        existing_steps = existing.get("steps", []) if existing else []
        existing_ids = {step["id"] for step in existing_steps}
        ids_by_text: dict[str, list[str]] = {}
        for step in existing_steps:
            ids_by_text.setdefault(step["step"], []).append(step["id"])

        normalized_steps = []
        used_ids = set()
        for position, step in enumerate(steps):
            step_id = str(step.get("id") or "").strip()
            if step_id not in existing_ids or step_id in used_ids:
                matches = ids_by_text.get(step["step"], [])
                step_id = next(
                    (candidate for candidate in matches if candidate not in used_ids),
                    "",
                )
            if not step_id:
                step_id = f"step-{uuid.uuid4().hex[:12]}"
            used_ids.add(step_id)
            normalized_steps.append({
                "id": step_id,
                "position": position,
                "step": step["step"],
                "status": step["status"],
                "note": step.get("note", ""),
            })

        current_step = next(
            (step["id"] for step in normalized_steps if step["status"] == "in_progress"),
            None,
        )
        has_uncertain_executions = bool(
            existing and existing.get("uncertain_executions")
        )
        status = (
            "completed"
            if normalized_steps and not has_uncertain_executions and all(
                step["status"] == "completed" for step in normalized_steps
            )
            else "active"
        )

        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO tasks (
                    id, conversation_id, workspace, objective, explanation,
                    status, current_step_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    conversation_id = excluded.conversation_id,
                    workspace = excluded.workspace,
                    objective = excluded.objective,
                    explanation = excluded.explanation,
                    status = excluded.status,
                    current_step_id = excluded.current_step_id,
                    updated_at = excluded.updated_at
                """,
                (
                    task_id,
                    conversation_id,
                    workspace,
                    objective,
                    explanation,
                    status,
                    current_step,
                    existing.get("created_at", now) if existing else now,
                    now,
                ),
            )
            self._connection.execute(
                "DELETE FROM task_steps WHERE task_id = ?",
                (task_id,),
            )
            self._connection.executemany(
                """
                INSERT INTO task_steps (
                    task_id, id, position, step, status, note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        task_id,
                        step["id"],
                        step["position"],
                        step["step"],
                        step["status"],
                        step["note"],
                        now,
                    )
                    for step in normalized_steps
                ],
            )
        return self.get_task(task_id) or {}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                return None
            steps = self._connection.execute(
                """
                SELECT id, position, step, status, note, updated_at
                FROM task_steps WHERE task_id = ? ORDER BY position
                """,
                (str(task_id),),
            ).fetchall()
            uncertain = self._connection.execute(
                """
                SELECT id, step_id, tool_call_id, tool_name, risk, arguments,
                       status, result_summary, started_at, finished_at
                FROM task_executions
                WHERE task_id = ? AND status = 'uncertain'
                ORDER BY started_at
                """,
                (str(task_id),),
            ).fetchall()

        task = dict(row)
        task["steps"] = [dict(step) for step in steps]
        task["uncertain_executions"] = [dict(item) for item in uncertain]
        return task

    def latest_task(
        self,
        workspace: str,
        conversation_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["workspace = ?"]
        params: list[Any] = [workspace]
        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        sql = (
            "SELECT id FROM tasks WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC LIMIT 1"
        )
        with self._lock:
            row = self._connection.execute(sql, params).fetchone()
        return self.get_task(row["id"]) if row else None

    def set_task_status(self, task_id: str, status: str) -> dict[str, Any] | None:
        if status not in TASK_STATUSES:
            raise ValueError(f"Invalid task status: {status}")
        current_step_id = None if status != "active" else _KEEP_VALUE
        with self._lock, self._connection:
            if current_step_id is _KEEP_VALUE:
                cursor = self._connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (status, _utc_now(), task_id),
                )
            else:
                cursor = self._connection.execute(
                    """
                    UPDATE tasks SET status = ?, current_step_id = NULL,
                                     updated_at = ? WHERE id = ?
                    """,
                    (status, _utc_now(), task_id),
                )
        return self.get_task(task_id) if cursor.rowcount else None

    def bind_conversation(self, task_id: str, conversation_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE tasks SET conversation_id = ?, updated_at = ? WHERE id = ?",
                (conversation_id, _utc_now(), task_id),
            )

    def mark_interrupted(self, workspace: str) -> list[str]:
        """Recover rows left active/started by a previous process."""
        now = _utc_now()
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT id FROM tasks WHERE workspace = ? AND status = 'active'",
                (workspace,),
            ).fetchall()
            task_ids = [row["id"] for row in rows]
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                self._connection.execute(
                    f"""
                    UPDATE task_executions
                    SET status = 'uncertain', finished_at = ?
                    WHERE status = 'started' AND task_id IN ({placeholders})
                    """,
                    [now, *task_ids],
                )
                self._connection.execute(
                    f"""
                    UPDATE tasks
                    SET status = 'interrupted', updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    [now, *task_ids],
                )
        return task_ids

    def start_execution(
        self,
        task_id: str,
        step_id: str | None,
        tool_call_id: str,
        tool_name: str,
        risk: str,
        arguments: str,
    ) -> str:
        execution_id = f"exec-{uuid.uuid4().hex}"
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO task_executions (
                    id, task_id, step_id, tool_call_id, tool_name, risk,
                    arguments, status, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?)
                """,
                (
                    execution_id,
                    task_id,
                    step_id,
                    tool_call_id,
                    tool_name,
                    risk,
                    arguments,
                    _utc_now(),
                ),
            )
        return execution_id

    def finish_execution(
        self,
        execution_id: str,
        status: str,
        result_summary: str = "",
    ) -> None:
        if status not in EXECUTION_STATUSES - {"started"}:
            raise ValueError(f"Invalid execution status: {status}")
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE task_executions
                SET status = ?, result_summary = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, result_summary, _utc_now(), execution_id),
            )

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM task_executions WHERE id = ?",
                (execution_id,),
            ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        with self._lock:
            self._connection.close()


_KEEP_VALUE = object()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
