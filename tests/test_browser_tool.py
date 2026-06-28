import json
import unittest
from unittest.mock import patch

from aiagent.tools import browser_tool
from aiagent.tools.browser_tool import browser_fetch


class BrowserToolTests(unittest.TestCase):
    def test_rejects_non_http_urls(self):
        result = json.loads(browser_fetch("file:///etc/passwd"))

        self.assertFalse(result["ok"])
        self.assertIn("http", result["error"])

    def test_browser_navigate_reports_missing_backend_cleanly(self):
        with patch.object(browser_tool.browser_session, "ensure_page", return_value=(None, "missing backend")):
            result = json.loads(browser_tool.browser_navigate("https://example.com"))

        self.assertFalse(result["ok"])
        self.assertIn("missing backend", result["error"])

    def test_browser_snapshot_reports_missing_backend_cleanly(self):
        with patch.object(browser_tool.browser_session, "ensure_page", return_value=(None, "missing backend")):
            result = json.loads(browser_tool.browser_snapshot())

        self.assertFalse(result["ok"])
        self.assertIn("missing backend", result["error"])

    def test_browser_ref_mapping_prefers_snapshot_refs(self):
        browser_tool.browser_session.remember_refs({"e1": "#submit"})

        self.assertEqual(browser_tool.browser_session.selector_for("e1"), "#submit")
        self.assertEqual(browser_tool.browser_session.selector_for(".fallback"), ".fallback")


if __name__ == "__main__":
    unittest.main()
