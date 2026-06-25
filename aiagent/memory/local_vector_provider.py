import os

from ..safety import sanitize_text
from .embedding import OpenAICompatibleEmbeddingClient
from .provider import MemoryProvider
from .vector_store import SQLiteVectorStore


class LocalVectorProvider(MemoryProvider):
    """Semantic conversation memory using remote embeddings and local SQLite."""

    def __init__(
        self,
        embedding_client,
        store: SQLiteVectorStore,
        workspace: str,
        scope: str = "workspace",
        min_score: float = 0.35,
        max_turn_chars: int = 6000,
        min_turn_chars: int = 12,
    ):
        if scope not in ("workspace", "global"):
            raise ValueError("Vector memory scope must be 'workspace' or 'global'")
        self.embedding_client = embedding_client
        self.store = store
        self.workspace = os.path.abspath(workspace or ".")
        self.scope = scope
        self.min_score = float(min_score)
        self.max_turn_chars = max(500, int(max_turn_chars))
        self.min_turn_chars = max(1, int(min_turn_chars))

    @property
    def name(self) -> str:
        return "local_vector"

    @classmethod
    def from_config(cls, config: dict, base_dir: str, workspace: str):
        embedding_config = config.get("embedding", {})
        if embedding_config.get("provider", "openai_compatible") != "openai_compatible":
            raise ValueError("Only openai_compatible embeddings are currently supported")

        path = config.get("path", "memory/vector_memory.sqlite3")
        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        embedding_client = OpenAICompatibleEmbeddingClient(
            base_url=embedding_config.get("base_url", ""),
            api_key=embedding_config.get("api_key", ""),
            model=embedding_config.get("model", ""),
            dimensions=embedding_config.get("dimensions"),
            batch_size=embedding_config.get("batch_size", 10),
            timeout=embedding_config.get("timeout", 20.0),
        )
        store = SQLiteVectorStore(
            path,
            max_records=config.get("max_records", 5000),
        )
        return cls(
            embedding_client=embedding_client,
            store=store,
            workspace=workspace,
            scope=config.get("scope", "workspace"),
            min_score=config.get("recall_min_score", 0.35),
            max_turn_chars=config.get("max_turn_chars", 6000),
            min_turn_chars=config.get("min_turn_chars", 12),
        )

    def get_prompt_context(self) -> str:
        return ""

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        workspace_filter = self.workspace if self.scope == "workspace" else None
        if self.store.count(workspace=workspace_filter) == 0:
            return []

        query = sanitize_text(str(query or "").strip(), max_length=2000)
        if not query:
            return []
        query_vector = self.embedding_client.embed_one(query)
        records = self.store.search(
            query_vector,
            limit=limit,
            workspace=workspace_filter,
            min_score=self.min_score,
        )
        return [
            {
                "id": record["id"],
                "content": record["content"],
                "target": "history",
                "score": record["score"],
                "conversation_id": record["conversation_id"],
                "created_at": record["created_at"],
            }
            for record in records
        ]

    def apply_operations(self, operations: list[dict]) -> dict:
        return {"changes": [], "errors": []}

    def status(self) -> dict:
        return {
            "name": self.name,
            "available": True,
            "records": self.store.count(workspace=self.workspace),
            "total_records": self.store.count(),
            "scope": self.scope,
            "workspace": self.workspace,
            "storage": self.store.path,
            "embedding_model": getattr(self.embedding_client, "model", "unknown"),
        }

    def delete(self, memory_id: int) -> dict:
        deleted = self.store.delete(memory_id, workspace=self.workspace)
        return {
            "ok": deleted,
            "supported": True,
            "deleted": 1 if deleted else 0,
            "id": int(memory_id),
            "provider": self.name,
            "error": "" if deleted else "当前工作区没有找到该记忆 ID",
        }

    def clear(self) -> dict:
        deleted = self.store.clear(workspace=self.workspace)
        return {
            "ok": True,
            "supported": True,
            "deleted": deleted,
            "provider": self.name,
        }

    def sync_turn(
        self,
        user_message: str,
        assistant_message: str,
        metadata: dict | None = None,
    ) -> None:
        content = sanitize_text(
            f"用户: {str(user_message or '').strip()}\n"
            f"Sierra: {str(assistant_message or '').strip()}",
            max_length=self.max_turn_chars,
        )
        if len(content) < self.min_turn_chars:
            return

        record_metadata = dict(metadata or {})
        record_metadata["workspace"] = self.workspace
        if self.store.contains(content, workspace=self.workspace):
            return
        vector = self.embedding_client.embed_one(content)
        self.store.add(content, vector, record_metadata)

    def close(self) -> None:
        try:
            self.store.close()
        finally:
            self.embedding_client.close()
