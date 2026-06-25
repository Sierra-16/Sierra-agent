import tempfile
import unittest

from aiagent.agent import Agent
from aiagent.memory import MemoryManager, MarkdownMemoryProvider
from aiagent.memory_store import MemoryStore


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.messages = None

    def chat(self, messages):
        self.messages = messages
        return {
            "content": self.content,
            "usage": {"input": 5, "output": 2},
        }


class MemoryReviewOperationTests(unittest.TestCase):
    def make_store(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return MemoryStore(base_dir=temp_dir.name)

    def make_agent(self):
        agent = Agent.__new__(Agent)
        agent.memory_review_interval = 2
        agent.memory_review_max_chars = 16000
        agent._turns_since_memory_review = 2
        agent.total_input_tokens = 0
        agent.total_output_tokens = 0
        agent.current_context_tokens = 777
        agent.messages = [
            {"role": "user", "content": "我现在更喜欢红茶"},
            {"role": "assistant", "content": "记住了"},
        ]
        agent.refresh_system_prompt = lambda: None
        return agent

    def test_parser_accepts_operations_and_legacy_memories(self):
        agent = self.make_agent()

        operations = agent._parse_memory_operations(
            '```json\n{"operations":[{"action":"remove","target":"memory","old_text":"旧"}]}\n```'
        )
        legacy = agent._parse_memory_operations(
            '{"memories":[{"target":"user","content":"用户喜欢红茶"}]}'
        )

        self.assertEqual(operations[0]["action"], "remove")
        self.assertEqual(legacy[0]["action"], "add")

    def test_apply_operations_adds_replaces_and_removes(self):
        store = self.make_store()
        store.add("用户喜欢咖啡", target="user")
        store.add("项目仍使用旧架构", target="memory")
        provider = MarkdownMemoryProvider(store)
        operations = [
            {
                "action": "replace",
                "target": "user",
                "old_text": "喜欢咖啡",
                "content": "用户现在更喜欢红茶",
            },
            {
                "action": "remove",
                "target": "memory",
                "old_text": "仍使用旧架构",
            },
            {
                "action": "add",
                "target": "memory",
                "content": "项目已采用新架构",
            },
        ]

        result = provider.apply_operations(operations)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["changes"]), 3)
        self.assertEqual(store.get_entries("user"), ["用户现在更喜欢红茶"])
        self.assertEqual(store.get_entries("memory"), ["项目已采用新架构"])

    def test_duplicate_add_is_not_reported_as_change(self):
        store = self.make_store()
        store.add("用户喜欢红茶", target="user")
        provider = MarkdownMemoryProvider(store)

        result = provider.apply_operations([{
                "action": "add",
                "target": "user",
                "content": "用户喜欢红茶",
            }])

        self.assertEqual(result["changes"], [])
        self.assertEqual(result["errors"], [])

    def test_review_receives_existing_memory_and_recent_dialogue(self):
        store = self.make_store()
        store.add("用户以前喜欢咖啡", target="user")
        agent = self.make_agent()
        agent.llm = FakeLLM('{"operations":[]}')
        agent.memory_manager = MemoryManager(MarkdownMemoryProvider(store))

        result = agent.review_recent_memory()

        review_input = agent.llm.messages[1]["content"]
        self.assertEqual(result["saved"], [])
        self.assertIn("用户以前喜欢咖啡", review_input)
        self.assertIn("我现在更喜欢红茶", review_input)
        self.assertEqual(agent._turns_since_memory_review, 0)
        self.assertEqual(agent.total_input_tokens, 5)
        self.assertEqual(agent.current_context_tokens, 777)


if __name__ == "__main__":
    unittest.main()
