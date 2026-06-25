import os
import tempfile
import unittest

from aiagent.memory.vector_store import SQLiteVectorStore


class SQLiteVectorStoreTests(unittest.TestCase):
    def make_store(self, max_records=5000):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = SQLiteVectorStore(
            os.path.join(temp_dir.name, "memory.sqlite3"),
            max_records=max_records,
        )
        self.addCleanup(store.close)
        return store

    def test_search_orders_by_cosine_similarity(self):
        store = self.make_store()
        store.add("travel", [1.0, 0.0], {"workspace": "a"})
        store.add("code", [0.0, 1.0], {"workspace": "a"})

        results = store.search([0.9, 0.1], workspace="a", limit=2)

        self.assertEqual([item["content"] for item in results], ["travel", "code"])
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_workspace_filter_and_content_deduplication(self):
        store = self.make_store()

        self.assertTrue(store.add("same", [1.0, 0.0], {"workspace": "a"}))
        self.assertFalse(store.add("same", [1.0, 0.0], {"workspace": "a"}))
        self.assertTrue(store.add("same", [1.0, 0.0], {"workspace": "b"}))

        self.assertEqual(store.count(workspace="a"), 1)
        self.assertEqual(store.count(workspace="b"), 1)
        self.assertEqual(store.count(), 2)

    def test_prunes_oldest_records_at_limit(self):
        store = self.make_store(max_records=2)
        store.add("one", [1.0, 0.0])
        store.add("two", [0.8, 0.2])
        store.add("three", [0.0, 1.0])

        results = store.search([1.0, 0.0], limit=5)

        self.assertEqual(store.count(), 2)
        self.assertNotIn("one", [item["content"] for item in results])

    def test_delete_is_scoped_to_workspace(self):
        store = self.make_store()
        store.add("workspace a", [1.0, 0.0], {"workspace": "a"})
        store.add("workspace b", [0.0, 1.0], {"workspace": "b"})
        record_id = store.search([1.0, 0.0], workspace="a")[0]["id"]

        self.assertFalse(store.delete(record_id, workspace="b"))
        self.assertTrue(store.delete(record_id, workspace="a"))
        self.assertEqual(store.count(workspace="a"), 0)
        self.assertEqual(store.count(workspace="b"), 1)

    def test_clear_only_removes_requested_workspace(self):
        store = self.make_store()
        store.add("a one", [1.0, 0.0], {"workspace": "a"})
        store.add("a two", [0.8, 0.2], {"workspace": "a"})
        store.add("b one", [0.0, 1.0], {"workspace": "b"})

        deleted = store.clear(workspace="a")

        self.assertEqual(deleted, 2)
        self.assertEqual(store.count(workspace="a"), 0)
        self.assertEqual(store.count(workspace="b"), 1)


if __name__ == "__main__":
    unittest.main()
