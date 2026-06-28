import json
import os
import unittest

from aiagent.conversation_loop import run_conversation_loop
from aiagent.tools.tool_result_storage import PERSISTED_OUTPUT_TAG
from aiagent.permission_policy import PermissionPolicy
from aiagent.safety import SafetyGate


class FakeTools:
    def __init__(self):
        self.executed = []
        self.forced_result = None

    def get_definitions(self):
        return []

    def execute(self, name, arguments):
        self.executed.append((name, arguments))
        if self.forced_result is not None:
            return self.forced_result
        return json.dumps({"ok": True, "tool": name}, ensure_ascii=False)

    def get_max_result_size(self, name, default=None):
        return default


class FakeAudit:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(event)
        return event


class FakeSkillUsage:
    def __init__(self):
        self.turns = []
        self.events = []

    def start_turn(self, **event):
        self.turns.append(event)
        return 41

    def record(self, **event):
        self.events.append(event)
        return len(self.events)


class FakeLLM:
    def __init__(self, tool_name, arguments):
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0

    def stream_chat(self, messages, tools, on_delta):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": None,
                "tool_calls": [{
                    "id": "tool-call-1",
                    "type": "function",
                    "function": {
                        "name": self.tool_name,
                        "arguments": json.dumps(self.arguments, ensure_ascii=False),
                    },
                }],
                "usage": {"input": 1, "output": 1},
            }

        return {
            "content": "done",
            "tool_calls": None,
            "usage": {"input": 1, "output": 1},
        }


class FakeAgent:
    def __init__(self, permission_config=None):
        self.messages = []
        self.llm = FakeLLM("write_file", {"file_path": "demo.txt", "content": "hello"})
        self.tools = FakeTools()
        self.safety = SafetyGate()
        self.permission_policy = PermissionPolicy(permission_config)
        self.audit = FakeAudit()
        self.system_prompt = "system"
        self.max_iterations = 3
        self.max_compress_tokens = 100000
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def compress_messages(self):
        return None

    def auto_remember(self, user_message, assistant_response):
        return {"saved": []}


class ConversationPermissionTests(unittest.TestCase):
    def run_scenario(self, permission_config=None, approval="deny"):
        agent = FakeAgent(permission_config)
        approval_requests = []

        def approve(request):
            approval_requests.append(request)
            return approval

        result = run_conversation_loop(
            agent,
            "write the file",
            on_status=lambda event: None,
            on_tool_approval=approve,
        )
        tool_message = next(message for message in agent.messages if message["role"] == "tool")
        return agent, approval_requests, json.loads(tool_message["content"]), result

    def test_deny_policy_blocks_without_prompting(self):
        agent, approvals, tool_result, result = self.run_scenario({"deny": ["write_file"]})

        self.assertEqual(agent.tools.executed, [])
        self.assertEqual(approvals, [])
        self.assertEqual(tool_result["error"], "权限策略禁止执行该工具")
        self.assertFalse(agent.audit.events[0]["executed"])
        self.assertEqual(agent.audit.events[0]["decision"], "deny")
        self.assertEqual(result, "done")

    def test_allow_policy_executes_without_prompting(self):
        agent, approvals, tool_result, _ = self.run_scenario({"allow": ["write_file"]})

        self.assertEqual(len(agent.tools.executed), 1)
        self.assertEqual(approvals, [])
        self.assertTrue(tool_result["ok"])
        self.assertTrue(agent.audit.events[0]["success"])
        self.assertEqual(agent.audit.events[0]["decision"], "allow")

    def test_ask_policy_rejection_blocks_execution(self):
        agent, approvals, tool_result, _ = self.run_scenario(approval="deny")

        self.assertEqual(agent.tools.executed, [])
        self.assertEqual(len(approvals), 1)
        self.assertEqual(tool_result["error"], "用户拒绝执行该工具")
        self.assertEqual(agent.audit.events[0]["decision"], "deny")

    def test_ask_policy_approval_executes_tool(self):
        agent, approvals, tool_result, _ = self.run_scenario(approval="once")

        self.assertEqual(len(agent.tools.executed), 1)
        self.assertEqual(len(approvals), 1)
        self.assertTrue(tool_result["ok"])
        self.assertEqual(agent.audit.events[0]["decision"], "once")

    def test_session_approval_updates_permission_policy(self):
        agent, approvals, tool_result, _ = self.run_scenario(approval="session")

        next_decision = agent.permission_policy.decide("write_file", "high")
        self.assertEqual(len(agent.tools.executed), 1)
        self.assertEqual(len(approvals), 1)
        self.assertTrue(tool_result["ok"])
        self.assertEqual(next_decision.action, "allow")
        self.assertEqual(agent.audit.events[0]["decision"], "session")

    def test_skill_tool_is_bound_to_the_current_usage_turn(self):
        agent = FakeAgent({"allow": ["skill_view"]})
        agent.llm = FakeLLM("skill_view", {"name": "code-review"})
        agent.skill_usage = FakeSkillUsage()
        agent.conv_id = "conversation-1"
        agent.model = "test-model"
        agent.workspace = "."

        run_conversation_loop(agent, "review this change")

        self.assertEqual(agent.skill_usage.turns[0]["user_query"], "review this change")
        self.assertEqual(agent.skill_usage.events[0]["turn_id"], 41)
        self.assertEqual(agent.skill_usage.events[0]["skill_name"], "code-review")
        self.assertEqual(agent.skill_usage.events[0]["event_type"], "view")
        self.assertTrue(agent.skill_usage.events[0]["success"])

    def test_explicit_false_tool_status_is_recorded_as_failure(self):
        agent = FakeAgent({"allow": ["skill_run_script"]})
        agent.llm = FakeLLM(
            "skill_run_script",
            {"name": "codebase-inspection", "file_path": "scripts/fail.py"},
        )
        agent.tools.forced_result = json.dumps({"ok": False, "stderr": "failed"})
        agent.skill_usage = FakeSkillUsage()

        run_conversation_loop(agent, "run the inspection script")

        self.assertFalse(agent.audit.events[0]["success"])
        self.assertFalse(agent.skill_usage.events[0]["success"])
        self.assertEqual(agent.skill_usage.events[0]["error"], "failed")

    def test_large_tool_result_is_persisted_before_message_append(self):
        agent = FakeAgent({"allow": ["write_file"]})
        agent.tools.forced_result = "x" * 100_001

        run_conversation_loop(agent, "write the file")

        tool_message = next(message for message in agent.messages if message["role"] == "tool")
        self.assertIn(PERSISTED_OUTPUT_TAG, tool_message["content"])
        path_line = next(
            line for line in tool_message["content"].splitlines()
            if line.startswith("Full output saved to:")
        )
        file_path = path_line.split(":", 1)[1].strip()
        self.assertTrue(os.path.exists(file_path))


if __name__ == "__main__":
    unittest.main()
