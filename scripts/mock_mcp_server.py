"""Tiny stdio MCP server for Sierra smoke tests.

Run it through Sierra's mcpServers config to verify initialize,
tools/list, and tools/call without installing any external server.
"""
from __future__ import annotations

import json
import sys


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def result(request_id, payload: dict) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": payload})


def error(request_id, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


def tool_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back from a mock MCP server.",
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


def handle_call(name: str, arguments: dict) -> dict:
    if name == "echo":
        return tool_result(str(arguments.get("text", "")))
    if name == "add":
        return tool_result(str(float(arguments.get("a", 0)) + float(arguments.get("b", 0))))
    return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue

        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            result(request_id, {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sierra-mock-mcp", "version": "0.1.0"},
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            result(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            result(request_id, handle_call(params.get("name", ""), params.get("arguments") or {}))
        elif method == "ping":
            result(request_id, {})
        elif request_id is not None:
            error(request_id, -32601, f"Unknown method: {method}")


if __name__ == "__main__":
    main()
