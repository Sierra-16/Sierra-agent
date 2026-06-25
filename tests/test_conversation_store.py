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


if __name__ == "__main__":
    unittest.main()
