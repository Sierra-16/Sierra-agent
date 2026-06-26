import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.agent import Agent
from aiagent.background_jobs import BackgroundJobQueue
from aiagent.conversation_loop import run_conversation_loop
from aiagent.server import run_server


class BackgroundJobQueueTests(unittest.TestCase):
    def test_jobs_run_and_record_failures(self):
        queue = BackgroundJobQueue()
        self.addCleanup(queue.close)

        queue.submit("ok", lambda: {"saved": 1})

        def fail():
            raise RuntimeError("boom")

        queue.submit("fail", fail)

        self.assertTrue(queue.wait_idle(timeout=2))
        jobs = queue.status()["jobs"]

        self.assertEqual(jobs[0]["name"], "fail")
        self.assertEqual(jobs[0]["status"], "failed")
        self.assertIn("boom", jobs[0]["error"])
        self.assertEqual(jobs[1]["name"], "ok")
        self.assertEqual(jobs[1]["status"], "done")
        self.assertEqual(jobs[1]["summary"]["saved"], 1)


class OneShotLLM:
    def stream_chat(self, messages, tools, on_delta):
        return {
            "content": "answer",
            "tool_calls": None,
            "usage": {"input": 3, "output": 2},
        }


class EmptyTools:
    def get_definitions(self):
        return []


class ScheduledMaintenanceAgent:
    def __init__(self):
        self.messages = []
        self.llm = OneShotLLM()
        self.tools = EmptyTools()
        self.memory_manager = None
        self.history_recall_config = {"enabled": False}
        self.system_prompt = "system"
        self.max_iterations = 2
        self.max_compress_tokens = 100000
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.current_context_tokens = 0
        self.context_tokens_estimated = False
        self.conv_id = "c1"
        self.model = "test-model"
        self.maintenance_calls = []

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def update_current_context(self, actual_tokens, estimated_tokens=0):
        self.current_context_tokens = actual_tokens or estimated_tokens

    def compress_messages(self, keep_tokens=None):
        return {"compressed": False}

    def schedule_post_turn_maintenance(
        self,
        user_message,
        assistant_message,
        *,
        messages_snapshot=None,
        on_status=None,
    ):
        self.maintenance_calls.append({
            "user": user_message,
            "assistant": assistant_message,
            "snapshot": list(messages_snapshot or []),
        })


class ConversationLoopBackgroundJobTests(unittest.TestCase):
    def test_final_answer_schedules_post_turn_maintenance(self):
        agent = ScheduledMaintenanceAgent()

        result = run_conversation_loop(agent, "hello")

        self.assertEqual(result, "answer")
        self.assertEqual(len(agent.maintenance_calls), 1)
        call = agent.maintenance_calls[0]
        self.assertEqual(call["user"], "hello")
        self.assertEqual(call["assistant"], "answer")
        self.assertEqual(call["snapshot"][-1], {"role": "assistant", "content": "answer"})


class ImmediateFuture:
    def result(self):
        return None


class FakeMemoryManager:
    def __init__(self):
        self.sync_calls = []

    def sync_turn(self, user_message, assistant_message, metadata=None):
        self.sync_calls.append((user_message, assistant_message, metadata))
        return ImmediateFuture()


class AgentBackgroundMaintenanceTests(unittest.TestCase):
    def test_agent_schedules_all_post_turn_jobs_with_snapshot(self):
        agent = Agent.__new__(Agent)
        agent.background_jobs = BackgroundJobQueue()
        self.addCleanup(agent.background_jobs.close)
        agent.memory_manager = FakeMemoryManager()
        agent.conv_id = "conv-1"
        agent.model = "test-model"
        agent.workspace = "workspace"
        agent.memory_review_due = lambda: True
        agent.companion_review_due = lambda: True
        reviewed = {}

        def review_memory(messages=None):
            reviewed["memory"] = messages
            return {"saved": [{"content": "saved"}]}

        def review_companion(messages=None, conversation_id=None):
            reviewed["companion"] = (messages, conversation_id)
            return {"changed": True}

        agent.review_recent_memory = review_memory
        agent.review_companion_state = review_companion
        snapshot = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "answer"},
        ]

        result = Agent.schedule_post_turn_maintenance(
            agent,
            "hello",
            "answer",
            messages_snapshot=snapshot,
        )

        self.assertEqual(
            [job["name"] for job in result["queued"]],
            ["memory_sync", "memory_review", "companion_review"],
        )
        self.assertTrue(agent.background_jobs.wait_idle(timeout=2))
        self.assertEqual(agent.memory_manager.sync_calls[0][0:2], ("hello", "answer"))
        self.assertEqual(reviewed["memory"], snapshot)
        self.assertEqual(reviewed["companion"], (snapshot, "conv-1"))


class FakeJobsAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake-model")
        self.model = "fake-model"
        self.limit = None
        self.closed = False

    def list_conversations(self):
        return []

    def background_jobs_status(self, limit=20):
        self.limit = limit
        return {
            "enabled": True,
            "jobs": [{"name": "memory_sync", "status": "done"}],
            "text": "Background Jobs\n- memory_sync done",
        }

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


class ServerJobsCommandTests(unittest.TestCase):
    def test_jobs_command_returns_background_status(self):
        agent = FakeJobsAgent()

        events = run_commands(agent, [{"cmd": "jobs"}])

        self.assertEqual(events[0]["type"], "jobs")
        self.assertIn("Background Jobs", events[0]["text"])
        self.assertEqual(agent.limit, 20)


if __name__ == "__main__":
    unittest.main()
