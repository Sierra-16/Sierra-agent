from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .client import (
    MCPError,
    MCPProcessError,
    MCPRequestError,
    MCPTimeoutError,
    PROTOCOL_VERSION,
)


class MCPHTTPStatusError(MCPError):
    """Raised when a Streamable HTTP server returns an HTTP error."""

    def __init__(self, status: int, body: str):
        detail = f": {body[:300]}" if body else ""
        super().__init__(f"HTTP MCP request failed ({status}){detail}")
        self.status = status
        self.body = body


class MCPHTTPClient:
    """Streamable HTTP MCP client.

    It mirrors the small stdio client API Sierra uses: initialize,
    tools/list, tools/call, and close.
    """

    def __init__(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
    ):
        self.name = name
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout

        self._next_id = 0
        self._closed = False
        self._initialized = False
        self.session_id: str | None = None
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}

    @property
    def is_running(self) -> bool:
        return not self._closed

    def start(self) -> None:
        self._closed = False

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if self._closed:
            raise MCPProcessError(f"MCP HTTP server '{self.name}' is closed")

        request_id = self._new_id()
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        return self._post_jsonrpc(message, expected_id=request_id, timeout=timeout or self.timeout)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params
        self._post_jsonrpc(message, expected_id=None, timeout=self.timeout)

    def initialize(self) -> dict[str, Any]:
        self.start()
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "sierra",
                    "title": "Sierra AI Agent",
                    "version": "0.1.0",
                },
            },
        )
        self.server_info = result.get("serverInfo", {})
        self.server_capabilities = result.get("capabilities", {})
        self._initialized = True
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        if not self._initialized:
            self.initialize()
        result = self.request("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if not self._initialized:
            self.initialize()
        return self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )

    def close(self) -> None:
        if self.session_id:
            try:
                request = urllib.request.Request(
                    self.url,
                    headers=self._build_headers(accept="application/json", include_protocol=True),
                    method="DELETE",
                )
                urllib.request.urlopen(request, timeout=min(self.timeout, 5)).close()
            except urllib.error.HTTPError as exc:
                if exc.code not in (404, 405):
                    pass
            except OSError:
                pass

        self._closed = True
        self._initialized = False
        self.session_id = None

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _post_jsonrpc(
        self,
        message: dict[str, Any],
        expected_id: int | None,
        timeout: float,
    ) -> Any:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers=self._build_headers(
                accept="application/json, text/event-stream",
                content_type="application/json",
                include_protocol=self._initialized,
            ),
            method="POST",
        )

        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 and self.session_id:
                self.session_id = None
                self._initialized = False
            raise MCPHTTPStatusError(exc.code, body) from exc
        except TimeoutError as exc:
            raise MCPTimeoutError(f"HTTP MCP request timed out: {message.get('method')}") from exc
        except OSError as exc:
            raise MCPProcessError(f"HTTP MCP server '{self.name}' is unavailable: {exc}") from exc

        with response:
            if response.headers.get("Mcp-Session-Id"):
                self.session_id = response.headers.get("Mcp-Session-Id")

            status = response.getcode()
            body = response.read()

            if expected_id is None:
                if status in (200, 202, 204) and not body:
                    return None
                if status == 202:
                    return None

            if not body:
                if expected_id is None:
                    return None
                raise MCPProcessError(f"HTTP MCP server '{self.name}' returned an empty response")

            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            text = body.decode("utf-8", errors="replace")

            if content_type == "text/event-stream":
                return self._handle_sse_response(text, expected_id)

            if content_type == "application/json" or text.lstrip().startswith("{"):
                return self._handle_json_response(json.loads(text), expected_id)

            raise MCPProcessError(
                f"HTTP MCP server '{self.name}' returned unsupported content type: {content_type or 'unknown'}"
            )

    def _handle_json_response(self, message: dict[str, Any], expected_id: int | None) -> Any:
        if expected_id is None:
            return None

        if message.get("id") != expected_id:
            self._handle_incoming(message)
            raise MCPProcessError(f"HTTP MCP server '{self.name}' did not return response id {expected_id}")

        if "error" in message:
            raise MCPRequestError("http", message["error"])
        return message.get("result")

    def _handle_sse_response(self, text: str, expected_id: int | None) -> Any:
        for message in parse_sse_messages(text):
            if expected_id is not None and message.get("id") == expected_id:
                if "error" in message:
                    raise MCPRequestError("http", message["error"])
                return message.get("result")
            self._handle_incoming(message)

        if expected_id is None:
            return None
        raise MCPProcessError(f"HTTP MCP server '{self.name}' closed SSE without response id {expected_id}")

    def _handle_incoming(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method == "ping" and "id" in message:
            self._post_jsonrpc(
                {"jsonrpc": "2.0", "id": message["id"], "result": {}},
                expected_id=None,
                timeout=self.timeout,
            )
            return

        if "id" in message and method:
            self._post_jsonrpc(
                {
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": f"Unsupported client method: {method}",
                    },
                },
                expected_id=None,
                timeout=self.timeout,
            )

    def _build_headers(
        self,
        accept: str,
        content_type: str | None = None,
        include_protocol: bool = False,
    ) -> dict[str, str]:
        headers = dict(self.headers)
        headers["Accept"] = accept
        if content_type:
            headers["Content-Type"] = content_type
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if include_protocol:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    def __enter__(self) -> "MCPHTTPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def parse_sse_messages(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        raw = "\n".join(data_lines).strip()
        data_lines.clear()
        if raw:
            messages.append(json.loads(raw))

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    flush()
    return messages
