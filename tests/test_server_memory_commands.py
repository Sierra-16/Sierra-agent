import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.permission_policy import PermissionPolicy
from aiagent.server import run_server


class FakeAudit:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(event)
        return event


class FakeMemoryCommandAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake-model")
        self.model = "fake-model"
        self.conv_id = "c1"
        self.permission_policy = PermissionPolicy({
            "ask": ["memory_forget", "memory_clear"],
        })
        self.audit = FakeAudit()
        self.forgotten = []
        self.clear_calls = 0
        self.closed = False

    def list_conversations(self):
        return []

    def memory_status(self):
        return {
            "curated": "【关于用户】\n- 喜欢红茶",
            "providers": [
                {"name": "markdown", "available": True, "memory_entries": 0, "user_entries": 1},
                {"name": "local_vector", "available": True, "records": 2, "embedding_model": "test"},
            ],
        }

    def memory_search(self, query, limit=5):
        return [{
            "id": 7,
            "content": f"用户: {query}\nSierra: remembered",
            "score": 0.88,
            "created_at": "2026-06-21T10:00:00+00:00",
        }]

    def memory_forget(self, memory_id):
        self.forgotten.append(memory_id)
        return {"ok": True, "deleted": 1, "id": memory_id}

    def memory_clear(self):
        self.clear_calls += 1
        return {"ok": True, "deleted": 2}

    def close(self):
        self.closed = True


def run_commands(agent, messages):
    stdin = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    output = io.StringIO()
    with (
        patch.object(sys, "stdin", stdin),
        patch.object(sys, "stdout", output),
        patch.object(sys, "__stdout__", output),
        patch("aiagent.server.uuid.uuid4", return_value=SimpleNamespace(hex="1234567890abcdef")),
    ):
        run_server(agent)
    return [json.loads(line) for line in output.getvalue().splitlines() if line]


class ServerMemoryCommandTests(unittest.TestCase):
    def test_memory_status_and_search_are_read_only(self):
        agent = FakeMemoryCommandAgent()

        events = run_commands(agent, [
            {"cmd": "memory"},
            {"cmd": "memory_search", "query": "桂林旅行"},
        ])

        self.assertEqual(events[0]["type"], "memory")
        self.assertIn("当前工作区 2 条", events[0]["text"])
        self.assertEqual(events[1]["type"], "memory_search")
        self.assertIn("#7", events[1]["text"])
        self.assertEqual(agent.audit.events, [])

    def test_memory_forget_requires_approval_and_is_audited(self):
        agent = FakeMemoryCommandAgent()

        events = run_commands(agent, [
            {"cmd": "memory_forget", "id": 7},
            {"cmd": "tool_approval", "id": "tool-1234567890ab", "decision": "once"},
        ])

        self.assertEqual([event["type"] for event in events], [
            "tool_approval_request",
            "tool_approval_result",
            "memory_action",
        ])
        self.assertEqual(agent.forgotten, [7])
        self.assertTrue(agent.audit.events[0]["executed"])
        self.assertTrue(agent.audit.events[0]["success"])
        self.assertEqual(agent.audit.events[0]["tool"], "memory_forget")

    def test_rejected_clear_does_not_execute_but_is_audited(self):
        agent = FakeMemoryCommandAgent()

        events = run_commands(agent, [
            {"cmd": "memory_clear"},
            {"cmd": "tool_approval", "id": "tool-1234567890ab", "decision": "deny"},
        ])

        self.assertEqual(events[-1]["type"], "memory_action")
        self.assertEqual(agent.clear_calls, 0)
        self.assertFalse(agent.audit.events[0]["executed"])
        self.assertFalse(agent.audit.events[0]["approved"])


if __name__ == "__main__":
    unittest.main()
