import json
import os
import tempfile
import unittest

from aiagent.tools.execute_code_tool import execute_code
from aiagent.tools.path_context import set_tool_workspace


class ExecuteCodeToolTests(unittest.TestCase):
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

    def test_execute_code_runs_python_in_workspace(self):
        result = json.loads(execute_code(
            "from pathlib import Path\n"
            "Path('answer.txt').write_text('42', encoding='utf-8')\n"
            "print(Path.cwd().name)\n"
        ))

        self.assertTrue(result["ok"], result.get("stderr"))
        self.assertIn("workspace", result["stdout"])
        with open(os.path.join(self.workspace, "answer.txt"), "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "42")

    def test_execute_code_reports_failure(self):
        result = json.loads(execute_code("raise SystemExit(3)"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], 3)

    def test_execute_code_can_keep_script(self):
        result = json.loads(execute_code("print('kept')", keep_script=True))

        self.assertTrue(result["ok"])
        self.assertTrue(os.path.exists(result["script_path"]))


if __name__ == "__main__":
    unittest.main()
