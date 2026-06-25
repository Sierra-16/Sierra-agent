import unittest

from aiagent.agent import Agent


class MemoryReviewScheduleTests(unittest.TestCase):
    def make_agent(self, interval=3, max_chars=16000):
        agent = Agent.__new__(Agent)
        agent.memory_review_interval = interval
        agent.memory_review_max_chars = max_chars
        agent._turns_since_memory_review = 0
        agent.messages = []
        return agent

    def test_review_is_due_only_at_configured_interval(self):
        agent = self.make_agent(interval=3)

        self.assertFalse(agent.memory_review_due())
        self.assertFalse(agent.memory_review_due())
        self.assertTrue(agent.memory_review_due())

    def test_disabled_review_never_becomes_due(self):
        agent = self.make_agent(interval=0)

        for _ in range(20):
            self.assertFalse(agent.memory_review_due())

    def test_transcript_contains_only_recent_completed_turns(self):
        agent = self.make_agent(interval=2)
        agent.messages = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": "second answer"},
            {"role": "user", "content": "third question"},
            {"role": "assistant", "content": "third answer"},
            {"role": "user", "content": "unfinished question"},
        ]

        transcript = agent._build_memory_review_transcript()

        self.assertNotIn("first question", transcript)
        self.assertIn("second question", transcript)
        self.assertIn("third answer", transcript)
        self.assertNotIn("unfinished question", transcript)

    def test_loaded_session_restores_counter_from_user_turns(self):
        agent = self.make_agent(interval=3)
        agent.messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "two"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "three"},
            {"role": "assistant", "content": "c"},
            {"role": "user", "content": "four"},
            {"role": "assistant", "content": "d"},
        ]

        agent.sync_memory_review_state()

        self.assertEqual(agent._turns_since_memory_review, 1)
        self.assertFalse(agent.memory_review_due())
        self.assertTrue(agent.memory_review_due())


if __name__ == "__main__":
    unittest.main()
