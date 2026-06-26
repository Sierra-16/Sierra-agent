import os
import tempfile
import unittest

from aiagent.skills.loader import Skill
from aiagent.skills.prompt_index import SkillPromptIndex


class SkillPromptIndexTests(unittest.TestCase):
    def make_skill(
        self,
        root,
        name,
        category,
        description=None,
        platforms=None,
        prerequisites=None,
        frontmatter=None,
    ):
        directory = os.path.join(root, category, name)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "SKILL.md")
        with open(path, "w", encoding="utf-8") as file:
            file.write("---\nname: test\ndescription: test\n---\n\nbody")
        return Skill(
            name=name,
            description=description or f"Description for {name}",
            triggers=[],
            category=category,
            body="SECRET FULL BODY",
            path=path,
            platforms=platforms or [],
            prerequisites=prerequisites or {},
            frontmatter=frontmatter or {},
        )

    def test_compact_categories_keep_names_but_drop_descriptions(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        skills = [
            self.make_skill(temp_dir.name, "debug", "development"),
            self.make_skill(temp_dir.name, "logo-design", "creative"),
        ]
        index = SkillPromptIndex({"compact_categories": ["creative"]})

        prompt = index.build(skills, available_tools=[])

        self.assertIn("debug: Description for debug", prompt)
        self.assertIn("[category: creative] [names only]: logo-design", prompt)
        self.assertNotIn("Description for logo-design", prompt)
        self.assertNotIn("SECRET FULL BODY", prompt)

    def test_platform_disabled_and_tool_conditions_filter_offer_index(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        disabled = self.make_skill(temp_dir.name, "disabled-one", "testing")
        unsupported = self.make_skill(
            temp_dir.name,
            "linux-only",
            "testing",
            platforms=["linux"],
        )
        conditioned = self.make_skill(
            temp_dir.name,
            "needs-browser",
            "testing",
            frontmatter={
                "metadata": {
                    "sierra": {"conditions": {"requires_tools": ["browser"]}}
                }
            },
        )
        index = SkillPromptIndex({
            "disabled": ["disabled-one"],
            "platform": "windows",
        })

        summaries = index.summaries(
            [disabled, unsupported, conditioned],
            available_tools=[],
            include_unavailable=True,
        )

        statuses = {item["name"]: item["readiness_status"] for item in summaries}
        self.assertEqual(statuses["disabled-one"], "disabled")
        self.assertEqual(statuses["linux-only"], "unsupported")
        self.assertEqual(statuses["needs-browser"], "condition_unmet")
        self.assertEqual(
            index.readiness(conditioned, available_tools=["browser"]).status,
            "available",
        )

    def test_missing_prerequisites_are_offered_as_setup_needed(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        skill = self.make_skill(
            temp_dir.name,
            "needs-setup",
            "testing",
            prerequisites={
                "commands": ["sierra-command-that-does-not-exist"],
                "environment_variables": ["SIERRA_TEST_MISSING_KEY"],
            },
        )
        index = SkillPromptIndex()

        readiness = index.readiness(skill, available_tools=[])

        self.assertTrue(readiness.offered)
        self.assertEqual(readiness.status, "setup_needed")
        self.assertEqual(
            readiness.missing_commands,
            ("sierra-command-that-does-not-exist",),
        )
        self.assertEqual(
            readiness.missing_environment_variables,
            ("SIERRA_TEST_MISSING_KEY",),
        )

    def test_category_description_is_loaded_without_skill_bodies(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        skill = self.make_skill(temp_dir.name, "research-one", "research")
        description_path = os.path.join(temp_dir.name, "research", "DESCRIPTION.md")
        with open(description_path, "w", encoding="utf-8") as file:
            file.write("---\ndescription: Evidence-backed research workflows.\n---\n")
        index = SkillPromptIndex()

        prompt = index.build([skill], available_tools=[])

        self.assertIn("[category: research] Evidence-backed research workflows.", prompt)

    def test_large_prompt_auto_compacts_categories(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        skills = [
            self.make_skill(
                temp_dir.name,
                f"visual-{index}",
                "creative",
                description="Long visual workflow description " * 10,
            )
            for index in range(8)
        ]
        skills.append(
            self.make_skill(
                temp_dir.name,
                "debugger",
                "development",
                description="Short debugging workflow",
            )
        )
        index = SkillPromptIndex({"max_prompt_chars": 2600})

        prompt = index.build(skills, available_tools=[])

        self.assertIn("[category: creative] [names only]:", prompt)
        self.assertIn("visual-0", prompt)
        self.assertNotIn("Long visual workflow description", prompt)
        self.assertIn("debugger", prompt)


if __name__ == "__main__":
    unittest.main()
