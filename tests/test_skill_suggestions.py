import unittest

from aiagent.skill_suggestions import suggest_skill_from_turn


class SkillSuggestionTests(unittest.TestCase):
    def test_suggests_skill_for_repeated_tool_workflow(self):
        suggestion = suggest_skill_from_turn(
            "以后经常要这样整理旅行计划",
            "done",
            [
                {"role": "assistant", "tool_calls": [
                    {"function": {"name": "read_file"}},
                    {"function": {"name": "web_search"}},
                ]},
                {"role": "assistant", "tool_calls": [
                    {"function": {"name": "write_file"}},
                ]},
            ],
        )

        self.assertIsNotNone(suggestion)
        self.assertIn("Skill", suggestion.to_text())

    def test_skips_small_plain_chat(self):
        suggestion = suggest_skill_from_turn("hello", "hi", [])

        self.assertIsNone(suggestion)


if __name__ == "__main__":
    unittest.main()
