import os
import shutil
import tempfile
import unittest

from aiagent.agent import Agent
from aiagent.checkpoints import CheckpointManager


@unittest.skipUnless(shutil.which("git"), "git is required for checkpoint tests")
class CheckpointManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_dir = os.path.join(self.temp_dir.name, "sierra")
        self.workspace = os.path.join(self.temp_dir.name, "workspace")
        os.makedirs(self.base_dir)
        os.makedirs(self.workspace)

    def make_manager(self, enabled=True):
        return CheckpointManager(
            enabled=enabled,
            base_dir=self.base_dir,
            path="checkpoints/store",
            max_snapshots=5,
            max_files=100,
            timeout_seconds=10,
        )

    def test_takes_one_checkpoint_per_turn_per_workspace(self):
        manager = self.make_manager()
        note_path = os.path.join(self.workspace, "note.txt")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("first")

        first = manager.ensure_checkpoint(self.workspace, "before first write")
        second = manager.ensure_checkpoint(self.workspace, "before second write")

        self.assertTrue(first.taken, first.error)
        self.assertFalse(second.taken)

        with open(note_path, "w", encoding="utf-8") as f:
            f.write("second")
        manager.new_turn()
        third = manager.ensure_checkpoint(self.workspace, "before third write")

        self.assertTrue(third.taken, third.error)
        checkpoints = manager.list_checkpoints(self.workspace)
        self.assertGreaterEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[0]["reason"], "before third write")

    def test_disabled_manager_does_not_create_store(self):
        manager = self.make_manager(enabled=False)

        result = manager.ensure_checkpoint(self.workspace, "before write")

        self.assertFalse(result.taken)
        self.assertFalse(os.path.exists(os.path.join(self.base_dir, "checkpoints")))

    def test_restore_checkpoint(self):
        manager = self.make_manager()
        note_path = os.path.join(self.workspace, "note.txt")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("first")
        first = manager.ensure_checkpoint(self.workspace, "before first write")
        self.assertTrue(first.taken, first.error)

        with open(note_path, "w", encoding="utf-8") as f:
            f.write("second")
        manager.new_turn()
        second = manager.ensure_checkpoint(self.workspace, "before second write")
        self.assertTrue(second.taken, second.error)

        restored = manager.restore(self.workspace, first.commit)

        self.assertTrue(restored["success"], restored.get("error"))
        with open(note_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "first")

    def test_restore_rejects_path_traversal(self):
        manager = self.make_manager()
        note_path = os.path.join(self.workspace, "note.txt")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("first")
        first = manager.ensure_checkpoint(self.workspace, "before write")

        result = manager.restore(self.workspace, first.commit, "../outside.txt")

        self.assertFalse(result["success"])
        self.assertIn("escapes", result["error"])

    def test_agent_only_checkpoints_mutating_workspace_tools(self):
        agent = Agent.__new__(Agent)
        agent.workspace = self.workspace
        agent.checkpoints = self.make_manager()

        self.assertTrue(agent._tool_should_checkpoint(
            "write_file",
            {"file_path": "note.txt"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "patch_file",
            {"file_path": "note.txt"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "delete_path",
            {"path": "note.txt"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "move_path",
            {"source": "note.txt", "destination": "renamed.txt"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "copy_path",
            {"source": "note.txt", "destination": "copy.txt"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "make_directory",
            {"path": "nested"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "powershell",
            {"cwd": ".", "command": "Remove-Item note.txt"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "terminal",
            {"workdir": ".", "command": "Remove-Item note.txt"},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "execute_code",
            {"workdir": "."},
        ))
        self.assertTrue(agent._tool_should_checkpoint(
            "browser_screenshot",
            {"path": "shot.png"},
        ))
        self.assertFalse(agent._tool_should_checkpoint(
            "powershell",
            {"cwd": ".", "command": "Get-ChildItem"},
        ))
        self.assertFalse(agent._tool_should_checkpoint(
            "terminal",
            {"workdir": ".", "command": "Get-ChildItem"},
        ))
        self.assertFalse(agent._tool_should_checkpoint(
            "browser_screenshot",
            {},
        ))
        self.assertFalse(agent._tool_should_checkpoint(
            "read_file",
            {"file_path": "note.txt"},
        ))
        self.assertFalse(agent._tool_should_checkpoint(
            "file_info",
            {"path": "note.txt"},
        ))
        self.assertFalse(agent._tool_should_checkpoint(
            "write_file",
            {"file_path": os.path.join(self.temp_dir.name, "outside.txt")},
        ))


if __name__ == "__main__":
    unittest.main()
