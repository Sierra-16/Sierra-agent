import json
import unittest

from scripts.run_live_skill_eval import _evaluate_case


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, messages, tools=None):
        return self.responses.pop(0)


class FakeTools:
    def __init__(self):
        self.executed = []

    def get_definitions(self):
        return [{"type": "function", "function": {"name": "skill_view"}}]

    def execute(self, name, arguments):
        self.executed.append((name, arguments))
        return json.dumps({"name": arguments.get("name"), "content": "rules"})


class FakeAgent:
    def __init__(self, responses):
        self.system_prompt = "skills"
        self.llm = FakeLLM(responses)
        self.tools = FakeTools()


def response(tool_name=None, arguments=None):
    tool_calls = None
    if tool_name:
        tool_calls = [{
            "id": "call-1",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(arguments or {}),
            },
        }]
    return {
        "content": None,
        "tool_calls": tool_calls,
        "usage": {"input": 10, "output": 2},
    }


class LiveSkillEvaluationTests(unittest.TestCase):
    def test_records_safe_skill_view_selection(self):
        agent = FakeAgent([response("skill_view", {"name": "code-review"})])

        selected, stopped_on, usage = _evaluate_case(agent, "review", 3)

        self.assertEqual(selected, ["code-review"])
        self.assertEqual(stopped_on, "")
        self.assertEqual(agent.tools.executed[0][0], "skill_view")
        self.assertEqual(usage, {"input": 10, "output": 2})

    def test_stops_before_executing_non_discovery_tool(self):
        agent = FakeAgent([response("powershell", {"command": "Remove-Item demo"})])

        selected, stopped_on, _ = _evaluate_case(agent, "danger", 3)

        self.assertEqual(selected, [])
        self.assertEqual(stopped_on, "powershell")
        self.assertEqual(agent.tools.executed, [])


if __name__ == "__main__":
    unittest.main()
