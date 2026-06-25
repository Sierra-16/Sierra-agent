import json
import os
import tempfile
import unittest

from aiagent.skills.loader import SkillLoader, set_skill_loader, set_skills
from aiagent.skills.manager import SkillManager
from aiagent.skills.prompt_index import SkillPromptIndex
from aiagent.tools.skill_view_tool import (
    configure_skill_tools,
    skill_render_template,
    skill_run_script,
    skill_view,
    skills_list,
)


class SkillLoaderTests(unittest.TestCase):
    def make_skill(self, root, category, folder, name, body="instructions"):
        directory = os.path.join(root, category, folder)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "SKILL.md")
        with open(path, "w", encoding="utf-8") as file:
            file.write(
                "---\n"
                f"name: {name}\n"
                f"description: Use {name} for tests.\n"
                "metadata:\n"
                "  sierra:\n"
                "    triggers: [demo, inspect]\n"
                "---\n\n"
                f"{body}\n"
            )
        return directory

    def activate(self, loader):
        loader.load()
        set_skill_loader(loader)
        self.addCleanup(lambda: set_skill_loader(None))

    def test_category_comes_from_top_level_directory(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.make_skill(temp_dir.name, "software-development", "demo", "demo")

        skills = SkillLoader(temp_dir.name).load()

        self.assertEqual(skills[0].category, "software-development")
        self.assertTrue(skills[0].path.endswith("SKILL.md"))
        self.assertEqual(skills[0].triggers, ["demo", "inspect"])

    def test_duplicate_names_are_reported_and_skipped(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.make_skill(temp_dir.name, "a", "duplicate", "duplicate")
        self.make_skill(temp_dir.name, "b", "duplicate", "duplicate")
        loader = SkillLoader(temp_dir.name)

        skills = loader.load()

        self.assertEqual(len(skills), 1)
        self.assertIn("duplicate skill name", loader.errors[0])

    def test_skill_view_supports_pagination_without_silent_truncation(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.make_skill(
            temp_dir.name,
            "writing",
            "long-skill",
            "long-skill",
            body="x" * 15000,
        )
        skills = SkillLoader(temp_dir.name).load()
        set_skills(skills)
        self.addCleanup(lambda: set_skills([]))

        first = json.loads(skill_view("long-skill"))
        second = json.loads(skill_view(
            "long-skill",
            offset=first["next_offset"],
        ))

        self.assertTrue(first["truncated"])
        self.assertEqual(len(first["body"]), 12000)
        self.assertFalse(second["truncated"])
        self.assertEqual(first["body"] + second["body"], "x" * 15000)

    def test_resources_are_discovered_and_read_safely(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        skill_dir = self.make_skill(temp_dir.name, "research", "demo", "demo")
        reference_dir = os.path.join(skill_dir, "references")
        os.makedirs(reference_dir)
        with open(os.path.join(reference_dir, "guide.md"), "w", encoding="utf-8") as file:
            file.write("evidence checklist")
        loader = SkillLoader(temp_dir.name)
        self.activate(loader)

        result = json.loads(skill_view("demo", file_path="references/guide.md"))
        blocked = json.loads(skill_view("demo", file_path="references/../../secret.txt"))

        self.assertEqual(result["content"], "evidence checklist")
        self.assertEqual(result["source"], "references/guide.md")
        self.assertIn("Parent path traversal", blocked["error"])
        self.assertEqual(loader.get("demo").resources[0]["kind"], "references")

    def test_skill_list_filters_without_loading_full_bodies(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.make_skill(temp_dir.name, "research", "research-one", "research-one")
        self.make_skill(temp_dir.name, "writing", "writing-two", "writing-two")
        loader = SkillLoader(temp_dir.name)
        self.activate(loader)

        payload = json.loads(skills_list(category="research", query="inspect"))

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["skills"][0]["name"], "research-one")
        self.assertNotIn("body", payload["skills"][0])

    def test_offer_index_hides_disabled_skills_from_tools(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.make_skill(temp_dir.name, "research", "hidden-skill", "hidden-skill")
        loader = SkillLoader(temp_dir.name)
        self.activate(loader)
        index = SkillPromptIndex({"disabled": ["hidden-skill"]})
        configure_skill_tools(temp_dir.name, index)
        self.addCleanup(lambda: configure_skill_tools(None, None))

        listing = json.loads(skills_list())
        viewed = json.loads(skill_view("hidden-skill"))

        self.assertEqual(listing["count"], 0)
        self.assertIn("not available", viewed["error"])

    def test_template_render_reports_unresolved_variables(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        skill_dir = self.make_skill(temp_dir.name, "creative", "demo", "demo")
        template_dir = os.path.join(skill_dir, "templates")
        os.makedirs(template_dir)
        with open(os.path.join(template_dir, "note.md"), "w", encoding="utf-8") as file:
            file.write("# {{title}}\n{{body}}")
        loader = SkillLoader(temp_dir.name)
        self.activate(loader)

        payload = json.loads(skill_render_template(
            "demo",
            "templates/note.md",
            {"title": "Sierra"},
        ))

        self.assertEqual(payload["content"], "# Sierra\n{{body}}")
        self.assertEqual(payload["unresolved_variables"], ["body"])

    def test_python_skill_script_runs_without_shell_parsing(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        skill_dir = self.make_skill(temp_dir.name, "tools", "demo", "demo")
        scripts_dir = os.path.join(skill_dir, "scripts")
        os.makedirs(scripts_dir)
        with open(os.path.join(scripts_dir, "echo.py"), "w", encoding="utf-8") as file:
            file.write("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
        loader = SkillLoader(temp_dir.name)
        self.activate(loader)
        configure_skill_tools(temp_dir.name)

        payload = json.loads(skill_run_script(
            "demo",
            "scripts/echo.py",
            ["hello world", "&& not-a-shell"],
        ))

        self.assertTrue(payload["ok"])
        self.assertEqual(json.loads(payload["stdout"]), ["hello world", "&& not-a-shell"])

    def test_skill_manager_lifecycle_reloads_registry(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        loader = SkillLoader(temp_dir.name)
        loader.load()

        def reload_skills():
            loader.reload()
            return {"count": len(loader.skills), "errors": loader.errors}

        manager = SkillManager(loader, reload_skills)
        manager.execute(
            "create",
            "managed-skill",
            category="testing",
            description="Managed test skill.",
            content="# Managed\n\nFollow the test.",
        )
        manager.execute(
            "write_resource",
            "managed-skill",
            file_path="references/checklist.md",
            content="check one",
        )

        self.assertIsNotNone(loader.get("managed-skill"))
        self.assertEqual(loader.get("managed-skill").resources[0]["file_path"], "references/checklist.md")

        manager.execute(
            "remove_resource",
            "managed-skill",
            file_path="references/checklist.md",
        )
        manager.execute("delete", "managed-skill")
        self.assertIsNone(loader.get("managed-skill"))

    def test_project_companion_skills_load_without_errors(self):
        loader = SkillLoader()

        skills = loader.load()
        names = {skill.name for skill in skills}

        self.assertEqual(loader.errors, [])
        self.assertTrue({
            "companion-dialogue",
            "decision-support",
            "memory-curation",
            "workspace-organizer",
            "travel-planning",
        }.issubset(names))
        architecture = loader.get("architecture-diagram")
        self.assertTrue(any(item["kind"] == "templates" for item in architecture.resources))
        inspection = loader.get("codebase-inspection")
        self.assertTrue(any(item["executable"] for item in inspection.resources))


if __name__ == "__main__":
    unittest.main()
