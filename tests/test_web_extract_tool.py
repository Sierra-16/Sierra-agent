import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from aiagent.tools.web_extract_tool import web_extract


class WebExtractToolTests(unittest.TestCase):
    def test_rejects_non_http_urls(self):
        result = json.loads(web_extract(["file:///etc/passwd"]))

        self.assertFalse(result["results"][0]["ok"])
        self.assertIn("http", result["results"][0]["error"])

    def test_extracts_html_as_markdown(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"""
                    <html>
                      <head><title>Extract Test</title></head>
                      <body>
                        <h1>Hello</h1>
                        <p>Sierra reads this page.</p>
                        <a href="/next">Next page</a>
                      </body>
                    </html>
                    """
                )

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = json.loads(web_extract([f"http://127.0.0.1:{server.server_port}/"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        page = result["results"][0]
        self.assertTrue(page["ok"], page.get("error"))
        self.assertEqual(page["title"], "Extract Test")
        self.assertIn("# Hello", page["markdown"])
        self.assertIn("Sierra reads this page", page["markdown"])
        self.assertEqual(page["links"][0]["text"], "Next page")


if __name__ == "__main__":
    unittest.main()
