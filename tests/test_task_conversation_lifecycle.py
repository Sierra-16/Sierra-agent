import json
import unittest

from aiagent.agent import Agent
from aiagent.conversation_loop import run_conversation_loop
from aiagent.permission_policy import PermissionPolicy
from aiagent.safety import SafetyGate


class FakeTools:
    def get_definitions(self):
        return []

    def execute(self, name, arguments):
        return json.dumps({"ok": True, "name": name})


class ToolThenAnswerLLM:
    def __init__(self):
        self.calls = []

    def stream_chat(self, messages, tools, on_delta):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return {
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "demo_tool", "arguments": "{}"},
                }],
                "usage": {"input": 1, "output": 1},
            }
        return {
            "content": "done",
            "tool_calls": None,
            "usage": {"input": 1, "output": 1},
        }


class FakeTaskManager:
    def __init__(self):
        self.started = []
        self.finished = []

    def prompt_context(self):
        return "<task-plan>current plan</task-plan>"

    def start_tool_execution(self, **kwargs):
        self.started.append(kwargs)
        return "exec-1"

    def finish_tool_execution(self, execution_id, success, result_summary):
        self.finished.append((execution_id, success, result_summary))


class TaskConversationLifecycleTests(unittest.TestCase):
    def make_agent(self):
        agent = Agent.__new__(Agent)
        agent.messages = []
        agent.llm = ToolThenAnswerLLM()
        agent.tools = FakeTools()
        agent.safety = SafetyGate()
        agent.permission_policy = PermissionPolicy({"allow": ["demo_tool"]})
        agent.task_manager = FakeTaskManager()
        agent.memory_manager = None
        agent.system_prompt = "system"
        agent.max_iterations = 3
        agent.max_compress_tokens = 100000
        agent.total_input_tokens = 0
        agent.total_output_tokens = 0
        agent.current_context_tokens = 0
        agent.context_tokens_estimated = False
        agent.memory_review_interval = 0
        agent.conv_id = "conversation-1"
        agent.model = "test-model"
        return agent

    def test_tool_execution_is_checkpointed_and_plan_is_in_prompt(self):
        agent = self.make_agent()

        result = run_conversation_loop(agent, "do the task")

        self.assertEqual(result, "done")
        self.assertEqual(agent.task_manager.started[0]["tool_call_id"], "call-1")
        self.assertEqual(agent.task_manager.started[0]["tool_name"], "demo_tool")
        self.assertEqual(agent.task_manager.finished[0][0:2], ("exec-1", True))
        self.assertTrue(any(
            message.get("content") == "<task-plan>current plan</task-plan>"
            for message in agent.llm.calls[0]
        ))

    def test_uncertain_tool_call_is_reconciled_for_api_validity(self):
        agent = Agent.__new__(Agent)
        agent.messages = [{
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-uncertain",
                "type": "function",
                "function": {"name": "write_file", "arguments": "{}"},
            }],
        }]
        agent.task_manager = type("RecoveryManager", (), {
            "recovery_task": lambda self: {
                "uncertain_executions": [{
                    "tool_call_id": "call-uncertain",
                    "tool_name": "write_file",
                }],
            },
        })()
        checkpoints = []
        agent.checkpoint_conversation = lambda: checkpoints.append(True)

        agent._reconcile_uncertain_tool_calls()

        self.assertEqual(agent.messages[-1]["role"], "tool")
        self.assertEqual(agent.messages[-1]["tool_call_id"], "call-uncertain")
        self.assertIn("uncertain", agent.messages[-1]["content"])
        self.assertEqual(checkpoints, [True])

    def test_dangling_tool_call_without_task_checkpoint_is_reconciled(self):
        agent = Agent.__new__(Agent)
        agent.messages = [{
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-waiting",
                "type": "function",
                "function": {"name": "request_user_input", "arguments": "{}"},
            }],
        }]
        agent.task_manager = None
        agent.checkpoint_conversation = lambda: None

        agent._reconcile_uncertain_tool_calls()

        self.assertEqual(agent.messages[-1]["tool_call_id"], "call-waiting")
        self.assertIn("interrupted", agent.messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
