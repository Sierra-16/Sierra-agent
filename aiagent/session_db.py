from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "data/sierra.sqlite3"
SCHEMA_VERSION = 1
CONTENT_JSON_PREFIX = "\x00json:"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    model TEXT,
    cwd TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    ended_at REAL,
    message_count INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    created_at REAL NOT NULL,
    token_count INTEGER,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, active, id);
"""


FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
    INSERT INTO messages_fts(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;
"""


class SessionDB:
    """SQLite-backed session history with optional FTS5 search."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None, base_dir: str | None = None):
        path = Path(db_path or DEFAULT_DB_PATH)
        if not path.is_absolute():
            path = Path(base_dir or os.getcwd()) / path
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fts_enabled = False
        self._initialize()

    @classmethod
    def from_config(cls, config: dict[str, Any] | None, base_dir: str | None = None) -> "SessionDB | None":
        config = config if isinstance(config, dict) else {}
        if config.get("enabled", True) is False:
            return None
        return cls(config.get("path", DEFAULT_DB_PATH), base_dir=base_dir)

    def _initialize(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            try:
                self._conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:
                pass
            self._conn.executescript(SCHEMA_SQL)
            self._ensure_schema_version()
            self._initialize_fts()
            self._conn.commit()

    def _ensure_schema_version(self) -> None:
        row = self._conn.execute("SELECT COUNT(*) AS count FROM schema_version").fetchone()
        if int(row["count"]) == 0:
            self._conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            return
        self._conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

    def _initialize_fts(self) -> None:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE temp._sierra_fts_probe USING fts5(content)")
            self._conn.execute("DROP TABLE temp._sierra_fts_probe")
            self._conn.executescript(FTS_SQL)
            self._rebuild_fts()
            self._fts_enabled = True
        except sqlite3.DatabaseError:
            self._drop_fts_triggers()
            self._fts_enabled = False

    def _drop_fts_triggers(self) -> None:
        for name in (
            "messages_fts_insert",
            "messages_fts_delete",
            "messages_fts_update",
        ):
            self._conn.execute(f"DROP TRIGGER IF EXISTS {name}")

    def _rebuild_fts(self) -> None:
        self._conn.execute("DELETE FROM messages_fts")
        self._conn.execute(
            """
            INSERT INTO messages_fts(rowid, content)
            SELECT id, COALESCE(content, '') || ' ' || COALESCE(tool_name, '') || ' ' || COALESCE(tool_calls, '')
            FROM messages
            """
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_session(
        self,
        session_id: str,
        *,
        title: str = "",
        model: str = "",
        cwd: str = "",
        created_at: float | None = None,
        updated_at: float | None = None,
    ) -> str:
        now = time.time()
        created = created_at or now
        updated = updated_at or now
        title = _clean_text(title, 120)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions(id, title, model, cwd, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = CASE WHEN excluded.title != '' THEN excluded.title ELSE sessions.title END,
                    model = CASE WHEN excluded.model != '' THEN excluded.model ELSE sessions.model END,
                    cwd = CASE WHEN excluded.cwd != '' THEN excluded.cwd ELSE sessions.cwd END,
                    updated_at = excluded.updated_at
                """,
                (session_id, title, model, cwd, created, updated),
            )
            self._conn.commit()
        return session_id

    def replace_session(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        title: str = "",
        model: str = "",
        cwd: str = "",
        usage: dict[str, Any] | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        usage = usage if isinstance(usage, dict) else {}
        title = title or _title_from_messages(messages)
        now = time.time()
        created = float(created_at or now)
        updated = float(updated_at or now)
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    """
                    INSERT INTO sessions(id, title, model, cwd, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = CASE WHEN excluded.title != '' THEN excluded.title ELSE sessions.title END,
                        model = CASE WHEN excluded.model != '' THEN excluded.model ELSE sessions.model END,
                        cwd = CASE WHEN excluded.cwd != '' THEN excluded.cwd ELSE sessions.cwd END,
                        updated_at = excluded.updated_at
                    """,
                    (session_id, _clean_text(title, 120), model, cwd, created, updated),
                )
                self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                message_count = 0
                tool_call_count = 0
                timestamp = created
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    role = str(message.get("role") or "unknown")
                    tool_calls = message.get("tool_calls")
                    tool_calls_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
                    tool_name = _tool_name_from_message(message)
                    self._conn.execute(
                        """
                        INSERT INTO messages(
                            session_id, role, content, tool_call_id, tool_calls,
                            tool_name, created_at, token_count, active
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            session_id,
                            role,
                            _encode_content(message.get("content")),
                            message.get("tool_call_id"),
                            tool_calls_json,
                            tool_name,
                            timestamp,
                            message.get("token_count"),
                        ),
                    )
                    message_count += 1
                    if tool_calls:
                        tool_call_count += len(tool_calls) if isinstance(tool_calls, list) else 1
                    timestamp += 0.000001
                self._conn.execute(
                    """
                    UPDATE sessions
                    SET message_count = ?, tool_call_count = ?, input_tokens = ?,
                        output_tokens = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        message_count,
                        tool_call_count,
                        int(usage.get("input", 0) or 0),
                        int(usage.get("output", 0) or 0),
                        updated,
                        session_id,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(100, int(limit or 20)))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, title, model, cwd, created_at, updated_at, message_count,
                       input_tokens, output_tokens
                FROM sessions
                WHERE message_count > 0
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT role, content, tool_call_id, tool_calls, tool_name, token_count
                FROM messages
                WHERE session_id = ? AND active = 1
                ORDER BY id
                """,
                (session_id,),
            ).fetchall()
        return [_row_to_message(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def search_messages(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        limit = max(1, min(50, int(limit or 10)))
        if self._fts_enabled:
            try:
                results = self._search_messages_fts(query, limit)
                if results:
                    return results
            except sqlite3.DatabaseError:
                pass
        return self._search_messages_like(query, limit)

    def _search_messages_fts(self, query: str, limit: int) -> list[dict[str, Any]]:
        fts_query = _fts_query(query)
        if not fts_query:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    m.id AS message_id,
                    m.session_id,
                    m.role,
                    snippet(messages_fts, 0, '[', ']', '...', 32) AS snippet,
                    m.content,
                    m.created_at,
                    s.title,
                    s.model,
                    s.cwd
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ? AND m.active = 1
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        return [_row_to_search_result(row, query) for row in rows]

    def _search_messages_like(self, query: str, limit: int) -> list[dict[str, Any]]:
        pattern = f"%{_escape_like(query)}%"
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    m.id AS message_id,
                    m.session_id,
                    m.role,
                    m.content,
                    m.created_at,
                    s.title,
                    s.model,
                    s.cwd
                FROM messages m
                JOIN sessions s ON s.id = m.session_id
                WHERE m.active = 1 AND m.content LIKE ? ESCAPE '\\'
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (pattern, limit),
            ).fetchall()
        return [_row_to_search_result(row, query) for row in rows]


def _encode_content(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    try:
        return CONTENT_JSON_PREFIX + json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


def _decode_content(content: Any) -> Any:
    if isinstance(content, str) and content.startswith(CONTENT_JSON_PREFIX):
        try:
            return json.loads(content[len(CONTENT_JSON_PREFIX):])
        except (TypeError, json.JSONDecodeError):
            return content
    return content


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    message = {
        "role": row["role"],
        "content": _decode_content(row["content"]),
    }
    if row["tool_call_id"]:
        message["tool_call_id"] = row["tool_call_id"]
    if row["tool_calls"]:
        try:
            message["tool_calls"] = json.loads(row["tool_calls"])
        except json.JSONDecodeError:
            message["tool_calls"] = []
    if row["tool_name"]:
        message["tool_name"] = row["tool_name"]
    if row["token_count"] is not None:
        message["token_count"] = row["token_count"]
    return message


def _row_to_search_result(row: sqlite3.Row, query: str) -> dict[str, Any]:
    content = _decode_content(row["content"])
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "snippet": row["snippet"] if "snippet" in row.keys() else _snippet(content, query),
        "content": content,
        "created_at": row["created_at"],
        "title": row["title"] or "",
        "model": row["model"] or "",
        "cwd": row["cwd"] or "",
    }


def _tool_name_from_message(message: dict[str, Any]) -> str:
    if message.get("tool_name"):
        return str(message["tool_name"])
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        function = (tool_calls[0] or {}).get("function") or {}
        return str(function.get("name") or "")
    return ""


def _title_from_messages(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            return _clean_text(str(message.get("content") or ""), 80)
    return ""


def _clean_text(text: str, max_chars: int) -> str:
    text = " ".join(str(text or "").split())
    return text[:max_chars]


def _fts_query(query: str) -> str:
    tokens = [token.strip() for token in query.split() if token.strip()]
    if not tokens:
        tokens = [query.strip()]
    quoted = []
    for token in tokens:
        token = token.replace('"', '""')
        if token:
            quoted.append(f'"{token}"')
    return " AND ".join(quoted)


def _escape_like(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _snippet(content: str, query: str, max_chars: int = 180) -> str:
    lower_content = content.lower()
    lower_query = query.lower()
    index = lower_content.find(lower_query)
    if index < 0:
        return content[:max_chars]
    start = max(0, index - 50)
    end = min(len(content), index + len(query) + 80)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"
