import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.server import run_server


class FakeCompanionAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake-model")
        self.model = "fake-model"
        self.conv_id = "c1"
        self.closed = False

    def list_conversations(self):
        return []

    def companion_status(self):
        return {
            "enabled": True,
            "text": "陪伴状态\n- 当前关注: Sierra",
        }

    def companion_handoff(self):
        return "Sierra 续接\n最近关注: Sierra"

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


class ServerCompanionCommandTests(unittest.TestCase):
    def test_companion_command_returns_formatted_state(self):
        agent = FakeCompanionAgent()

        events = run_commands(agent, [{"cmd": "companion"}])

        self.assertEqual(events[0]["type"], "companion")
        self.assertIn("当前关注", events[0]["text"])

    def test_init_includes_companion_handoff(self):
        agent = FakeCompanionAgent()

        events = run_commands(agent, [{"cmd": "init"}])

        self.assertEqual(events[0]["type"], "init")
        self.assertIn("Sierra 续接", events[0]["companion_hint"])


if __name__ == "__main__":
    unittest.main()
