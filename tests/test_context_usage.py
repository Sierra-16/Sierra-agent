import unittest

from aiagent.agent import Agent


class FakeTools:
    def get_definitions(self):
        return [{"type": "function", "function": {"name": "demo"}}]


class ContextUsageTests(unittest.TestCase):
    def make_agent(self):
        agent = Agent.__new__(Agent)
        agent.total_input_tokens = 100
        agent.total_output_tokens = 20
        agent.current_context_tokens = 0
        agent.context_tokens_estimated = False
        agent.context_window = 1000
        agent.system_prompt = "system prompt"
        agent.messages = [{"role": "user", "content": "hello"}]
        agent.tools = FakeTools()
        agent._turns_since_memory_review = 5
        return agent

    def test_actual_prompt_tokens_take_priority(self):
        agent = self.make_agent()

        agent.update_current_context(321, estimated_tokens=999)

        self.assertEqual(agent.current_context_tokens, 321)
        self.assertFalse(agent.context_tokens_estimated)

    def test_estimate_is_used_when_provider_reports_no_usage(self):
        agent = self.make_agent()

        agent.update_current_context(0, estimated_tokens=456)

        self.assertEqual(agent.current_context_tokens, 456)
        self.assertTrue(agent.context_tokens_estimated)

    def test_usage_snapshot_keeps_cumulative_and_context_separate(self):
        agent = self.make_agent()
        agent.update_current_context(321)

        snapshot = agent.usage_snapshot()

        self.assertEqual(snapshot["input"], 100)
        self.assertEqual(snapshot["output"], 20)
        self.assertEqual(snapshot["context"], 321)
        self.assertEqual(snapshot["context_window"], 1000)

    def test_reset_clears_context_but_not_cumulative_usage(self):
        agent = self.make_agent()
        agent.current_context_tokens = 321

        agent.reset()

        self.assertEqual(agent.current_context_tokens, 0)
        self.assertEqual(agent.total_input_tokens, 100)
        self.assertEqual(agent.total_output_tokens, 20)

    def test_refresh_context_marks_value_as_estimated(self):
        agent = self.make_agent()

        agent.refresh_context_estimate()

        self.assertGreater(agent.current_context_tokens, 0)
        self.assertTrue(agent.context_tokens_estimated)


if __name__ == "__main__":
    unittest.main()
