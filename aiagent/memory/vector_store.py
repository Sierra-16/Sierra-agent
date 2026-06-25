import hashlib
import math
import os
import sqlite3
import struct
import threading
from datetime import datetime, timezone


class SQLiteVectorStore:
    """Small local vector store backed by SQLite and exact cosine search."""

    def __init__(self, path: str, max_records: int = 5000):
        self.path = os.path.abspath(path)
        self.max_records = max(1, int(max_records))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    dimensions INTEGER NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    workspace TEXT NOT NULL DEFAULT '',
                    conversation_id TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_vector_memories_workspace "
                "ON vector_memories(workspace)"
            )

    def add(self, content: str, vector: list[float], metadata: dict | None = None) -> bool:
        content = str(content or "").strip()
        values = self._validate_vector(vector)
        if not content:
            raise ValueError("Vector memory content cannot be empty")

        metadata = metadata or {}
        workspace = str(metadata.get("workspace") or "")
        content_hash = self._content_hash(content, workspace)
        packed = struct.pack(f"<{len(values)}f", *values)
        created_at = datetime.now(timezone.utc).isoformat()

        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO vector_memories (
                    content, embedding, dimensions, content_hash, workspace,
                    conversation_id, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content,
                    packed,
                    len(values),
                    content_hash,
                    workspace,
                    str(metadata.get("conversation_id") or ""),
                    str(metadata.get("model") or ""),
                    created_at,
                ),
            )
            inserted = cursor.rowcount > 0
            if inserted:
                self._connection.execute(
                    """
                    DELETE FROM vector_memories
                    WHERE id NOT IN (
                        SELECT id FROM vector_memories
                        ORDER BY id DESC
                        LIMIT ?
                    )
                    """,
                    (self.max_records,),
                )
        return inserted

    def contains(self, content: str, workspace: str = "") -> bool:
        content_hash = self._content_hash(str(content or "").strip(), str(workspace))
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM vector_memories WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
        return row is not None

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        workspace: str | None = None,
        min_score: float = -1.0,
    ) -> list[dict]:
        query = self._validate_vector(query_vector)
        limit = max(0, int(limit))
        if limit == 0:
            return []

        sql = (
            "SELECT id, content, embedding, dimensions, workspace, "
            "conversation_id, model, created_at FROM vector_memories"
        )
        params = []
        if workspace is not None:
            sql += " WHERE workspace = ?"
            params.append(str(workspace))

        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()

        results = []
        for row in rows:
            if row["dimensions"] != len(query):
                continue
            vector = list(struct.unpack(
                f"<{row['dimensions']}f",
                row["embedding"],
            ))
            score = self._cosine_similarity(query, vector)
            if score < min_score:
                continue
            results.append({
                "id": row["id"],
                "content": row["content"],
                "score": score,
                "workspace": row["workspace"],
                "conversation_id": row["conversation_id"],
                "model": row["model"],
                "created_at": row["created_at"],
            })

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def count(self, workspace: str | None = None) -> int:
        with self._lock:
            if workspace is None:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS count FROM vector_memories"
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS count FROM vector_memories WHERE workspace = ?",
                    (str(workspace),),
                ).fetchone()
        return int(row["count"])

    def delete(self, record_id: int, workspace: str | None = None) -> bool:
        record_id = int(record_id)
        sql = "DELETE FROM vector_memories WHERE id = ?"
        params = [record_id]
        if workspace is not None:
            sql += " AND workspace = ?"
            params.append(str(workspace))
        with self._lock, self._connection:
            cursor = self._connection.execute(sql, params)
        return cursor.rowcount > 0

    def clear(self, workspace: str | None = None) -> int:
        sql = "DELETE FROM vector_memories"
        params = []
        if workspace is not None:
            sql += " WHERE workspace = ?"
            params.append(str(workspace))
        with self._lock, self._connection:
            cursor = self._connection.execute(sql, params)
        return max(0, cursor.rowcount)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _content_hash(content: str, workspace: str) -> str:
        return hashlib.sha256(
            f"{workspace}\0{content}".encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_vector(vector) -> list[float]:
        values = [float(value) for value in vector]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("Vector must contain finite numeric values")
        if math.sqrt(sum(value * value for value in values)) == 0:
            raise ValueError("Vector magnitude cannot be zero")
        return values

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)
