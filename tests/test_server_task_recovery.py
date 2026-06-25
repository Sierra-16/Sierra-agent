import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.server import run_server


class FakeTaskAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake-model")
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.current_context_tokens = 0
        self.context_window = 1000
        self.context_tokens_estimated = False
        self.conv_id = "conversation-1"
        self.closed = False
        self.task = {
            "id": "task-1",
            "conversation_id": "conversation-1",
            "workspace": "E:/workspace",
            "objective": "继续未完成任务",
            "status": "interrupted",
            "steps": [{
                "id": "step-1",
                "position": 0,
                "step": "完成测试",
                "status": "in_progress",
                "note": "",
            }],
            "uncertain_executions": [],
        }

    def list_conversations(self):
        return []

    def task_status(self):
        return self.task

    def task_recovery(self, task_id=None):
        if task_id and task_id != self.task["id"]:
            return None
        return self.task if self.task["status"] == "interrupted" else None

    def resume_task(self, task_id):
        self.task["status"] = "active"
        return {"ok": True, "task": self.task}

    def abandon_task(self, task_id):
        self.task["status"] = "cancelled"
        return {"ok": True, "task": self.task}

    def close(self):
        self.closed = True


class ServerTaskRecoveryTests(unittest.TestCase):
    def run_commands(self, commands):
        agent = FakeTaskAgent()
        stdin = io.StringIO("".join(json.dumps(command) + "\n" for command in commands))
        output = io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", output),
        ):
            run_server(agent)
        events = [json.loads(line) for line in output.getvalue().splitlines() if line]
        return agent, events

    def test_init_exposes_interrupted_task(self):
        agent, events = self.run_commands([{"cmd": "init"}])

        self.assertEqual(events[0]["recovery_task"]["id"], "task-1")
        self.assertTrue(agent.closed)

    def test_resume_command_reactivates_task(self):
        agent, events = self.run_commands([
            {"cmd": "task_resume", "id": "task-1"},
        ])

        self.assertEqual(events[0]["type"], "task_recovery_result")
        self.assertTrue(events[0]["success"])
        self.assertEqual(events[0]["task"]["status"], "active")
        self.assertEqual(agent.task["status"], "active")


if __name__ == "__main__":
    unittest.main()
