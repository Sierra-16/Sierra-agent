import os
import tempfile
import unittest

from aiagent.memory.embedding import EmbeddingClient
from aiagent.memory.local_vector_provider import LocalVectorProvider
from aiagent.memory.vector_store import SQLiteVectorStore


class KeywordEmbeddingClient(EmbeddingClient):
    def __init__(self):
        self.calls = []
        self.closed = False

    def embed(self, texts):
        vectors = []
        for text in texts:
            self.calls.append(text)
            if any(word in text for word in ("桂林", "旅行", "景点")):
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors

    def close(self):
        self.closed = True


class LocalVectorProviderTests(unittest.TestCase):
    def make_provider(self, workspace="workspace-a"):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = SQLiteVectorStore(os.path.join(temp_dir.name, "memory.sqlite3"))
        embedding = KeywordEmbeddingClient()
        provider = LocalVectorProvider(
            embedding_client=embedding,
            store=store,
            workspace=workspace,
            min_score=0.5,
        )
        self.addCleanup(provider.close)
        return provider, store, embedding

    def test_empty_store_skips_query_embedding(self):
        provider, _, embedding = self.make_provider()

        self.assertEqual(provider.recall("桂林怎么玩"), [])
        self.assertEqual(embedding.calls, [])

    def test_sync_and_semantic_recall(self):
        provider, store, embedding = self.make_provider()
        provider.sync_turn(
            "帮我规划桂林七日旅行",
            "可以安排漓江和阳朔",
            {"conversation_id": "c1", "model": "test"},
        )
        provider.sync_turn(
            "Python 项目如何测试",
            "可以使用 unittest",
            {"conversation_id": "c2", "model": "test"},
        )

        recalled = provider.recall("之前推荐了哪些景点", limit=1)

        self.assertEqual(store.count(workspace=os.path.abspath("workspace-a")), 2)
        self.assertEqual(len(recalled), 1)
        self.assertIn("桂林", recalled[0]["content"])
        self.assertEqual(recalled[0]["conversation_id"], "c1")
        self.assertEqual(len(embedding.calls), 3)

    def test_sync_redacts_secrets_and_deduplicates_turns(self):
        provider, store, embedding = self.make_provider()
        user_message = "API key=secret-value-123456"
        assistant_message = "已收到 sk-abcdefghijk12345"

        provider.sync_turn(user_message, assistant_message)
        provider.sync_turn(user_message, assistant_message)
        records = store.search(
            [0.0, 1.0],
            workspace=os.path.abspath("workspace-a"),
            limit=5,
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(len(embedding.calls), 1)
        self.assertNotIn("secret-value", records[0]["content"])
        self.assertNotIn("abcdefghijk", records[0]["content"])

    def test_status_delete_and_clear_use_current_workspace(self):
        provider, store, _ = self.make_provider()
        provider.sync_turn("桂林旅行", "去阳朔")
        provider.sync_turn("Python 测试", "使用 unittest")
        record = store.search(
            [1.0, 0.0],
            workspace=os.path.abspath("workspace-a"),
            limit=1,
        )[0]

        status = provider.status()
        deleted = provider.delete(record["id"])
        cleared = provider.clear()

        self.assertEqual(status["records"], 2)
        self.assertTrue(deleted["ok"])
        self.assertEqual(cleared["deleted"], 1)
        self.assertEqual(store.count(workspace=os.path.abspath("workspace-a")), 0)


if __name__ == "__main__":
    unittest.main()
