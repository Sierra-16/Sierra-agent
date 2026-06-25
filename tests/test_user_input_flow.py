import json
import unittest

from aiagent.conversation_loop import run_conversation_loop
from aiagent.permission_policy import PermissionPolicy
from aiagent.safety import SafetyGate
from aiagent.tools import registry


class FakeTools:
    def __init__(self):
        self.executed = []

    def get_definitions(self):
        return registry.get_definitions()

    def execute(self, name, arguments):
        self.executed.append((name, arguments))
        return json.dumps({"unexpected": True})


class FakeLLM:
    def __init__(self, arguments):
        self.arguments = arguments
        self.calls = 0

    def stream_chat(self, messages, tools, on_delta):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": None,
                "tool_calls": [{
                    "id": "input-call-1",
                    "type": "function",
                    "function": {
                        "name": "request_user_input",
                        "arguments": json.dumps(self.arguments, ensure_ascii=False),
                    },
                }],
                "usage": {"input": 1, "output": 1},
            }
        return {
            "content": "continued",
            "tool_calls": None,
            "usage": {"input": 1, "output": 1},
        }


class FakeAgent:
    def __init__(self, arguments):
        self.messages = []
        self.llm = FakeLLM(arguments)
        self.tools = FakeTools()
        self.safety = SafetyGate()
        self.permission_policy = PermissionPolicy()
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


class UserInputFlowTests(unittest.TestCase):
    def make_arguments(self):
        return {
            "question": "Choose a database",
            "options": [
                {"label": "SQLite", "description": "Local", "value": "sqlite"},
                {"label": "PostgreSQL", "description": "Server", "value": "postgres"},
            ],
            "allow_free_text": True,
        }

    def test_tool_is_registered_for_the_model(self):
        definitions = registry.get_definitions()
        names = [definition["function"]["name"] for definition in definitions]

        self.assertIn("request_user_input", names)

    def test_structured_answer_returns_to_model_without_normal_execution(self):
        agent = FakeAgent(self.make_arguments())
        requests = []

        result = run_conversation_loop(
            agent,
            "build an app",
            on_user_input=lambda request: requests.append(request) or {
                "value": "postgres",
                "label": "PostgreSQL",
                "free_text": False,
                "cancelled": False,
            },
        )

        tool_message = next(message for message in agent.messages if message["role"] == "tool")
        payload = json.loads(tool_message["content"])
        self.assertEqual(result, "continued")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["options"][1]["value"], "postgres")
        self.assertEqual(payload["status"], "answered")
        self.assertEqual(payload["answer"]["value"], "postgres")
        self.assertEqual(agent.tools.executed, [])

    def test_free_text_string_is_normalized(self):
        agent = FakeAgent(self.make_arguments())

        run_conversation_loop(
            agent,
            "build an app",
            on_user_input=lambda request: "Use MySQL instead",
        )

        tool_message = next(message for message in agent.messages if message["role"] == "tool")
        answer = json.loads(tool_message["content"])["answer"]
        self.assertEqual(answer["value"], "Use MySQL instead")
        self.assertTrue(answer["free_text"])

    def test_missing_callback_returns_cancelled_error(self):
        agent = FakeAgent(self.make_arguments())

        run_conversation_loop(agent, "build an app")

        tool_message = next(message for message in agent.messages if message["role"] == "tool")
        payload = json.loads(tool_message["content"])
        self.assertTrue(payload["cancelled"])
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
