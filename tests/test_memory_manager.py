import unittest

from aiagent.memory import MemoryManager, MemoryProvider


class FakeProvider(MemoryProvider):
    def __init__(self, name, context="", recalled=None):
        self._name = name
        self.context = context
        self.recalled = recalled or []
        self.applied = []
        self.synced = []
        self.deleted = []
        self.clear_calls = 0
        self.closed = False

    @property
    def name(self):
        return self._name

    def get_prompt_context(self):
        return self.context

    def recall(self, query, limit=5):
        return self.recalled[:limit]

    def apply_operations(self, operations):
        self.applied.extend(operations)
        return {"changes": list(operations), "errors": []}

    def sync_turn(self, user_message, assistant_message, metadata=None):
        self.synced.append((user_message, assistant_message, metadata))

    def status(self):
        return {"name": self.name, "available": True}

    def delete(self, memory_id):
        self.deleted.append(memory_id)
        return {"ok": True, "deleted": 1}

    def clear(self):
        self.clear_calls += 1
        return {"ok": True, "deleted": 2}

    def close(self):
        self.closed = True


class BrokenProvider(FakeProvider):
    def get_prompt_context(self):
        raise RuntimeError("context failed")

    def recall(self, query, limit=5):
        raise RuntimeError("recall failed")

    def sync_turn(self, user_message, assistant_message, metadata=None):
        raise RuntimeError("sync failed")


class MemoryManagerTests(unittest.TestCase):
    def test_combines_context_from_registered_providers(self):
        primary = FakeProvider("markdown", context="curated")
        vector = FakeProvider("vector", context="vector status")
        manager = MemoryManager(primary)

        self.assertTrue(manager.add_provider(vector))
        self.assertFalse(manager.add_provider(FakeProvider("vector")))
        self.assertEqual(manager.get_prompt_context(), "curated\n\nvector status")

    def test_recall_deduplicates_and_sorts_across_providers(self):
        primary = FakeProvider("markdown", recalled=[
            {"content": "shared", "target": "memory", "score": 0.2},
        ])
        vector = FakeProvider("vector", recalled=[
            {"content": "high", "target": "memory", "score": 0.9},
            {"content": "shared", "target": "memory", "score": 0.8},
        ])
        manager = MemoryManager(primary)
        manager.add_provider(vector)

        recalled = manager.recall("query", limit=5)

        self.assertEqual([item["content"] for item in recalled], ["high", "shared"])
        self.assertEqual(recalled[0]["provider"], "vector")
        self.assertEqual(recalled[1]["provider"], "vector")
        self.assertEqual(recalled[1]["score"], 0.8)

    def test_operations_are_routed_only_to_primary_provider(self):
        primary = FakeProvider("markdown")
        vector = FakeProvider("vector")
        manager = MemoryManager(primary)
        manager.add_provider(vector)
        operations = [{"action": "add", "target": "memory", "content": "fact"}]

        result = manager.apply_operations(operations)

        self.assertEqual(result["errors"], [])
        self.assertEqual(primary.applied, operations)
        self.assertEqual(vector.applied, [])

    def test_broken_secondary_provider_does_not_block_primary(self):
        primary = FakeProvider("markdown", context="curated")
        manager = MemoryManager(primary)
        manager.add_provider(BrokenProvider("broken"))

        self.assertEqual(manager.get_prompt_context(), "curated")
        self.assertEqual(manager.recall("query"), [])
        manager.sync_turn("user", "assistant", {"session": "demo"}).result()
        self.assertEqual(len(primary.synced), 1)

    def test_sync_turn_is_sent_to_every_provider(self):
        primary = FakeProvider("markdown")
        vector = FakeProvider("vector")
        manager = MemoryManager(primary)
        manager.add_provider(vector)

        manager.sync_turn("question", "answer", {"conversation_id": "c1"}).result()

        self.assertEqual(primary.synced[0][0:2], ("question", "answer"))
        self.assertEqual(vector.synced[0][2]["conversation_id"], "c1")

    def test_close_notifies_every_provider(self):
        primary = FakeProvider("markdown")
        vector = FakeProvider("vector")
        manager = MemoryManager(primary)
        manager.add_provider(vector)

        manager.close()

        self.assertTrue(primary.closed)
        self.assertTrue(vector.closed)

    def test_delete_and_clear_route_to_named_provider(self):
        primary = FakeProvider("markdown")
        vector = FakeProvider("local_vector")
        manager = MemoryManager(primary)
        manager.add_provider(vector)

        deleted = manager.delete(7)
        cleared = manager.clear()

        self.assertTrue(deleted["ok"])
        self.assertTrue(cleared["ok"])
        self.assertEqual(vector.deleted, [7])
        self.assertEqual(vector.clear_calls, 1)
        self.assertEqual(primary.deleted, [])


if __name__ == "__main__":
    unittest.main()
