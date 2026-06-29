import unittest

from aiagent.safety import SafetyGate, sanitize_arguments, sanitize_text


class SafetyRedactionTests(unittest.TestCase):
    def test_skill_reads_are_low_risk_and_execution_is_high_risk(self):
        gate = SafetyGate()

        self.assertEqual(gate.assess("read_file", {"file_path": "notes.txt"}).level, "low")
        self.assertEqual(gate.assess("web_fetch", {"url": "https://example.com"}).level, "low")
        self.assertEqual(gate.assess("web_search", {"query": "Sierra"}).level, "low")
        self.assertEqual(gate.assess("web_extract", {"urls": ["https://example.com"]}).level, "low")
        self.assertEqual(gate.assess("skills_list").level, "low")
        self.assertEqual(gate.assess("skill_render_template").level, "low")
        self.assertEqual(gate.assess("skill_usage_stats").level, "low")
        self.assertEqual(gate.assess("browser_fetch", {"url": "https://example.com"}).level, "low")
        self.assertEqual(gate.assess("file_info", {"path": "notes.txt"}).level, "low")
        self.assertEqual(gate.assess("session_search", {"query": "Sierra"}).level, "low")
        self.assertEqual(gate.assess("session_load", {"session_id": "abc"}).level, "low")
        self.assertEqual(gate.assess("git_inspect", {"action": "status"}).level, "low")
        self.assertEqual(gate.assess("project_inspect", {"path": "."}).level, "low")
        self.assertEqual(gate.assess("tool_search", {"query": "github"}).level, "low")
        self.assertEqual(gate.assess("tool_describe", {"name": "mcp__github__create_issue"}).level, "low")
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

    def test_terminal_is_high_risk_but_process_reads_are_low_risk(self):
        gate = SafetyGate()

        self.assertEqual(gate.assess("terminal", {"command": "dir"}).level, "high")
        self.assertEqual(gate.assess("process", {"action": "list"}).level, "low")
        self.assertEqual(gate.assess("process", {"action": "log"}).level, "low")
        self.assertEqual(gate.assess("process", {"action": "wait"}).level, "low")
        self.assertEqual(gate.assess("process", {"action": "kill"}).level, "high")

    def test_execute_code_and_browser_actions_have_risk_boundaries(self):
        gate = SafetyGate()

        self.assertEqual(gate.assess("execute_code", {"code": "print(1)"}).level, "high")
        self.assertEqual(gate.assess("browser_navigate", {"url": "https://example.com"}).level, "low")
        self.assertEqual(gate.assess("browser_snapshot").level, "low")
        self.assertEqual(gate.assess("browser_scroll").level, "low")
        self.assertEqual(gate.assess("browser_back").level, "low")
        self.assertEqual(gate.assess("browser_close").level, "low")
        self.assertEqual(gate.assess("browser_click", {"ref": "e1"}).level, "high")
        self.assertEqual(gate.assess("browser_type", {"ref": "e1", "text": "hello"}).level, "high")
        self.assertEqual(gate.assess("browser_press", {"key": "Enter"}).level, "high")
        self.assertEqual(gate.assess("browser_screenshot", {"path": "shot.png"}).level, "high")
        self.assertEqual(gate.assess("browser_console", {}).level, "low")
        self.assertEqual(gate.assess("browser_console", {"expression": "location.href"}).level, "high")

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
