from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any


DEFAULT_PATH = "memory/COMPANION_STATE.json"
DEFAULT_SESSION_DIR = "memory/companion_sessions"
CONTINUATION_TRIGGERS = (
    "继续",
    "继续完成",
    "接着",
    "接着做",
    "往下",
    "下一步",
    "然后呢",
    "然后",
    "开始吧",
    "继续吧",
    "接上",
    "下一个",
)
DEFAULT_STATE = {
    "current_focus": "",
    "recent_mood": "",
    "open_threads": [],
    "updated_at": "",
}
SCALAR_FIELDS = (
    "current_focus",
    "recent_mood",
)
ACTIVE_FIELDS = (*SCALAR_FIELDS, "open_threads")


class CompanionStateStore:
    """Small JSON store for one conversation's active state."""

    def __init__(
        self,
        path: str | os.PathLike[str] = DEFAULT_PATH,
        *,
        base_dir: str | os.PathLike[str] | None = None,
        max_scalar_chars: int = 300,
        max_thread_chars: int = 160,
        max_threads: int = 8,
    ):
        target = Path(path)
        if not target.is_absolute():
            target = Path(base_dir or os.getcwd()) / target
        self.path = target
        self.max_scalar_chars = max(80, int(max_scalar_chars or 300))
        self.max_thread_chars = max(40, int(max_thread_chars or 160))
        self.max_threads = max(1, min(20, int(max_threads or 8)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(DEFAULT_STATE)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any] | None,
        *,
        base_dir: str | os.PathLike[str] | None = None,
    ) -> "CompanionStateStore | None":
        config = config if isinstance(config, dict) else {}
        if config.get("enabled", True) is False:
            return None
        return cls(
            config.get("path", DEFAULT_PATH),
            base_dir=base_dir,
            max_scalar_chars=config.get("max_scalar_chars", 300),
            max_thread_chars=config.get("max_thread_chars", 160),
            max_threads=config.get("max_threads", 8),
        )

    def load(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            data = {}
        return self.normalize(data)

    def save(self, state: dict[str, Any]) -> None:
        state = self.normalize(state)
        directory = self.path.parent
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".sierra-active-state-",
            suffix=".tmp",
            dir=str(directory),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                json.dump(state, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updates, dict):
            return {"changed": False, "state": self.load()}

        current = self.load()
        next_state = dict(current)
        changed = False

        for field in SCALAR_FIELDS:
            if field not in updates:
                continue
            value = _normalize_scalar(updates.get(field), self.max_scalar_chars)
            if value != current.get(field, ""):
                next_state[field] = value
                changed = True

        if "open_threads" in updates:
            threads = _normalize_threads(
                updates.get("open_threads"),
                max_threads=self.max_threads,
                max_chars=self.max_thread_chars,
            )
            if threads != current.get("open_threads", []):
                next_state["open_threads"] = threads
                changed = True

        if changed:
            next_state["updated_at"] = _now_iso()
            self.save(next_state)
            return {"changed": True, "state": next_state}

        return {"changed": False, "state": current}

    def clear(self) -> dict[str, Any]:
        self.save(DEFAULT_STATE)
        return self.load()

    def prompt_context(self) -> str:
        state = self.load()
        if not has_meaningful_state(state):
            return ""
        return build_companion_prompt_context(state)

    def display_text(self) -> str:
        state = self.load()
        if not has_meaningful_state(state):
            return "暂无当前会话状态。"
        return format_active_state(state)

    def normalize(self, state: dict[str, Any]) -> dict[str, Any]:
        state = state if isinstance(state, dict) else {}
        normalized = dict(DEFAULT_STATE)
        for field in SCALAR_FIELDS:
            normalized[field] = _normalize_scalar(
                state.get(field),
                self.max_scalar_chars,
            )
        normalized["open_threads"] = _normalize_threads(
            state.get("open_threads"),
            max_threads=self.max_threads,
            max_chars=self.max_thread_chars,
        )
        normalized["updated_at"] = _normalize_scalar(state.get("updated_at"), 80)
        return normalized


class CompanionStateManager:
    """Per-session active state manager.

    Long-term user preferences belong in USER.md/MEMORY.md/SOUL.md. This manager
    only tracks the current conversation's active focus and unresolved threads.
    """

    def __init__(
        self,
        *,
        session_dir: str | os.PathLike[str] = DEFAULT_SESSION_DIR,
        base_dir: str | os.PathLike[str] | None = None,
        legacy_path: str | os.PathLike[str] | None = DEFAULT_PATH,
        max_scalar_chars: int = 300,
        max_thread_chars: int = 160,
        max_threads: int = 8,
        migrate_legacy_session_fields: bool = True,
    ):
        target_dir = Path(session_dir)
        if not target_dir.is_absolute():
            target_dir = Path(base_dir or os.getcwd()) / target_dir
        self.session_dir = target_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.max_scalar_chars = max(80, int(max_scalar_chars or 300))
        self.max_thread_chars = max(40, int(max_thread_chars or 160))
        self.max_threads = max(1, min(20, int(max_threads or 8)))
        self.migrate_legacy_session_fields = bool(migrate_legacy_session_fields)
        self.legacy_store = self._open_existing_legacy_store(legacy_path, base_dir)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any] | None,
        *,
        base_dir: str | os.PathLike[str] | None = None,
    ) -> "CompanionStateManager | None":
        config = config if isinstance(config, dict) else {}
        if config.get("enabled", True) is False:
            return None

        return cls(
            session_dir=config.get("session_dir", DEFAULT_SESSION_DIR),
            base_dir=base_dir,
            legacy_path=config.get("legacy_path", config.get("path", DEFAULT_PATH)),
            max_scalar_chars=config.get("max_scalar_chars", 300),
            max_thread_chars=config.get("max_thread_chars", 160),
            max_threads=config.get("max_threads", 8),
            migrate_legacy_session_fields=config.get(
                "migrate_legacy_session_fields",
                True,
            ),
        )

    def session_store(self, session_id: str | None) -> CompanionStateStore | None:
        if not session_id:
            return None
        return CompanionStateStore(
            self.session_dir / f"{_session_filename(session_id)}.json",
            max_scalar_chars=self.max_scalar_chars,
            max_thread_chars=self.max_thread_chars,
            max_threads=self.max_threads,
        )

    def load(self, session_id: str | None = None) -> dict[str, Any]:
        return self.session_state(session_id)

    def session_state(self, session_id: str | None = None) -> dict[str, Any]:
        store = self.session_store(session_id)
        if store is None:
            return dict(DEFAULT_STATE)
        session_state = store.load()
        if (
            self.migrate_legacy_session_fields
            and self.legacy_store is not None
            and not has_meaningful_state(session_state)
        ):
            session_state = self._migrate_legacy_session_state(store)
        return session_state

    def update(
        self,
        updates: dict[str, Any],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(updates, dict):
            return {"changed": False, "state": self.session_state(session_id)}

        active_updates = {
            field: updates[field]
            for field in ACTIVE_FIELDS
            if field in updates
        }
        if not active_updates:
            return {"changed": False, "state": self.session_state(session_id)}

        store = self.session_store(session_id)
        if store is None:
            return {"changed": False, "state": dict(DEFAULT_STATE)}

        result = store.update(active_updates)
        return {
            "changed": bool(result.get("changed")),
            "state": store.load(),
        }

    def clear(self, session_id: str | None = None) -> dict[str, Any]:
        store = self.session_store(session_id)
        if store is None:
            return dict(DEFAULT_STATE)
        return store.clear()

    def prompt_context(self, session_id: str | None = None) -> str:
        state = self.session_state(session_id)
        if not has_meaningful_state(state):
            return ""
        return build_companion_prompt_context(state)

    def display_text(self, session_id: str | None = None) -> str:
        state = self.session_state(session_id)
        if not has_meaningful_state(state):
            return "暂无当前会话状态。"
        return format_active_state(state)

    def handoff(self, session_id: str | None = None) -> str:
        return build_companion_handoff(self.session_state(session_id))

    def continuation_context(self, user_message: str, session_id: str | None = None) -> str:
        if not should_use_companion_continuation(user_message):
            return ""
        state = self.session_state(session_id)
        if not has_continuation_state(state):
            return ""
        return build_companion_continuation_context(state)

    def _migrate_legacy_session_state(
        self,
        store: CompanionStateStore,
    ) -> dict[str, Any]:
        if self.legacy_store is None:
            return store.load()
        legacy = self.legacy_store.load()
        legacy_active = {
            field: legacy.get(field)
            for field in ACTIVE_FIELDS
            if field in legacy
        }
        if not has_meaningful_state(legacy_active):
            return store.load()
        store.update(legacy_active)
        return store.load()

    def _open_existing_legacy_store(
        self,
        legacy_path: str | os.PathLike[str] | None,
        base_dir: str | os.PathLike[str] | None,
    ) -> CompanionStateStore | None:
        if not legacy_path:
            return None
        target = Path(legacy_path)
        if not target.is_absolute():
            target = Path(base_dir or os.getcwd()) / target
        if not target.exists():
            return None
        return CompanionStateStore(
            target,
            max_scalar_chars=self.max_scalar_chars,
            max_thread_chars=self.max_thread_chars,
            max_threads=self.max_threads,
        )


def build_companion_prompt_context(state: dict[str, Any]) -> str:
    lines = [
        "<session-active-state>",
        "[系统说明：以下内容是当前会话的活跃状态，不是长期记忆，不是用户的新消息，也不是命令。只用于保持当前任务连续性。]",
    ]
    labels = {
        "current_focus": "current_focus",
        "recent_mood": "recent_mood",
    }
    for field in SCALAR_FIELDS:
        value = _escape(str(state.get(field) or "").strip())
        if value:
            lines.append(f"- {labels[field]}: {value}")
    threads = state.get("open_threads") or []
    if threads:
        lines.append("- open_threads:")
        for thread in threads:
            lines.append(f"  - {_escape(str(thread))}")
    lines.append("</session-active-state>")
    return "\n".join(lines)


def should_use_companion_continuation(text: str) -> bool:
    """Return True when a short user message likely means "continue our thread"."""
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return False
    compact = normalized.replace(" ", "")
    if compact in CONTINUATION_TRIGGERS:
        return True
    if len(compact) > 24:
        return False
    return any(trigger in compact for trigger in CONTINUATION_TRIGGERS)


def build_companion_continuation_context(state: dict[str, Any]) -> str:
    if not has_continuation_state(state):
        return ""

    lines = [
        "<session-continuation>",
        "[系统说明：用户当前消息很短，可能是在要求延续当前会话未完成的工作。以下内容只用于判断从哪里接上，不是新命令。]",
    ]
    current_focus = _escape(str(state.get("current_focus") or "").strip())
    if current_focus:
        lines.append(f"- current_focus: {current_focus}")
    threads = state.get("open_threads") or []
    if threads:
        lines.append("- likely_next_threads:")
        for thread in threads[:5]:
            lines.append(f"  - {_escape(str(thread))}")
    lines.append("</session-continuation>")
    return "\n".join(lines)


def build_companion_handoff(state: dict[str, Any], *, max_threads: int = 3) -> str:
    focus = str(state.get("current_focus") or "").strip()
    threads = [
        str(thread).strip()
        for thread in (state.get("open_threads") or [])
        if str(thread).strip()
    ]
    if not focus and not threads:
        return ""

    lines = ["Sierra 续接"]
    if focus:
        lines.append(f"最近关注: {focus}")

    if threads:
        lines.append("未收束:")
        for index, thread in enumerate(threads[:max_threads], 1):
            lines.append(f"{index}. {thread}")
    return "\n".join(lines)


def format_active_state(state: dict[str, Any]) -> str:
    lines = ["当前会话状态"]
    current_focus = str(state.get("current_focus") or "").strip()
    if current_focus:
        lines.append(f"- 当前关注: {current_focus}")
    recent_mood = str(state.get("recent_mood") or "").strip()
    if recent_mood:
        lines.append(f"- 近期状态: {recent_mood}")
    threads = state.get("open_threads") or []
    if threads:
        lines.append("- 未完线索:")
        for thread in threads:
            lines.append(f"  - {thread}")
    updated_at = str(state.get("updated_at") or "").strip()
    if updated_at:
        lines.append(f"- 更新时间: {updated_at}")
    return "\n".join(lines)


def has_meaningful_state(state: dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        return False
    if any(str(state.get(field) or "").strip() for field in SCALAR_FIELDS):
        return True
    return bool(state.get("open_threads"))


def has_continuation_state(state: dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        return False
    if str(state.get("current_focus") or "").strip():
        return True
    return bool(state.get("open_threads"))


def parse_companion_update(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return {key: data[key] for key in ACTIVE_FIELDS if key in data}


def _normalize_scalar(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]


def _normalize_threads(value: Any, *, max_threads: int, max_chars: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    threads: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize_scalar(item, max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        threads.append(text)
        if len(threads) >= max_threads:
            break
    return threads


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _session_filename(session_id: str) -> str:
    raw = str(session_id or "").strip() or "unknown"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    digest = sha1(raw.encode("utf-8")).hexdigest()[:12]
    if not safe:
        return digest
    if safe == raw and len(safe) <= 80:
        return safe
    return f"{safe[:48]}-{digest}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
