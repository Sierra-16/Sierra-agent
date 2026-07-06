import os
import tempfile
import unittest

from aiagent.conversation_store import ConversationStore


class ConversationStoreTests(unittest.TestCase):
    def test_atomic_save_round_trip(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = ConversationStore(storage_dir=temp_dir.name)
        messages = [{"role": "user", "content": "继续任务"}]

        store.save("conversation-1", messages, {"input": 3}, "任务")
        loaded_messages, usage = store.load("conversation-1")

        self.assertEqual(loaded_messages, messages)
        self.assertEqual(usage["input"], 3)
        leftovers = [
            name for name in os.listdir(temp_dir.name)
            if name.endswith(".tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_rename_updates_index_title(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = ConversationStore(storage_dir=temp_dir.name)
        store.save("conversation-1", [{"role": "user", "content": "hello"}], {}, "old")

        self.assertTrue(store.rename("conversation-1", "new title"))

        conversations = store.list_all()
        self.assertEqual(conversations[0]["title"], "new title")

    def test_delete_removes_messages_and_index_entry(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        store = ConversationStore(storage_dir=temp_dir.name)
        store.save("conversation-1", [{"role": "user", "content": "hello"}], {}, "demo")

        self.assertTrue(store.delete("conversation-1"))

        self.assertEqual(store.load("conversation-1"), ([], {}))
        self.assertEqual(store.list_all(), [])


if __name__ == "__main__":
    unittest.main()
