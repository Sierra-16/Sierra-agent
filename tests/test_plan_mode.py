import json
import unittest

from fastapi.testclient import TestClient

from aiagent.agent import Agent
from aiagent.conversation_loop import run_conversation_loop
from aiagent.dashboard_api import create_dashboard_app
from aiagent.permission_policy import PermissionPolicy
from aiagent.safety import SafetyGate


class FakeTools:
    def __init__(self):
        self.executed = []

    def get_definitions(self):
        return []

    def execute(self, name, arguments):
        self.executed.append((name, arguments))
        return json.dumps({"ok": True, "tool": name}, ensure_ascii=False)

    def get_max_result_size(self, name, default=None):
        return default


class FakeAudit:
    def __init__(self):
        self.events = []

    def log(self, event):
        self.events.append(event)
        return event


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


class PlanModeAgent:
    def __init__(self, tool_name="write_file", arguments=None):
        self.messages = []
        self.llm = FakeLLM(tool_name, arguments or {"file_path": "demo.txt", "content": "hello"})
        self.tools = FakeTools()
        self.safety = SafetyGate()
        self.permission_policy = PermissionPolicy({"allow": [tool_name]})
        self.audit = FakeAudit()
        self.system_prompt = "system"
        self.max_iterations = 3
        self.max_compress_tokens = 100000
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.plan_mode_enabled = True

    def plan_mode_allows_tool(self, name, arguments=None):
        return Agent.plan_mode_allows_tool(self, name, arguments)

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def compress_messages(self):
        return None

    def auto_remember(self, user_message, assistant_response):
        return {"saved": []}


class DashboardPlanAgent:
    model = "test-model"
    workspace = "E:\\workspace"
    sierra_dir = "E:\\Sierra"
    messages = []

    def __init__(self):
        self.plan_mode_enabled = False

    def set_plan_mode(self, enabled):
        self.plan_mode_enabled = bool(enabled)
        return self.plan_mode_status()

    def plan_mode_status(self):
        return Agent.plan_mode_status(self)

    def refresh_context_estimate(self):
        return None

    def usage_snapshot(self):
        return {"input": 0, "output": 0, "context": 0, "context_window": 1000}

    def list_conversations(self):
        return []


class AgentPlanModeTests(unittest.TestCase):
    def test_plan_mode_blocks_mutating_tool_before_policy_prompt(self):
        agent = PlanModeAgent("write_file")
        events = []

        result = run_conversation_loop(
            agent,
            "write the file",
            on_status=events.append,
            on_tool_approval=lambda request: "once",
        )

        tool_message = next(message for message in agent.messages if message["role"] == "tool")
        payload = json.loads(tool_message["content"])
        self.assertEqual(result, "done")
        self.assertEqual(agent.tools.executed, [])
        self.assertTrue(payload["plan_mode"])
        self.assertIn("Plan Mode", payload["error"])
        self.assertEqual(agent.audit.events[0]["policy_action"], "plan_mode")
        self.assertTrue(any(event["type"] == "plan_mode_blocked" for event in events))

    def test_plan_mode_allows_read_only_tools(self):
        agent = PlanModeAgent("read_file", {"file_path": "README.md"})

        run_conversation_loop(agent, "read the file")

        self.assertEqual(agent.tools.executed, [("read_file", {"file_path": "README.md"})])


class DashboardPlanModeTests(unittest.TestCase):
    def test_web_api_toggles_plan_mode_without_command(self):
        agent = DashboardPlanAgent()
        app = create_dashboard_app(
            agent,
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        enabled = client.post("/api/mode/plan", json={"enabled": True})
        dashboard = client.get("/api/dashboard")

        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json()["mode"]["plan_mode"]["enabled"])
        self.assertTrue(dashboard.json()["mode"]["plan_mode"]["enabled"])


if __name__ == "__main__":
    unittest.main()
