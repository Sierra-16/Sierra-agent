import json
import unittest

from aiagent.agent import Agent
from aiagent.safety import SafetyGate
from aiagent.todo import MAX_TODO_CONTENT_CHARS, TRUNCATION_MARKER, TodoStore
from aiagent.toolsets import resolve_toolset


class TodoStoreTests(unittest.TestCase):
    def test_write_read_and_summary(self):
        store = TodoStore()

        result = json.loads(store.tool(todos=[
            {"id": "1", "content": "Inspect workspace", "status": "completed"},
            {"id": "2", "content": "Patch files", "status": "in_progress"},
            {"id": "3", "content": "Run tests", "status": "pending"},
        ]))

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["total"], 3)
        self.assertEqual(result["summary"]["in_progress"], 1)
        self.assertEqual(result["todos"][1]["content"], "Patch files")

    def test_merge_updates_by_id_and_preserves_order(self):
        store = TodoStore()
        store.write([
            {"id": "a", "content": "A", "status": "pending"},
            {"id": "b", "content": "B", "status": "pending"},
        ])

        items = store.write([
            {"id": "b", "content": "B done", "status": "completed"},
            {"id": "c", "content": "C", "status": "pending"},
        ], merge=True)

        self.assertEqual([item["id"] for item in items], ["a", "b", "c"])
        self.assertEqual(items[1]["content"], "B done")
        self.assertEqual(items[1]["status"], "completed")

    def test_prompt_injection_only_keeps_active_items(self):
        store = TodoStore()
        store.write([
            {"id": "done", "content": "Already done", "status": "completed"},
            {"id": "now", "content": "Keep working", "status": "in_progress"},
            {"id": "later", "content": "Verify", "status": "pending"},
        ])

        prompt = store.format_for_prompt()

        self.assertIn("Active Work List", prompt)
        self.assertIn("Keep working", prompt)
        self.assertIn("Verify", prompt)
        self.assertNotIn("Already done", prompt)

    def test_content_is_capped(self):
        store = TodoStore()

        items = store.write([
            {"id": "huge", "content": "x" * (MAX_TODO_CONTENT_CHARS + 100), "status": "pending"},
        ])

        self.assertEqual(len(items[0]["content"]), MAX_TODO_CONTENT_CHARS)
        self.assertTrue(items[0]["content"].endswith(TRUNCATION_MARKER))

    def test_sierra_reset_clears_todo_store(self):
        agent = object.__new__(Agent)
        agent.task_manager = None
        agent.messages = [{"role": "user", "content": "hello"}]
        agent.todo_store = TodoStore()
        agent.todo_store.write([
            {"id": "1", "content": "temporary", "status": "pending"},
        ])
        agent._turns_since_memory_review = 5
        agent.current_context_tokens = 10
        agent.context_tokens_estimated = True
        agent._ineffective_compression_count = 1
        agent._summary_failure_cooldown_until = 123.0

        Agent.reset(agent)

        self.assertEqual(agent.todo_store.read(), [])
        self.assertEqual(agent.messages, [])


class TodoIntegrationTests(unittest.TestCase):
    def test_todo_is_low_risk_planning_tool(self):
        self.assertEqual(SafetyGate().assess("todo").level, "low")

        tools = resolve_toolset("planning")

        self.assertIn("todo", tools)


if __name__ == "__main__":
    unittest.main()
