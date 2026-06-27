import tempfile
import time
import unittest

from aiagent.cron import CronStore


class CronStoreTests(unittest.TestCase):
    def test_add_list_remove(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CronStore("cron.json", base_dir=tmpdir)
            task = store.add("stand up", 15)

            self.assertEqual(len(store.list()), 1)
            self.assertTrue(store.remove(task["id"]))
            self.assertEqual(store.list(), [])

    def test_due_advances_next_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CronStore("cron.json", base_dir=tmpdir)
            task = store.add("check memory", 1)
            tasks = store._load()
            tasks[0].next_run_at = time.time() - 1
            store._save(tasks)

            due = store.due()
            after = store.list()[0]

        self.assertEqual(due[0]["id"], task["id"])
        self.assertIsNotNone(after["last_run_at"])
        self.assertGreater(after["next_run_at"], after["last_run_at"])


if __name__ == "__main__":
    unittest.main()
