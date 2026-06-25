from abc import ABC, abstractmethod


class MemoryProvider(ABC):
    """Storage-independent contract for Sierra's long-term memory."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider's stable identifier."""

    @abstractmethod
    def get_prompt_context(self) -> str:
        """Return curated memory that should be injected into the prompt."""

    @abstractmethod
    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Return memories relevant to a query, ordered by relevance."""

    @abstractmethod
    def apply_operations(self, operations: list[dict]) -> dict:
        """Apply validated add, replace, and remove operations."""

    def sync_turn(
        self,
        user_message: str,
        assistant_message: str,
        metadata: dict | None = None,
    ) -> None:
        """Persist a completed conversation turn when the provider needs it."""

    def status(self) -> dict:
        """Return user-facing provider health and capacity information."""
        return {"name": self.name, "available": True}

    def delete(self, memory_id: int) -> dict:
        """Delete one provider-owned memory when supported."""
        return {
            "ok": False,
            "supported": False,
            "error": f"Provider '{self.name}' does not support deletion by ID",
        }

    def clear(self) -> dict:
        """Clear provider-owned memories in the active scope when supported."""
        return {
            "ok": False,
            "supported": False,
            "error": f"Provider '{self.name}' does not support clearing",
        }

    def close(self) -> None:
        """Release provider resources when needed."""
