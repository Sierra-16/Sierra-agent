import json
import os
import shutil
import tempfile
import unittest

from aiagent.tools.path_context import set_tool_workspace
from aiagent.tools.terminal_tool import process, terminal


@unittest.skipUnless(
    shutil.which("pwsh") or shutil.which("powershell"),
    "PowerShell is required for terminal tool tests",
)
class TerminalToolTests(unittest.TestCase):
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

    def test_terminal_runs_foreground_command(self):
        result = json.loads(terminal("Write-Output hello"))

        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello", result["stdout"])
        self.assertFalse(result["timed_out"])

    def test_terminal_background_process_can_be_waited_and_logged(self):
        started = json.loads(terminal(
            "Write-Output start; Start-Sleep -Milliseconds 100; Write-Output done",
            background=True,
        ))
        session_id = started["session_id"]

        waited = json.loads(process("wait", session_id=session_id, timeout=5))
        log = json.loads(process("log", session_id=session_id, offset=0, limit=10))

        self.assertEqual(waited["status"], "exited")
        self.assertEqual(waited["exit_code"], 0)
        self.assertIn("start", "\n".join(log["lines"]))
        self.assertIn("done", "\n".join(log["lines"]))

    def test_process_list_includes_background_session(self):
        started = json.loads(terminal("Write-Output listed", background=True))

        listed = json.loads(process("list"))
        json.loads(process("wait", session_id=started["session_id"], timeout=5))

        self.assertTrue(
            any(item["session_id"] == started["session_id"] for item in listed["processes"])
        )


if __name__ == "__main__":
    unittest.main()
