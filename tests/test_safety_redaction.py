import unittest

from aiagent.safety import SafetyGate, sanitize_arguments, sanitize_text


class SafetyRedactionTests(unittest.TestCase):
    def test_skill_reads_are_low_risk_and_execution_is_high_risk(self):
        gate = SafetyGate()

        self.assertEqual(gate.assess("read_file", {"file_path": "notes.txt"}).level, "low")
        self.assertEqual(gate.assess("web_fetch", {"url": "https://example.com"}).level, "low")
        self.assertEqual(gate.assess("web_search", {"query": "Sierra"}).level, "low")
        self.assertEqual(gate.assess("skills_list").level, "low")
        self.assertEqual(gate.assess("skill_render_template").level, "low")
        self.assertEqual(gate.assess("skill_usage_stats").level, "low")
        self.assertEqual(gate.assess("browser_fetch", {"url": "https://example.com"}).level, "low")
        self.assertEqual(gate.assess("file_info", {"path": "notes.txt"}).level, "low")
        self.assertEqual(gate.assess("mcp__docs__search", {"query": "Sierra"}).level, "low")
        self.assertEqual(gate.assess("skill_run_script").level, "high")
        self.assertEqual(gate.assess("skill_manage").level, "high")

    def test_file_mutation_tools_are_high_risk(self):
        gate = SafetyGate()

        for name in (
            "write_file",
            "patch_file",
            "delete_path",
            "move_path",
            "copy_path",
            "make_directory",
        ):
            self.assertEqual(gate.assess(name).level, "high")

    def test_cron_mutations_are_medium_risk(self):
        gate = SafetyGate()

        self.assertEqual(gate.assess("cron_list").level, "low")
        self.assertEqual(gate.assess("cron_add").level, "medium")
        self.assertEqual(gate.assess("cron_remove").level, "medium")

    def test_sensitive_file_reads_still_require_approval(self):
        gate = SafetyGate()

        self.assertEqual(gate.assess("read_file", {"file_path": ".env"}).level, "high")
        self.assertEqual(gate.assess("read_file", {"file_path": "config.json"}).level, "high")

    def test_redacts_api_key_with_space(self):
        self.assertNotIn(
            "secret-value",
            sanitize_text("API key=secret-value-123456"),
        )

    def test_redacts_bearer_token_inside_command(self):
        value = sanitize_arguments({
            "command": "curl -H 'Authorization: Bearer very-secret-token' https://example.com",
        })

        self.assertNotIn("very-secret-token", value)
        self.assertIn("Bearer ***", value)

    def test_redacts_common_secret_assignments(self):
        value = sanitize_text("token=abc123 password=hunter2 api_key=key-value")

        self.assertNotIn("abc123", value)
        self.assertNotIn("hunter2", value)
        self.assertNotIn("key-value", value)

    def test_redacts_sk_style_keys(self):
        value = sanitize_text("key is sk-abcdefghijklmnopqrstuvwxyz")

        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", value)
        self.assertIn("sk-***", value)


if __name__ == "__main__":
    unittest.main()
