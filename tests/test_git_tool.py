import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from aiagent.tools.git_tool import git_inspect
from aiagent.tools.path_context import set_tool_workspace


class GitInspectToolTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git executable not available")
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmpdir.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        set_tool_workspace(str(self.workspace))
        self._git("init")
        self._git("config", "user.email", "sierra@example.local")
        self._git("config", "user.name", "Sierra Test")
        (self.repo / "tracked.txt").write_text("hello\n", encoding="utf-8")
        self._git("add", "tracked.txt")
        self._git("commit", "-m", "initial commit")

    def tearDown(self):
        set_tool_workspace(None)
        self.tmpdir.cleanup()

    def test_repo_status_diff_and_log(self):
        (self.repo / "tracked.txt").write_text("hello world\n", encoding="utf-8")
        (self.repo / "notes.md").write_text("new note\n", encoding="utf-8")

        repo = self._call("repo", workdir="repo")
        self.assertTrue(repo["ok"])
        self.assertEqual(Path(repo["repo_root"]).resolve(), self.repo.resolve())
        self.assertTrue(repo["dirty"])

        status = self._call("status", workdir="repo")
        self.assertTrue(status["ok"])
        self.assertEqual(status["summary"]["modified"], 1)
        self.assertEqual(status["summary"]["untracked"], 1)
        self.assertIn("tracked.txt", status["output"])
        self.assertIn("notes.md", status["output"])

        diff = self._call("diff", workdir="repo", paths=["tracked.txt"])
        self.assertTrue(diff["ok"])
        self.assertIn("-hello", diff["output"])
        self.assertIn("+hello world", diff["output"])
        self.assertEqual(diff["path_count"], 1)

        log = self._call("log", workdir="repo", limit=1)
        self.assertTrue(log["ok"])
        self.assertEqual(len(log["commits"]), 1)
        self.assertEqual(log["commits"][0]["subject"], "initial commit")

    def test_staged_diff_show_branches_and_truncation(self):
        (self.repo / "tracked.txt").write_text("hello\n" + ("x\n" * 3000), encoding="utf-8")
        self._git("add", "tracked.txt")

        staged = self._call("staged_diff", workdir="repo", max_chars=1000)
        self.assertTrue(staged["ok"])
        self.assertTrue(staged["truncated"])
        self.assertIn("tracked.txt", staged["stat"])

        show = self._call("show", workdir="repo", ref="HEAD", stat_only=True)
        self.assertTrue(show["ok"])
        self.assertIn("initial commit", show["output"])

        branches = self._call("branches", workdir="repo")
        self.assertTrue(branches["ok"])
        self.assertIn("master", branches["output"] + " main")

    def test_rejects_unsafe_refs_and_paths(self):
        bad_ref = self._call("log", workdir="repo", ref="-c")
        self.assertFalse(bad_ref["ok"])
        self.assertIn("ref", bad_ref["error"])

        absolute = self._call("status", workdir="repo", paths=[str(self.repo / "tracked.txt")])
        self.assertFalse(absolute["ok"])
        self.assertIn("relative", absolute["error"])

        parent = self._call("status", workdir="repo", paths=["../outside.txt"])
        self.assertFalse(parent["ok"])
        self.assertIn("relative", parent["error"])

    def test_reports_non_repo(self):
        outside = self.workspace / "outside"
        outside.mkdir()
        result = self._call("status", workdir="outside")
        self.assertFalse(result["ok"])
        self.assertIn("git repository", result["error"])

    def _call(self, action, **kwargs):
        return json.loads(git_inspect(action, **kwargs))

    def _git(self, *args):
        env = os.environ.copy()
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
