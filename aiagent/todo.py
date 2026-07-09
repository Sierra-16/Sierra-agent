from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


VALID_TODO_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
MAX_TODO_CONTENT_CHARS = 4000
MAX_TODO_ITEMS = 256
TRUNCATION_MARKER = "...[truncated]"


@dataclass(frozen=True)
class TodoSummary:
    total: int
    pending: int
    in_progress: int
    completed: int
    cancelled: int

    def as_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "pending": self.pending,
            "in_progress": self.in_progress,
            "completed": self.completed,
            "cancelled": self.cancelled,
        }


class TodoStore:
    """Session-scoped work list used by the model to keep long tasks focused."""

    def __init__(self):
        self._items: list[dict[str, str]] = []

    def read(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._items]

    def clear(self) -> None:
        self._items = []

    def write(
        self,
        todos: list[dict[str, Any]],
        *,
        merge: bool = False,
    ) -> list[dict[str, str]]:
        if not isinstance(todos, list):
            raise ValueError("todos must be a list")

        if not merge:
            self._items = [self._validate(item) for item in self._dedupe(todos)]
        else:
            self._merge(todos)

        if len(self._items) > MAX_TODO_ITEMS:
            self._items = self._items[:MAX_TODO_ITEMS]
        return self.read()

    def summary(self) -> TodoSummary:
        counts = {status: 0 for status in VALID_TODO_STATUSES}
        for item in self._items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return TodoSummary(
            total=len(self._items),
            pending=counts["pending"],
            in_progress=counts["in_progress"],
            completed=counts["completed"],
            cancelled=counts["cancelled"],
        )

    def format_for_prompt(self) -> str:
        active = [
            item
            for item in self._items
            if item["status"] in {"pending", "in_progress"}
        ]
        if not active:
            return ""

        markers = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
            "cancelled": "[~]",
        }
        lines = [
            "# Active Work List",
            "The model-maintained todo list below is for the current Sierra session only.",
            "Use it to continue multi-step work without asking the user to restate progress.",
        ]
        for item in active:
            marker = markers.get(item["status"], "[?]")
            lines.append(
                f"- {marker} {item['id']}: {item['content']} ({item['status']})"
            )
        return "\n".join(lines)

    def tool(self, todos: list[dict[str, Any]] | None = None, merge: bool = False) -> str:
        if todos is not None:
            items = self.write(todos, merge=bool(merge))
        else:
            items = self.read()
        return json.dumps(
            {
                "ok": True,
                "todos": items,
                "summary": self.summary().as_dict(),
            },
            ensure_ascii=False,
        )

    def _merge(self, todos: list[dict[str, Any]]) -> None:
        existing = {item["id"]: dict(item) for item in self._items}
        for raw in self._dedupe(todos):
            item_id = str(raw.get("id", "")).strip()
            if not item_id:
                continue

            if item_id not in existing:
                validated = self._validate(raw)
                existing[validated["id"]] = validated
                self._items.append(validated)
                continue

            current = existing[item_id]
            if "content" in raw and str(raw.get("content") or "").strip():
                current["content"] = self._cap_content(str(raw["content"]).strip())
            if "status" in raw and str(raw.get("status") or "").strip():
                status = str(raw["status"]).strip().lower()
                if status in VALID_TODO_STATUSES:
                    current["status"] = status
            existing[item_id] = current

        rebuilt: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in self._items:
            current = existing.get(item["id"], item)
            if current["id"] in seen:
                continue
            rebuilt.append(current)
            seen.add(current["id"])
        self._items = rebuilt

    @classmethod
    def _validate(cls, item: dict[str, Any]) -> dict[str, str]:
        item_id = str(item.get("id", "")).strip() or "?"
        content = str(item.get("content", "")).strip() or "(no description)"
        status = str(item.get("status", "pending")).strip().lower()
        if status not in VALID_TODO_STATUSES:
            status = "pending"
        return {
            "id": item_id,
            "content": cls._cap_content(content),
            "status": status,
        }

    @staticmethod
    def _cap_content(content: str) -> str:
        if len(content) <= MAX_TODO_CONTENT_CHARS:
            return content
        keep = max(0, MAX_TODO_CONTENT_CHARS - len(TRUNCATION_MARKER))
        return content[:keep] + TRUNCATION_MARKER

    @staticmethod
    def _dedupe(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last_index: dict[str, int] = {}
        for index, item in enumerate(todos):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "")).strip() or "?"
            last_index[item_id] = index
        return [
            todos[index]
            for index in sorted(last_index.values())
            if isinstance(todos[index], dict)
        ]
