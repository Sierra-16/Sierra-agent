import tempfile
import unittest

from aiagent.memory_store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def make_store(self, max_memory_chars=2200, max_user_chars=1375):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return MemoryStore(
            base_dir=temp_dir.name,
            max_memory_chars=max_memory_chars,
            max_user_chars=max_user_chars,
        )

    def test_add_normalizes_multiline_entries(self):
        store = self.make_store()

        result = store.add("用户喜欢\n  红茶", target="user")

        self.assertTrue(result["ok"])
        self.assertEqual(store.get_entries("user"), ["用户喜欢 红茶"])

    def test_replace_requires_a_unique_match(self):
        store = self.make_store()
        store.add("用户喜欢咖啡", target="user")
        store.add("用户喜欢咖啡味甜点", target="user")

        result = store.replace("咖啡", "用户喜欢红茶", target="user")

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["matches"]), 2)
        self.assertEqual(len(store.get_entries("user")), 2)

    def test_replace_updates_one_entry(self):
        store = self.make_store()
        store.add("用户喜欢咖啡", target="user")

        result = store.replace("喜欢咖啡", "用户现在更喜欢红茶", target="user")

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(store.get_entries("user"), ["用户现在更喜欢红茶"])

    def test_failed_replacement_keeps_original_file(self):
        store = self.make_store(max_memory_chars=5)
        store.add("12345", target="memory")

        result = store.replace("123", "123456", target="memory")

        self.assertFalse(result["ok"])
        self.assertEqual(store.get_entries("memory"), ["12345"])

    def test_automatic_remove_rejects_ambiguous_match(self):
        store = self.make_store()
        store.add("项目使用 Python", target="memory")
        store.add("项目使用 Python 测试", target="memory")

        result = store.remove("Python", target="memory", require_unique=True)

        self.assertFalse(result["ok"])
        self.assertEqual(len(store.get_entries("memory")), 2)

    def test_manual_remove_can_delete_all_matches(self):
        store = self.make_store()
        store.add("旧事实 A", target="memory")
        store.add("旧事实 B", target="memory")

        result = store.remove("旧事实", target="memory")

        self.assertTrue(result["ok"])
        self.assertEqual(result["removed"], 2)
        self.assertEqual(store.get_entries("memory"), [])


if __name__ == "__main__":
    unittest.main()
