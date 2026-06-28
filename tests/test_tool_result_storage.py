import os
import unittest

from aiagent.tools.tool_result_storage import (
    PERSISTED_OUTPUT_TAG,
    maybe_persist_tool_result,
)


class ToolResultStorageTests(unittest.TestCase):
    def test_small_result_stays_inline(self):
        result = maybe_persist_tool_result(
            "small",
            tool_name="demo",
            tool_call_id="call-1",
            threshold=100,
        )

        self.assertEqual(result, "small")

    def test_large_result_is_persisted_with_preview(self):
        content = "line\n" + ("x" * 200)
        result = maybe_persist_tool_result(
            content,
            tool_name="demo",
            tool_call_id="call-2",
            threshold=50,
            preview_size=20,
        )

        self.assertIn(PERSISTED_OUTPUT_TAG, result)
        path_line = next(
            line for line in result.splitlines()
            if line.startswith("Full output saved to:")
        )
        file_path = path_line.split(":", 1)[1].strip()
        self.assertTrue(os.path.exists(file_path))
        with open(file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), content)


if __name__ == "__main__":
    unittest.main()
