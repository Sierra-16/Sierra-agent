import json
import tempfile
import unittest
from pathlib import Path

from aiagent.audit_logger import AuditLogger


class AuditLoggerTests(unittest.TestCase):
    def test_log_persists_jsonl_and_recent_reads_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audit.jsonl"
            logger = AuditLogger(path)

            record = logger.log({"tool": "powershell", "decision": "once"})

            self.assertTrue(path.exists())
            stored = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(stored["tool"], "powershell")
            self.assertEqual(stored["decision"], "once")
            self.assertIn("timestamp", stored)
            self.assertEqual(logger.recent(1), [record])

    def test_disabled_logger_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audit.jsonl"
            logger = AuditLogger(path, enabled=False)

            result = logger.log({"tool": "calculator"})

            self.assertIsNone(result)
            self.assertFalse(path.exists())
            self.assertEqual(logger.recent(), [])

    def test_rotation_keeps_recent_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "audit.jsonl"
            logger = AuditLogger(path, max_bytes=1024, backup_count=2)

            for index in range(8):
                logger.log({"index": index, "payload": "x" * 400})

            self.assertTrue(path.with_name("audit.jsonl.1").exists())
            self.assertEqual(
                [record["index"] for record in logger.recent(3)],
                [5, 6, 7],
            )


if __name__ == "__main__":
    unittest.main()
