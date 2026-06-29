import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from aiagent.tools.path_context import set_tool_workspace
from aiagent.tools.project_tool import project_inspect


class ProjectInspectToolTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmpdir.name)
        self.project = self.workspace / "sample"
        self.project.mkdir()
        set_tool_workspace(str(self.workspace))

        (self.project / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (self.project / "requirements.txt").write_text("openai\nPyYAML>=6\n", encoding="utf-8")
        (self.project / "README.md").write_text("# Sample\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("# Agent rules\n", encoding="utf-8")
        (self.project / "config.json").write_text('{"api_key": "secret"}\n', encoding="utf-8")
        (self.project / "config.example.json").write_text('{"api_key": "YOUR_KEY"}\n', encoding="utf-8")
        (self.project / "tests").mkdir()
        (self.project / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        (self.project / "frontend").mkdir()
        (self.project / "frontend" / "AGENTS.md").write_text("# Frontend rules\n", encoding="utf-8")
        (self.project / ".cursor" / "rules").mkdir(parents=True)
        (self.project / ".cursor" / "rules" / "style.mdc").write_text("Use strict TS\n", encoding="utf-8")
        (self.project / "src").mkdir()
        (self.project / "src" / "main.tsx").write_text("import React from 'react';\n", encoding="utf-8")
        (self.project / "package.json").write_text(
            json.dumps(
                {
                    "name": "sample-app",
                    "scripts": {
                        "dev": "vite",
                        "test": "vitest",
                        "build": "vite build",
                        "typecheck": "tsc --noEmit",
                    },
                    "dependencies": {"@vitejs/plugin-react": "^1.0.0", "react": "^18.0.0"},
                    "devDependencies": {"typescript": "^5.0.0", "vite": "^5.0.0"},
                }
            ),
            encoding="utf-8",
        )
        (self.project / "package-lock.json").write_text("{}", encoding="utf-8")
        (self.project / "node_modules").mkdir()
        (self.project / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")

    def tearDown(self):
        set_tool_workspace(None)
        self.tmpdir.cleanup()

    def test_builds_compact_project_map_without_reading_sensitive_config(self):
        result = self._inspect(include_git=False)

        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["project_root"]).resolve(), self.project.resolve())
        self.assertTrue(any(item["language"] == "Python" for item in result["languages"]))
        self.assertTrue(any(item["language"] == "TypeScript" for item in result["languages"]))

        framework_names = {item["name"] for item in result["frameworks"]}
        self.assertIn("python", framework_names)
        self.assertIn("node", framework_names)
        self.assertIn("react", framework_names)
        self.assertIn("vite", framework_names)
        self.assertIn("typescript", framework_names)

        key_files = {item["path"]: item for item in result["key_files"]}
        self.assertIn("config.json", key_files)
        self.assertTrue(key_files["config.json"]["sensitive"])
        self.assertNotIn("secret", json.dumps(result, ensure_ascii=False))
        top_dirs = {item["path"]: item for item in result["top_level"]["directories"]}
        self.assertIn("node_modules", top_dirs)
        self.assertTrue(top_dirs["node_modules"]["skipped"])
        self.assertEqual(
            result["context_files"]["selected_startup_file"]["path"],
            "AGENTS.md",
        )
        context_paths = {
            item["path"]
            for item in (
                result["context_files"]["startup_candidates"]
                + result["context_files"]["subdirectory_hints"]
            )
        }
        self.assertIn("frontend/AGENTS.md", context_paths)
        self.assertIn(".cursor/rules/style.mdc", context_paths)
        self.assertEqual(result["context_files"]["style"], "hermes-inspired progressive disclosure")
        self.assertTrue(any(item["tool"] == "git_inspect" for item in result["follow_up_tools"]))

        run_commands = {item["command"] for item in result["commands"]["run"]}
        test_commands = {item["command"] for item in result["commands"]["test"]}
        build_commands = {item["command"] for item in result["commands"]["build"]}
        self.assertIn("python main.py", run_commands)
        self.assertIn("python -m unittest discover -s tests", test_commands)
        self.assertIn("npm run test", test_commands)
        self.assertIn("npm run build", build_commands)

        node_manifest = result["manifests"]["node"][0]
        self.assertEqual(node_manifest["name"], "sample-app")
        self.assertIn("react", node_manifest["dependencies"])

    def test_scan_truncation_is_reported(self):
        result = self._inspect(include_git=False, max_files=100)

        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["scan"]["files"], 1)
        self.assertFalse(result["scan"]["truncated"])

    def test_git_summary_when_repository_exists(self):
        if not shutil.which("git"):
            self.skipTest("git executable not available")

        self._git("init")
        self._git("config", "user.email", "sierra@example.local")
        self._git("config", "user.name", "Sierra Test")
        self._git("add", "main.py")
        self._git("commit", "-m", "initial")
        (self.project / "main.py").write_text("print('changed')\n", encoding="utf-8")

        result = self._inspect()

        self.assertTrue(result["git"]["enabled"])
        self.assertTrue(result["git"]["is_repo"])
        self.assertTrue(result["git"]["dirty"])
        self.assertEqual(result["git"]["summary"]["modified"], 1)

    def test_non_project_path_reports_error(self):
        result = json.loads(project_inspect("missing"))

        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

    def _inspect(self, **kwargs):
        return json.loads(project_inspect("sample", **kwargs))

    def _git(self, *args):
        env = os.environ.copy()
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        return subprocess.run(
            ["git", *args],
            cwd=self.project,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
