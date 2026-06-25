from .provider import MemoryProvider


class MarkdownMemoryProvider(MemoryProvider):
    """Curated memory backed by Sierra's MEMORY.md and USER.md files."""

    def __init__(self, store):
        self.store = store

    @property
    def name(self) -> str:
        return "markdown"

    def configure(self, max_memory_chars=None, max_user_chars=None):
        self.store.configure(
            max_memory_chars=max_memory_chars,
            max_user_chars=max_user_chars,
        )
        return self

    def get_prompt_context(self) -> str:
        return self.store.get_all_for_prompt()

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        # The curated Markdown store is small enough to inject in full.
        # Semantic retrieval belongs in a separate vector provider.
        return []

    def status(self) -> dict:
        return {
            "name": self.name,
            "available": True,
            "memory_entries": len(self.store.get_entries("memory")),
            "user_entries": len(self.store.get_entries("user")),
            "storage": "MEMORY.md / USER.md",
        }

    def apply_operations(self, operations: list[dict]) -> dict:
        changes = []
        errors = []

        for operation in operations[:5]:
            if not isinstance(operation, dict):
                errors.append("记忆操作必须是对象")
                continue

            action = str(operation.get("action", "")).strip().lower()
            target = str(operation.get("target", "")).strip().lower()
            old_text = str(operation.get("old_text", "")).strip()
            content = " ".join(str(operation.get("content", "")).split())

            if action not in ("add", "replace", "remove"):
                errors.append(f"未知记忆操作: {action or 'empty'}")
                continue
            if target not in ("memory", "user"):
                errors.append(f"未知记忆类型: {target or 'empty'}")
                continue
            if content and len(content) > 200:
                errors.append("自动记忆内容超过 200 字符，已拒绝")
                continue

            if action == "add":
                result = self.store.add(content, target=target)
                changed = result.get("ok") and not result.get("duplicate")
            elif action == "replace":
                result = self.store.replace(old_text, content, target=target)
                changed = result.get("ok") and result.get("changed", False)
            else:
                result = self.store.remove(
                    old_text,
                    target=target,
                    require_unique=True,
                )
                changed = result.get("ok") and result.get("changed", False)

            if not result.get("ok"):
                errors.append(result.get("error", "记忆操作失败"))
                continue
            if changed:
                changes.append({
                    "action": action,
                    "target": target,
                    "old_text": old_text,
                    "content": content,
                })

        return {"changes": changes, "errors": errors}
