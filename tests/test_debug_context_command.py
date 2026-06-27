import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.agent import Agent
from aiagent.server import run_server
from aiagent.turn_context import TurnContext


class FakeDebugContextAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake-model")
        self.model = "fake-model"
        self.conv_id = "c1"
        self.last_turn_context = TurnContext(
            user_message="继续",
            system_prompt="system",
            memory_context="memory",
            estimated_context_tokens=123,
        )
        self.closed = False

    def list_conversations(self):
        return []

    def debug_context_status(self):
        return Agent.debug_context_status(self)

    def close(self):
        self.closed = True


def run_commands(agent, messages):
    stdin = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    output = io.StringIO()
    with (
        patch.object(sys, "stdin", stdin),
        patch.object(sys, "stdout", output),
        patch.object(sys, "__stdout__", output),
    ):
        run_server(agent)
    return [json.loads(line) for line in output.getvalue().splitlines() if line]


class DebugContextCommandTests(unittest.TestCase):
    def test_agent_formats_last_turn_context(self):
        agent = FakeDebugContextAgent()

        status = agent.debug_context_status()

        self.assertTrue(status["available"])
        self.assertIn("TurnContext", status["text"])
        self.assertIn("memory 0", status["text"])
        self.assertEqual(status["summary"]["estimated_context_tokens"], 123)

    def test_agent_handles_missing_turn_context(self):
        agent = SimpleNamespace()

        status = Agent.debug_context_status(agent)

        self.assertFalse(status["available"])
        self.assertIn("暂无", status["text"])

    def test_server_debug_context_command(self):
        agent = FakeDebugContextAgent()

        events = run_commands(agent, [{"cmd": "debug_context"}])

        self.assertEqual(events[0]["type"], "debug_context")
        self.assertTrue(events[0]["available"])
        self.assertIn("TurnContext", events[0]["text"])


if __name__ == "__main__":
    unittest.main()
