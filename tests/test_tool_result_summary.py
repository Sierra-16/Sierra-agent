import json
import unittest

from aiagent.conversation_loop import summarize_tool_result


class ToolResultSummaryTests(unittest.TestCase):
    def test_summarizes_successful_directory_result(self):
        result = summarize_tool_result(json.dumps({
            "directories": ["aiagent/", "tui/"],
            "files": ["main.py"],
        }))

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"], "2 folder(s), 1 file(s)")

    def test_summarizes_error_result(self):
        result = summarize_tool_result(json.dumps({
            "ok": False,
            "stderr": "permission denied",
        }))

        self.assertFalse(result["success"])
        self.assertIn("permission denied", result["summary"])

    def test_redacts_secret_like_output(self):
        result = summarize_tool_result(json.dumps({
            "message": "token=abc123 password=hunter2",
        }))

        self.assertTrue(result["success"])
        self.assertNotIn("abc123", result["summary"])
        self.assertNotIn("hunter2", result["summary"])


if __name__ == "__main__":
    unittest.main()
