import json
import os
import tempfile
import unittest

from aiagent.tools.file_operations_tool import (
    copy_path,
    delete_path,
    file_info,
    make_directory,
    move_path,
    patch_file,
)
from aiagent.tools.path_context import set_tool_workspace


class FileOperationsToolTests(unittest.TestCase):
    def setUp(self):
        self.previous_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = os.path.join(self.temp_dir.name, "workspace")
        os.makedirs(self.workspace)
        os.chdir(self.temp_dir.name)
        set_tool_workspace(self.workspace)

    def tearDown(self):
        os.chdir(self.previous_cwd)
        set_tool_workspace(self.previous_cwd)
        self.temp_dir.cleanup()

    def test_file_info_reports_missing_and_existing_paths(self):
        missing = json.loads(file_info("missing.txt"))
        self.assertFalse(missing["exists"])

        target = os.path.join(self.workspace, "note.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("hello")

        existing = json.loads(file_info("note.txt"))

        self.assertTrue(existing["exists"])
        self.assertTrue(existing["is_file"])
        self.assertEqual(existing["size"], 5)

    def test_patch_file_requires_unique_match_by_default(self):
        target = os.path.join(self.workspace, "note.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("same\nsame\n")

        result = json.loads(patch_file("note.txt", "same", "done"))

        self.assertIn("multiple", result["error"])

    def test_patch_file_can_replace_all_matches(self):
        target = os.path.join(self.workspace, "note.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write("same\nsame\n")

        result = json.loads(patch_file("note.txt", "same", "done", replace_all=True))

        self.assertEqual(result["replaced"], 2)
        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "done\ndone\n")

    def test_make_move_copy_and_delete_path(self):
        make_result = json.loads(make_directory("nested"))
        self.assertTrue(make_result["created"])

        source = os.path.join(self.workspace, "nested", "source.txt")
        with open(source, "w", encoding="utf-8") as f:
            f.write("data")

        copy_result = json.loads(copy_path("nested/source.txt", "copy.txt"))
        self.assertTrue(copy_result["copied"])
        self.assertTrue(os.path.exists(os.path.join(self.workspace, "copy.txt")))

        move_result = json.loads(move_path("copy.txt", "moved.txt"))
        self.assertTrue(move_result["moved"])
        self.assertFalse(os.path.exists(os.path.join(self.workspace, "copy.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.workspace, "moved.txt")))

        delete_result = json.loads(delete_path("moved.txt"))
        self.assertTrue(delete_result["deleted"])
        self.assertFalse(os.path.exists(os.path.join(self.workspace, "moved.txt")))

    def test_delete_directory_requires_recursive_for_non_empty_directory(self):
        os.makedirs(os.path.join(self.workspace, "nested"))
        with open(os.path.join(self.workspace, "nested", "file.txt"), "w", encoding="utf-8") as f:
            f.write("data")

        result = json.loads(delete_path("nested"))

        self.assertIn("not empty", result["error"])


if __name__ == "__main__":
    unittest.main()
