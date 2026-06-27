import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.server import run_server


class FakeServerAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake-model")
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.current_context_tokens = 321
        self.context_window = 1000
        self.context_tokens_estimated = False
        self.workspace = os.path.join(os.getcwd(), "fake-workspace")
        self.answer = None
        self.closed = False

    def list_conversations(self):
        return []

    def chat(self, user_message, on_status=None, on_tool_approval=None, on_user_input=None):
        self.answer = on_user_input({
            "question": "Choose a database",
            "options": [{
                "label": "PostgreSQL",
                "description": "Server database",
                "value": "postgres",
            }],
            "allow_free_text": True,
        })
        return "continued"

    def close(self):
        self.closed = True


class ServerUserInputTests(unittest.TestCase):
    def test_init_reports_agent_workspace_as_cwd(self):
        agent = FakeServerAgent()
        stdin = io.StringIO(json.dumps({"cmd": "init"}) + "\n")
        output = io.StringIO()

        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", output),
            patch.object(sys, "__stdout__", output),
        ):
            run_server(agent)

        events = [json.loads(line) for line in output.getvalue().splitlines() if line]
        self.assertEqual(events[0]["type"], "init")
        self.assertEqual(events[0]["cwd"], agent.workspace)

    def test_server_round_trip_resumes_chat(self):
        agent = FakeServerAgent()
        request_id = "input-1234567890ab"
        stdin = io.StringIO(
            json.dumps({"cmd": "chat", "text": "build an app"}) + "\n" +
            json.dumps({
                "cmd": "user_input_response",
                "id": request_id,
                "value": "postgres",
                "label": "PostgreSQL",
                "free_text": False,
                "cancelled": False,
            }) + "\n"
        )
        output = io.StringIO()

        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", output),
            patch.object(sys, "__stdout__", output),
            patch("aiagent.server.uuid.uuid4", return_value=SimpleNamespace(hex="1234567890abcdef")),
        ):
            run_server(agent)

        events = [json.loads(line) for line in output.getvalue().splitlines() if line]
        self.assertEqual(events[0]["type"], "user_input_request")
        self.assertEqual(events[0]["id"], request_id)
        self.assertEqual(events[1]["type"], "user_input_result")
        self.assertEqual(events[2]["type"], "done")
        self.assertEqual(events[2]["usage"]["context"], 321)
        self.assertEqual(events[2]["usage"]["context_window"], agent.context_window)
        self.assertEqual(agent.answer["value"], "postgres")
        self.assertTrue(agent.closed)


if __name__ == "__main__":
    unittest.main()
