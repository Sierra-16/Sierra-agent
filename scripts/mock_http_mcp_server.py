"""Tiny Streamable HTTP MCP server for Sierra smoke tests."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back from a mock Streamable HTTP MCP server.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to echo."}},
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "Add two numbers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    },
]


def jsonrpc_result(request_id, payload: dict) -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "result": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def tool_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def handle_tool_call(name: str, arguments: dict) -> dict:
    if name == "echo":
        return tool_result(str(arguments.get("text", "")))
    if name == "add":
        return tool_result(str(float(arguments.get("a", 0)) + float(arguments.get("b", 0))))
    return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "SierraMockHTTPMCP/0.1"

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        message = json.loads(body.decode("utf-8"))
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if request_id is None:
            self.send_response(202)
            self.end_headers()
            return

        if method == "initialize":
            payload = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sierra-mock-http-mcp", "version": "0.1.0"},
            }
            self.send_json(jsonrpc_result(request_id, payload), session_id="mock-http-session")
            return

        if method == "tools/list":
            self.send_json(jsonrpc_result(request_id, {"tools": TOOLS}))
            return

        if method == "tools/call":
            result = handle_tool_call(params.get("name", ""), params.get("arguments") or {})
            self.send_json(jsonrpc_result(request_id, result))
            return

        self.send_json(json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }).encode("utf-8"), status=200)

    def do_GET(self) -> None:
        self.send_response(405)
        self.end_headers()

    def do_DELETE(self) -> None:
        self.send_response(204)
        self.end_headers()

    def send_json(self, body: bytes, status: int = 200, session_id: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock HTTP MCP listening on http://127.0.0.1:{port}/mcp", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
