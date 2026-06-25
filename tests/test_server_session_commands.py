import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.server import run_server


class FakeSessionAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake-model")
        self.model = "fake-model"
        self.messages = []
        self.conv_id = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.current_context_tokens = 0
        self.context_window = 1000
        self.context_tokens_estimated = False
        self.closed = False
        self.loaded = []

    def list_conversations(self):
        return []

    def list_sessions(self, limit=20):
        return [{
            "id": "s1",
            "title": "Guilin food",
            "updated_at": 1_780_000_000,
            "message_count": 2,
        }]

    def search_sessions(self, query, limit=10):
        return [{
            "message_id": 3,
            "session_id": "s1",
            "role": "assistant",
            "snippet": f"found {query}",
            "content": f"found {query}",
            "created_at": 1_780_000_000,
            "title": "Guilin food",
        }]

    def load_session(self, session_id):
        self.loaded.append(session_id)
        self.conv_id = session_id
        self.messages = [{"role": "user", "content": "hello"}]
        return {"ok": True, "session": {"id": session_id, "title": "Guilin food"}}

    def save_conversation(self, usage, title=""):
        return None

    def usage_snapshot(self):
        return {
            "input": 0,
            "output": 0,
            "context": 0,
            "context_window": 1000,
            "context_estimated": False,
        }

    def task_status(self):
        return None

    def task_recovery(self, task_id=None):
        return None

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


class ServerSessionCommandTests(unittest.TestCase):
    def test_sessions_and_search_commands_return_text(self):
        agent = FakeSessionAgent()

        events = run_commands(agent, [
            {"cmd": "sessions"},
            {"cmd": "session_search", "query": "Guilin"},
        ])

        self.assertEqual(events[0]["type"], "sessions")
        self.assertIn("s1", events[0]["text"])
        self.assertEqual(events[1]["type"], "session_search")
        self.assertIn("found Guilin", events[1]["text"])

    def test_session_load_uses_agent_loader(self):
        agent = FakeSessionAgent()

        events = run_commands(agent, [{"cmd": "session_load", "id": "s1"}])

        self.assertEqual(events[0]["type"], "session_loaded")
        self.assertTrue(events[0]["success"])
        self.assertEqual(agent.loaded, ["s1"])


if __name__ == "__main__":
    unittest.main()
