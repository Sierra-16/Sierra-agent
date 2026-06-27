import unittest

from aiagent.agent import Agent


class ConversationControlTests(unittest.TestCase):
    def make_agent(self, messages):
        agent = Agent.__new__(Agent)
        agent.messages = list(messages)
        agent.system_prompt = "system"
        agent.current_context_tokens = 0
        agent.context_tokens_estimated = False
        agent.sync_memory_review_state = lambda: None
        agent.refresh_context_estimate = lambda: None
        agent.refresh_system_prompt = lambda: None
        agent.checkpoint_conversation = lambda: None
        return agent

    def test_undo_removes_last_user_turn(self):
        agent = self.make_agent([
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "one"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "two"},
        ])

        result = Agent.undo_last_turn(agent)

        self.assertTrue(result["ok"])
        self.assertEqual(
            agent.messages,
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "one"},
            ],
        )

    def test_retry_returns_and_removes_previous_user_turn(self):
        agent = self.make_agent([
            {"role": "user", "content": "write a story"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "done", "tool_call_id": "1"},
            {"role": "assistant", "content": "ok"},
        ])

        result = Agent.retry_last_turn(agent)

        self.assertTrue(result["ok"])
        self.assertEqual(result["user_message"], "write a story")
        self.assertEqual(agent.messages, [])

    def test_undo_can_remove_multiple_turns(self):
        agent = self.make_agent([
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "B"},
        ])

        result = Agent.undo_last_turn(agent, count=2)

        self.assertTrue(result["ok"])
        self.assertEqual(agent.messages, [])


if __name__ == "__main__":
    unittest.main()
