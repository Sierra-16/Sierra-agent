import tempfile
import unittest
from pathlib import Path

from aiagent.context_files import ContextFileLoader


class ContextFilesTests(unittest.TestCase):
    def test_loads_existing_project_context_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "SIERRA.md").write_text("project rules", encoding="utf-8")
            loader = ContextFileLoader(
                enabled=True,
                filenames=("SIERRA.md", "missing.md"),
                max_chars=1000,
                max_file_chars=1000,
            )

            result = loader.load(str(root))

        self.assertIn("Project Context Files", result.text)
        self.assertIn("project rules", result.text)
        self.assertEqual([block["path"] for block in result.blocks], ["SIERRA.md"])

    def test_enforces_file_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "SIERRA.md").write_text("a" * 1200, encoding="utf-8")
            loader = ContextFileLoader(
                enabled=True,
                filenames=("SIERRA.md",),
                max_chars=2000,
                max_file_chars=500,
            )

            result = loader.load(str(root))

        self.assertLessEqual(len(result.blocks[0]["content"]), 520)
        self.assertIn("truncated", result.text)


if __name__ == "__main__":
    unittest.main()
