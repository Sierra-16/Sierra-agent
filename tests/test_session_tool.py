import json
import os
import tempfile
import unittest

from aiagent.session_db import SessionDB
from aiagent.tools.session_tool import (
    configure_session_tools,
    session_load,
    session_search,
)


class SessionToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "sessions.sqlite3")
        self.db = SessionDB(self.db_path)
        configure_session_tools(self.db)
        self.db.replace_session(
            "session-1",
            [
                {"role": "user", "content": "I like quiet green terminal themes"},
                {"role": "assistant", "content": "I will remember your visual preference."},
                {"role": "tool", "content": "large irrelevant output", "tool_name": "read_file"},
            ],
            title="Theme preference",
            model="test-model",
            cwd="E:/Sierra",
        )

    def tearDown(self):
        configure_session_tools(None)
        self.db.close()
        self.temp_dir.cleanup()

    def test_session_search_returns_compact_results(self):
        result = json.loads(session_search("green terminal", limit=3))

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["session_id"], "session-1")
        self.assertEqual(result["results"][0]["role"], "user")
        self.assertIn("green", result["results"][0]["content"])

    def test_session_load_returns_recent_messages(self):
        result = json.loads(session_load("session-1", limit=2))

        self.assertEqual(result["session"]["id"], "session-1")
        self.assertEqual(result["returned"], 2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["messages"][0]["role"], "assistant")

    def test_session_search_reports_missing_db(self):
        configure_session_tools(None)

        result = json.loads(session_search("anything"))

        self.assertIn("not available", result["error"])


if __name__ == "__main__":
    unittest.main()
