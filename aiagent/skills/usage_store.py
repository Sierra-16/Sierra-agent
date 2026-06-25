from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..safety import sanitize_text


SKILL_EVENT_TYPES = {"view", "template_render", "script_run"}


class SkillUsageStore:
    """Persist privacy-bounded Skill usage events and aggregate statistics."""

    def __init__(
        self,
        path: str | Path,
        enabled: bool = True,
        store_queries: bool = True,
        max_query_chars: int = 1000,
    ):
        self.path = os.path.abspath(str(path))
        self.enabled = bool(enabled)
        self.store_queries = bool(store_queries)
        self.max_query_chars = max(0, min(8000, int(max_query_chars or 0)))
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        if self.enabled:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._connection = sqlite3.connect(self.path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._initialize()

    @classmethod
    def from_config(
        cls,
        skill_config: dict[str, Any] | None,
        base_dir: str | Path | None = None,
    ) -> "SkillUsageStore":
        skill_config = skill_config if isinstance(skill_config, dict) else {}
        config = skill_config.get("telemetry", {})
        config = config if isinstance(config, dict) else {}
        root = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        configured_path = Path(str(config.get("path", "logs/skill_usage.sqlite3")))
        path = configured_path if configured_path.is_absolute() else root / configured_path
        return cls(
            path=path,
            enabled=config.get("enabled", True) is not False,
            store_queries=config.get("store_queries", True) is not False,
            max_query_chars=config.get("max_query_chars", 1000),
        )

    def record(
        self,
        *,
        turn_id: int | None = None,
        skill_name: str,
        event_type: str,
        success: bool,
        executed: bool,
        duration_ms: int = 0,
        conversation_id: str | None = None,
        model: str = "",
        workspace: str = "",
        file_path: str | None = None,
        user_query: str | None = None,
        error: str | None = None,
    ) -> int | None:
        if not self.enabled or self._connection is None:
            return None
        skill_name = str(skill_name or "").strip()
        if not skill_name:
            return None
        event_type = str(event_type or "").strip()
        if event_type not in SKILL_EVENT_TYPES:
            raise ValueError(f"Unsupported skill event type: {event_type}")
        query = ""
        if self.store_queries and user_query:
            query = sanitize_text(str(user_query), max_length=self.max_query_chars)
        error_text = sanitize_text(str(error or ""), max_length=500)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO skill_usage_events (
                    turn_id, created_at, conversation_id, model, workspace, skill_name,
                    event_type, file_path, success, executed, duration_ms,
                    user_query, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    now,
                    str(conversation_id or ""),
                    str(model or ""),
                    os.path.abspath(workspace) if workspace else "",
                    skill_name,
                    event_type,
                    str(file_path or ""),
                    int(bool(success)),
                    int(bool(executed)),
                    max(0, int(duration_ms or 0)),
                    query,
                    error_text,
                ),
            )
            return int(cursor.lastrowid)

    def start_turn(
        self,
        *,
        user_query: str,
        conversation_id: str | None = None,
        model: str = "",
        workspace: str = "",
    ) -> int | None:
        if not self.enabled or self._connection is None:
            return None
        query = ""
        if self.store_queries:
            query = sanitize_text(str(user_query or ""), max_length=self.max_query_chars)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO skill_usage_turns (
                    created_at, conversation_id, model, workspace, user_query
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    str(conversation_id or ""),
                    str(model or ""),
                    os.path.abspath(workspace) if workspace else "",
                    query,
                ),
            )
            return int(cursor.lastrowid)

    def stats(self, workspace: str | None = None, limit: int = 20) -> dict[str, Any]:
        if not self.enabled or self._connection is None:
            return {
                "enabled": False,
                "path": self.path,
                "total_events": 0,
                "skills": [],
            }
        limit = max(1, min(100, int(limit or 20)))
        where = ""
        parameters: list[Any] = []
        if workspace:
            where = "WHERE workspace = ?"
            parameters.append(os.path.abspath(workspace))
        with self._lock:
            totals = self._connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_events,
                    COUNT(DISTINCT skill_name) AS distinct_skills,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes
                FROM skill_usage_events
                {where}
                """,
                parameters,
            ).fetchone()
            rows = self._connection.execute(
                f"""
                SELECT
                    skill_name,
                    COUNT(*) AS total,
                    SUM(CASE WHEN event_type = 'view' THEN 1 ELSE 0 END) AS views,
                    SUM(CASE WHEN event_type = 'template_render' THEN 1 ELSE 0 END) AS renders,
                    SUM(CASE WHEN event_type = 'script_run' THEN 1 ELSE 0 END) AS script_runs,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failures,
                    SUM(CASE WHEN executed = 0 THEN 1 ELSE 0 END) AS denied,
                    ROUND(AVG(duration_ms), 1) AS average_duration_ms,
                    MAX(created_at) AS last_used_at
                FROM skill_usage_events
                {where}
                GROUP BY skill_name
                ORDER BY total DESC, last_used_at DESC, skill_name
                LIMIT ?
                """,
                [*parameters, limit],
            ).fetchall()
            turn_totals = self._connection.execute(
                f"SELECT COUNT(*) AS total_turns FROM skill_usage_turns {where}",
                parameters,
            ).fetchone()
            turns_with_skills = self._connection.execute(
                f"""
                SELECT COUNT(DISTINCT turn_id) AS turns_with_skills
                FROM skill_usage_events
                {where + (' AND' if where else 'WHERE')} turn_id IS NOT NULL
                  AND event_type = 'view' AND success = 1
                """,
                parameters,
            ).fetchone()
        total_events = int(totals["total_events"] or 0)
        successes = int(totals["successes"] or 0)
        total_turns = int(turn_totals["total_turns"] or 0)
        used_turns = int(turns_with_skills["turns_with_skills"] or 0)
        return {
            "enabled": True,
            "path": self.path,
            "workspace": os.path.abspath(workspace) if workspace else None,
            "total_events": total_events,
            "distinct_skills": int(totals["distinct_skills"] or 0),
            "success_rate": round(successes / total_events, 4) if total_events else None,
            "total_turns": total_turns,
            "turns_with_skills": used_turns,
            "skill_load_rate": round(used_turns / total_turns, 4) if total_turns else None,
            "skills": [dict(row) for row in rows],
        }

    def selections_for_queries(
        self,
        queries: Iterable[str],
        workspace: str | None = None,
    ) -> dict[str, set[str]]:
        normalized = {_normalize_query(query): str(query) for query in queries if str(query).strip()}
        selections = {key: set() for key in normalized}
        if not normalized or not self.enabled or self._connection is None:
            return selections
        placeholders = ",".join("?" for _ in normalized)
        parameters: list[Any] = list(normalized)
        workspace_clause = ""
        if workspace:
            workspace_clause = " AND workspace = ?"
            parameters.append(os.path.abspath(workspace))
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT user_query, skill_name
                FROM skill_usage_events
                WHERE event_type = 'view'
                  AND success = 1
                  AND LOWER(TRIM(user_query)) IN ({placeholders})
                  {workspace_clause}
                ORDER BY id
                """,
                parameters,
            ).fetchall()
        for row in rows:
            key = _normalize_query(row["user_query"])
            if key in selections:
                selections[key].add(str(row["skill_name"]))
        return selections

    def evaluation_observations(
        self,
        queries: Iterable[str],
        workspace: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        normalized = {_normalize_query(query) for query in queries if str(query).strip()}
        observations = {
            query: {"observed": False, "skills": set()}
            for query in normalized
        }
        if not normalized or not self.enabled or self._connection is None:
            return observations
        where = "WHERE user_query != ''"
        parameters: list[Any] = []
        if workspace:
            where += " AND workspace = ?"
            parameters.append(os.path.abspath(workspace))
        with self._lock:
            turns = self._connection.execute(
                f"SELECT id, user_query FROM skill_usage_turns {where}",
                parameters,
            ).fetchall()
            turn_ids: dict[int, str] = {}
            for turn in turns:
                query = _normalize_query(turn["user_query"])
                if query in observations:
                    observations[query]["observed"] = True
                    turn_ids[int(turn["id"])] = query
            if not turn_ids:
                return observations
            placeholders = ",".join("?" for _ in turn_ids)
            rows = self._connection.execute(
                f"""
                SELECT turn_id, skill_name
                FROM skill_usage_events
                WHERE turn_id IN ({placeholders})
                  AND event_type = 'view' AND success = 1
                """,
                list(turn_ids),
            ).fetchall()
        for row in rows:
            query = turn_ids.get(int(row["turn_id"]))
            if query:
                observations[query]["skills"].add(str(row["skill_name"]))
        return observations

    def recent(self, limit: int = 20, workspace: str | None = None) -> list[dict[str, Any]]:
        if not self.enabled or self._connection is None:
            return []
        limit = max(1, min(100, int(limit or 20)))
        where = ""
        parameters: list[Any] = []
        if workspace:
            where = "WHERE workspace = ?"
            parameters.append(os.path.abspath(workspace))
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT id, created_at, conversation_id, model, workspace,
                       skill_name, event_type, file_path, success, executed,
                       duration_ms, user_query, error
                FROM skill_usage_events
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                [*parameters, limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            self._connection.close()
            self._connection = None

    def _initialize(self) -> None:
        assert self._connection is not None
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id INTEGER,
                    created_at TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    workspace TEXT NOT NULL DEFAULT '',
                    skill_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    file_path TEXT NOT NULL DEFAULT '',
                    success INTEGER NOT NULL,
                    executed INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    user_query TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS skill_usage_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    conversation_id TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    workspace TEXT NOT NULL DEFAULT '',
                    user_query TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_skill_usage_workspace_time
                ON skill_usage_events(workspace, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_skill_usage_name_type
                ON skill_usage_events(skill_name, event_type, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_skill_usage_query
                ON skill_usage_events(user_query, event_type);

                CREATE INDEX IF NOT EXISTS idx_skill_turns_workspace_time
                ON skill_usage_turns(workspace, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_skill_turns_query
                ON skill_usage_turns(user_query);
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(skill_usage_events)"
                ).fetchall()
            }
            if "turn_id" not in columns:
                self._connection.execute(
                    "ALTER TABLE skill_usage_events ADD COLUMN turn_id INTEGER"
                )


def _normalize_query(value: str) -> str:
    return " ".join(str(value).strip().lower().split())
