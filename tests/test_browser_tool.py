import json
import unittest

from aiagent.tools.browser_tool import browser_fetch


class BrowserToolTests(unittest.TestCase):
    def test_rejects_non_http_urls(self):
        result = json.loads(browser_fetch("file:///etc/passwd"))

        self.assertFalse(result["ok"])
        self.assertIn("http", result["error"])


if __name__ == "__main__":
    unittest.main()
