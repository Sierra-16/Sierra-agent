import unittest

from aiagent.conversation_loop import run_conversation_loop


class OneShotLLM:
    def stream_chat(self, messages, tools, on_delta):
        return {
            "content": "好的，我们继续。",
            "tool_calls": None,
            "usage": {"input": 10, "output": 5},
        }


class FakeTools:
    def get_definitions(self):
        return []


class CompanionAgent:
    def __init__(self):
        self.messages = []
        self.llm = OneShotLLM()
        self.tools = FakeTools()
        self.memory_manager = None
        self.system_prompt = "system"
        self.max_iterations = 2
        self.max_compress_tokens = 100000
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.conv_id = "c1"
        self.model = "test-model"
        self.history_recall_config = {"enabled": False}
        self.reviewed = False

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def compress_messages(self, keep_tokens=None):
        return {"compressed": False}

    def companion_review_due(self):
        return True

    def review_companion_state(self):
        self.reviewed = True
        return {"changed": True}


class CompanionConversationLifecycleTests(unittest.TestCase):
    def test_companion_review_runs_after_final_answer(self):
        agent = CompanionAgent()
        statuses = []

        answer = run_conversation_loop(
            agent,
            "下一步做什么？",
            on_status=statuses.append,
        )

        self.assertEqual(answer, "好的，我们继续。")
        self.assertTrue(agent.reviewed)
        self.assertIn({"type": "companion_check"}, statuses)
        self.assertIn({"type": "companion_updated"}, statuses)


if __name__ == "__main__":
    unittest.main()
