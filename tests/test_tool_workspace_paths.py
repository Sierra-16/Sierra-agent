import json
import os
import tempfile
import unittest

from aiagent.tools.list_directory_tool import list_directory
from aiagent.tools.path_context import set_tool_workspace
from aiagent.tools.read_file_tool import read_file
from aiagent.tools.search_file_tool import search_files
from aiagent.tools.write_file_tool import write_file


class ToolWorkspacePathTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = os.path.join(self.temp_dir.name, "workspace")
        self.other_dir = os.path.join(self.temp_dir.name, "other")
        os.makedirs(self.workspace)
        os.makedirs(self.other_dir)
        os.chdir(self.other_dir)
        set_tool_workspace(self.workspace)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        set_tool_workspace(self.previous_cwd)
        self.temp_dir.cleanup()

    def test_read_file_resolves_relative_path_under_workspace(self):
        target = os.path.join(self.workspace, "note.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("hello from workspace")

        result = json.loads(read_file("note.txt"))

        self.assertEqual(result["file_path"], target)
        self.assertEqual(result["content"], "hello from workspace")

    def test_read_file_supports_line_pagination(self):
        target = os.path.join(self.workspace, "paged.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("one\ntwo\nthree\nfour\n")

        result = json.loads(read_file("paged.txt", offset=2, limit=2))

        self.assertEqual(result["content"], "two\nthree")
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_offset"], 4)

    def test_write_file_resolves_relative_path_under_workspace(self):
        result = json.loads(write_file("nested/out.txt", "saved"))
        target = os.path.join(self.workspace, "nested", "out.txt")

        self.assertEqual(result["file_path"], target)
        self.assertTrue(os.path.exists(target))
        self.assertFalse(os.path.exists(os.path.join(self.other_dir, "nested", "out.txt")))

    def test_list_directory_uses_workspace_for_dot(self):
        with open(os.path.join(self.workspace, "visible.txt"), "w", encoding="utf-8") as f:
            f.write("yes")
        with open(os.path.join(self.other_dir, "hidden.txt"), "w", encoding="utf-8") as f:
            f.write("no")

        result = json.loads(list_directory("."))

        self.assertEqual(result["dir_path"], self.workspace)
        self.assertIn("visible.txt (3 bytes)", result["files"])
        self.assertNotIn("hidden.txt (2 bytes)", result["files"])

    def test_search_files_uses_workspace_base(self):
        with open(os.path.join(self.workspace, "match.py"), "w", encoding="utf-8") as f:
            f.write("print('workspace')")
        with open(os.path.join(self.other_dir, "match.py"), "w", encoding="utf-8") as f:
            f.write("print('other')")

        result = json.loads(search_files("*.py"))

        self.assertEqual(result["dir_path"], self.workspace)
        self.assertEqual(result["matches"], [os.path.join(self.workspace, "match.py")])

    def test_search_files_supports_pagination(self):
        for name in ("a.py", "b.py", "c.py"):
            with open(os.path.join(self.workspace, name), "w", encoding="utf-8") as f:
                f.write(name)

        result = json.loads(search_files("*.py", offset=1, limit=1))

        self.assertEqual(result["matches"], [os.path.join(self.workspace, "b.py")])
        self.assertEqual(result["total"], 3)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_offset"], 2)

    def test_search_files_supports_content_search_with_context(self):
        os.makedirs(os.path.join(self.workspace, "pkg"))
        with open(os.path.join(self.workspace, "pkg", "agent.py"), "w", encoding="utf-8") as f:
            f.write("before\nclass Agent:\n    pass\nafter\n")
        with open(os.path.join(self.workspace, "config.json"), "w", encoding="utf-8") as f:
            f.write('{"secret": "class Agent"}')

        result = json.loads(
            search_files(
                "class Agent",
                target="content",
                path=".",
                file_glob="*.py",
                context=1,
            )
        )

        self.assertEqual(result["target"], "content")
        self.assertEqual(result["total"], 1)
        match = result["matches"][0]
        self.assertEqual(match["path"], "pkg/agent.py")
        self.assertEqual(match["line_number"], 2)
        self.assertEqual(match["before"][0]["line"], "before")
        self.assertEqual(match["after"][0]["line"], "    pass")
        self.assertNotIn("secret", json.dumps(result, ensure_ascii=False))

    def test_search_files_content_files_only_and_count_modes(self):
        with open(os.path.join(self.workspace, "a.py"), "w", encoding="utf-8") as f:
            f.write("needle\nneedle\n")
        with open(os.path.join(self.workspace, "b.py"), "w", encoding="utf-8") as f:
            f.write("needle\n")

        files_only = json.loads(
            search_files("needle", target="content", output_mode="files_only")
        )
        counts = json.loads(
            search_files("needle", target="content", output_mode="count")
        )

        self.assertEqual(files_only["total"], 2)
        self.assertEqual(
            {os.path.basename(path) for path in files_only["matches"]},
            {"a.py", "b.py"},
        )
        self.assertEqual(
            {os.path.basename(item["file_path"]): item["count"] for item in counts["matches"]},
            {"a.py": 2, "b.py": 1},
        )


if __name__ == "__main__":
    unittest.main()
