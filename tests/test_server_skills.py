import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.server import run_server


class FakeSkill:
    def __init__(self, name):
        self.name = name

    def summary(self):
        return {
            "name": self.name,
            "description": "Test skill",
            "category": "testing",
            "resource_counts": {"references": 1},
        }


class FakeSkillAgent:
    def __init__(self):
        self.skills = [FakeSkill("demo")]
        self.skill_loader = SimpleNamespace(errors=[])
        self.reload_calls = 0

    def reload_skills(self):
        self.reload_calls += 1
        return {
            "ok": True,
            "skills": [skill.summary() for skill in self.skills],
            "errors": [],
        }

    def skill_summaries(self, include_unavailable=False):
        return [skill.summary() for skill in self.skills]

    def skill_usage_stats(self, limit=20):
        return {
            "enabled": True,
            "total_turns": 4,
            "total_events": 3,
            "skill_load_rate": 0.5,
            "success_rate": 1.0,
            "skills": [{
                "skill_name": "demo",
                "views": 3,
                "renders": 0,
                "script_runs": 0,
                "failures": 0,
            }],
        }

    def close(self):
        pass


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


class ServerSkillCommandTests(unittest.TestCase):
    def test_list_and_reload_skills(self):
        agent = FakeSkillAgent()

        events = run_commands(agent, [
            {"cmd": "skills"},
            {"cmd": "skills_reload"},
        ])

        self.assertEqual([event["type"] for event in events], ["skills", "skills"])
        self.assertEqual(events[0]["skills"][0]["name"], "demo")
        self.assertTrue(events[1]["reloaded"])
        self.assertEqual(agent.reload_calls, 1)

    def test_skill_stats_are_formatted_for_the_tui(self):
        events = run_commands(FakeSkillAgent(), [{"cmd": "skills_stats"}])

        self.assertEqual(events[0]["type"], "skills_stats")
        self.assertIn("4 turns", events[0]["text"])
        self.assertIn("demo", events[0]["text"])


if __name__ == "__main__":
    unittest.main()
