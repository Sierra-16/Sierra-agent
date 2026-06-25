import tempfile
import unittest

from aiagent.session_db import SessionDB


class SessionDBTests(unittest.TestCase):
    def make_db(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db = SessionDB("sessions.sqlite3", base_dir=temp_dir.name)
        self.addCleanup(db.close)
        return db

    def test_replace_session_lists_and_loads_messages(self):
        db = self.make_db()
        db.replace_session(
            "s1",
            [
                {"role": "user", "content": "Plan a Guilin food trip"},
                {"role": "assistant", "content": "Try rice noodles first."},
            ],
            title="Guilin food",
            model="test-model",
            cwd="E:\\Sierra",
            usage={"input": 10, "output": 20},
        )

        sessions = db.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], "s1")
        self.assertEqual(sessions[0]["message_count"], 2)
        self.assertEqual(sessions[0]["input_tokens"], 10)

        messages = db.get_messages("s1")
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["content"], "Try rice noodles first.")

    def test_replace_session_preserves_supplied_timestamps(self):
        db = self.make_db()
        db.replace_session(
            "s1",
            [{"role": "user", "content": "old conversation"}],
            created_at=100.0,
            updated_at=200.0,
        )

        session = db.list_sessions()[0]
        self.assertEqual(session["created_at"], 100.0)
        self.assertEqual(session["updated_at"], 200.0)

    def test_replace_session_is_idempotent(self):
        db = self.make_db()
        db.replace_session("s1", [{"role": "user", "content": "old"}])
        db.replace_session("s1", [{"role": "user", "content": "new"}])

        self.assertEqual(db.list_sessions()[0]["message_count"], 1)
        self.assertEqual(db.get_messages("s1")[0]["content"], "new")

    def test_search_messages_finds_english_and_cjk_text(self):
        db = self.make_db()
        db.replace_session(
            "s1",
            [
                {"role": "user", "content": "I like quiet coding sessions"},
                {"role": "assistant", "content": "桂林米粉和漓江计划已经记录"},
            ],
            title="mixed",
        )

        english = db.search_messages("quiet coding")
        chinese = db.search_messages("桂林米粉")

        self.assertEqual(english[0]["session_id"], "s1")
        self.assertEqual(chinese[0]["session_id"], "s1")

    def test_tool_calls_round_trip(self):
        db = self.make_db()
        tool_calls = [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{\"path\":\"x\"}"},
        }]
        db.replace_session(
            "s1",
            [{"role": "assistant", "content": "", "tool_calls": tool_calls}],
        )

        messages = db.get_messages("s1")
        self.assertEqual(messages[0]["tool_calls"][0]["function"]["name"], "read_file")


if __name__ == "__main__":
    unittest.main()
