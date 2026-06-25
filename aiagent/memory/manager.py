import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from .provider import MemoryProvider


logger = logging.getLogger(__name__)


class MemoryManager:
    """Coordinates one writable provider and optional recall providers."""

    def __init__(self, primary: MemoryProvider):
        self.primary = primary
        self._providers = [primary]
        self._sync_executor = None
        self._sync_lock = threading.Lock()
        self._closed = False

    @property
    def providers(self) -> tuple[MemoryProvider, ...]:
        return tuple(self._providers)

    def add_provider(self, provider: MemoryProvider) -> bool:
        if any(existing.name == provider.name for existing in self._providers):
            return False
        self._providers.append(provider)
        return True

    def get_prompt_context(self) -> str:
        blocks = []
        for provider in self._providers:
            try:
                context = provider.get_prompt_context()
            except Exception as exc:
                logger.warning(
                    "Memory provider '%s' failed to build prompt context: %s",
                    provider.name,
                    exc,
                )
                continue
            if context and context.strip():
                blocks.append(context.strip())
        return "\n\n".join(blocks)

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        if not query or limit <= 0:
            return []

        results_by_key = {}
        for provider in self._providers:
            try:
                recalled = provider.recall(query, limit=limit)
            except Exception as exc:
                logger.warning(
                    "Memory provider '%s' failed to recall: %s",
                    provider.name,
                    exc,
                )
                continue

            for item in recalled or []:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                key = (str(item.get("target", "")), content)
                candidate = {**item, "content": content, "provider": provider.name}
                existing = results_by_key.get(key)
                if existing is None or self._score(candidate) > self._score(existing):
                    results_by_key[key] = candidate

        results = list(results_by_key.values())
        results.sort(key=self._score, reverse=True)
        return results[:limit]

    def apply_operations(self, operations: list[dict]) -> dict:
        try:
            return self.primary.apply_operations(operations)
        except Exception as exc:
            logger.exception("Primary memory provider failed to apply operations")
            return {"changes": [], "errors": [str(exc)]}

    def flush(self) -> None:
        with self._sync_lock:
            if self._closed or self._sync_executor is None:
                return
            future = self._sync_executor.submit(lambda: None)
        future.result()

    def status(self) -> list[dict]:
        self.flush()
        statuses = []
        for provider in self._providers:
            try:
                statuses.append(provider.status())
            except Exception as exc:
                statuses.append({
                    "name": provider.name,
                    "available": False,
                    "error": str(exc),
                })
        return statuses

    def search(self, query: str, limit: int = 5) -> list[dict]:
        self.flush()
        return self.recall(query, limit=limit)

    def delete(self, memory_id: int, provider_name: str = "local_vector") -> dict:
        self.flush()
        provider = self.get_provider(provider_name)
        if provider is None:
            return {"ok": False, "error": f"Memory provider not found: {provider_name}"}
        try:
            return provider.delete(int(memory_id))
        except (TypeError, ValueError):
            return {"ok": False, "error": "记忆 ID 必须是整数"}
        except Exception as exc:
            logger.exception("Memory provider '%s' failed to delete", provider.name)
            return {"ok": False, "error": str(exc)}

    def clear(self, provider_name: str = "local_vector") -> dict:
        self.flush()
        provider = self.get_provider(provider_name)
        if provider is None:
            return {"ok": False, "error": f"Memory provider not found: {provider_name}"}
        try:
            return provider.clear()
        except Exception as exc:
            logger.exception("Memory provider '%s' failed to clear", provider.name)
            return {"ok": False, "error": str(exc)}

    def get_provider(self, name: str) -> MemoryProvider | None:
        return next((provider for provider in self._providers if provider.name == name), None)

    def sync_turn(
        self,
        user_message: str,
        assistant_message: str,
        metadata: dict | None = None,
    ):
        if not user_message or not assistant_message:
            return None

        with self._sync_lock:
            if self._closed:
                return None
            if self._sync_executor is None:
                self._sync_executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="sierra-memory",
                )
            return self._sync_executor.submit(
                self._sync_turn_now,
                user_message,
                assistant_message,
                dict(metadata or {}),
            )

    def _sync_turn_now(
        self,
        user_message: str,
        assistant_message: str,
        metadata: dict,
    ) -> None:

        for provider in self._providers:
            try:
                provider.sync_turn(
                    user_message,
                    assistant_message,
                    metadata=dict(metadata),
                )
            except Exception as exc:
                logger.warning(
                    "Memory provider '%s' failed to sync turn: %s",
                    provider.name,
                    exc,
                )

    def close(self) -> None:
        with self._sync_lock:
            if self._closed:
                return
            self._closed = True
            executor = self._sync_executor
            self._sync_executor = None
        if executor is not None:
            executor.shutdown(wait=True)

        for provider in reversed(self._providers):
            try:
                provider.close()
            except Exception as exc:
                logger.warning(
                    "Memory provider '%s' failed to close: %s",
                    provider.name,
                    exc,
                )

    @staticmethod
    def _score(item: dict) -> float:
        try:
            return float(item.get("score", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
