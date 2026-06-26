import unittest

from aiagent.context_budget import (
    fit_messages_to_budget,
    prepare_conversation_messages_for_request,
)
from aiagent.conversation_loop import run_conversation_loop


class ContextBudgetTests(unittest.TestCase):
    def test_prepare_request_messages_truncates_old_tool_results_only_in_copy(self):
        original = [
            {"role": "tool", "content": "old-" + "x" * 1000, "tool_call_id": "old"},
            {"role": "user", "content": "continue"},
            {"role": "tool", "content": "recent-" + "y" * 1000, "tool_call_id": "recent"},
        ]

        prepared, stats = prepare_conversation_messages_for_request(
            original,
            old_tool_result_max_chars=120,
            recent_tool_result_max_chars=2000,
            recent_message_count=2,
        )

        self.assertEqual(stats["truncated_tool_results"], 1)
        self.assertLess(len(prepared[0]["content"]), len(original[0]["content"]))
        self.assertEqual(prepared[2]["content"], original[2]["content"])
        self.assertEqual(len(original[0]["content"]), 1004)

    def test_fit_messages_keeps_recent_turns_and_omits_old_history(self):
        system_messages = [{"role": "system", "content": "system"}]
        conversation_messages = [
            {"role": "user", "content": "old " + "x" * 2000},
            {"role": "assistant", "content": "old answer " + "y" * 2000},
            {"role": "user", "content": "current question"},
        ]

        fitted, omitted = fit_messages_to_budget(
            system_messages,
            conversation_messages,
            max_tokens=300,
        )

        rendered = str(fitted)
        self.assertGreater(omitted, 0)
        self.assertNotIn("old answer", rendered)
        self.assertIn("current question", rendered)


class BudgetAwareLLM:
    def __init__(self):
        self.messages = None

    def stream_chat(self, messages, tools, on_delta):
        self.messages = messages
        return {
            "content": "ok",
            "tool_calls": None,
            "usage": {"input": 10, "output": 1},
        }


class EmptyTools:
    def get_definitions(self):
        return []


class BudgetAgent:
    def __init__(self):
        self.messages = [
            {"role": "user", "content": "old " + "x" * 2000},
            {"role": "assistant", "content": "old answer " + "y" * 2000},
        ]
        self.llm = BudgetAwareLLM()
        self.tools = EmptyTools()
        self.memory_manager = None
        self.history_recall_config = {"enabled": False}
        self.system_prompt = "system"
        self.max_iterations = 2
        self.max_compress_tokens = 100000
        self.context_window = 400
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.conv_id = "c1"
        self.model = "test-model"

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def update_current_context(self, actual_tokens, estimated_tokens=0):
        self.current_context_tokens = actual_tokens or estimated_tokens

    def compress_messages(self, keep_tokens=None):
        return {"compressed": False}


class ConversationLoopContextBudgetTests(unittest.TestCase):
    def test_loop_trims_sent_context_without_mutating_history(self):
        agent = BudgetAgent()
        statuses = []

        result = run_conversation_loop(agent, "current question", on_status=statuses.append)

        self.assertEqual(result, "ok")
        rendered_request = str(agent.llm.messages)
        self.assertNotIn("old answer", rendered_request)
        self.assertIn("current question", rendered_request)
        self.assertIn("old answer", str(agent.messages))
        self.assertTrue(any(event["type"] == "context_budget_trimmed" for event in statuses))


if __name__ == "__main__":
    unittest.main()
