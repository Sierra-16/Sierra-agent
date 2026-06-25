from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any


PROTOCOL_VERSION = "2025-06-18"


class MCPError(Exception):
    """Base error for MCP client failures."""


class MCPProcessError(MCPError):
    """Raised when the MCP server process cannot be used."""


class MCPRequestError(MCPError):
    """Raised when the MCP server returns a JSON-RPC error."""

    def __init__(self, method: str, error: dict[str, Any]):
        self.method = method
        self.error = error
        message = error.get("message", "MCP request failed")
        code = error.get("code", "unknown")
        super().__init__(f"{method} failed ({code}): {message}")


class MCPTimeoutError(MCPError):
    """Raised when a request does not receive a response in time."""


class MCPClient:
    """Small stdio MCP client.

    This class intentionally implements only the core pieces first:
    process startup, JSON-RPC request/notification, initialize,
    tools/list, tools/call, and shutdown.
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 20.0,
    ):
        self.name = name
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env
        self.timeout = timeout

        self.process: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._request_lock = threading.Lock()
        self._stdout_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._initialized = False
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.is_running:
            return

        self.process = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env={**os.environ, **self.env} if self.env else None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a JSON-RPC request and wait for the matching response."""
        with self._request_lock:
            request_id = self._new_id()
            self._send({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            })

            deadline = time.monotonic() + (timeout or self.timeout)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MCPTimeoutError(f"{method} timed out")

                self._raise_if_process_exited()

                try:
                    message = self._stdout_queue.get(timeout=min(remaining, 0.25))
                except queue.Empty:
                    continue

                if message.get("id") == request_id:
                    if "error" in message:
                        raise MCPRequestError(method, message["error"])
                    return message.get("result")

                self._handle_incoming(message)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification. Notifications do not have ids."""
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params
        self._send(message)

    def initialize(self) -> dict[str, Any]:
        if not self.is_running:
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
        self.notify("notifications/initialized")
        self._initialized = True
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

    def close(self, terminate_after: float = 2.0, kill_after: float = 1.0) -> None:
        process = self.process
        if process is None:
            return

        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass

        try:
            process.wait(timeout=terminate_after)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=kill_after)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=kill_after)
        finally:
            self.process = None
            self._initialized = False

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _send(self, message: dict[str, Any]) -> None:
        if not self.is_running or self.process is None or self.process.stdin is None:
            raise MCPProcessError(f"MCP server '{self.name}' is not running")

        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        self.process.stdin.write(payload + "\n")
        self.process.stdin.flush()

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self._stdout_queue.put(json.loads(line))
            except json.JSONDecodeError:
                self._stderr_lines.append(f"Invalid stdout from {self.name}: {line[:200]}")

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return

        for line in process.stderr:
            line = line.rstrip()
            if line:
                self._stderr_lines.append(line)
                if len(self._stderr_lines) > 100:
                    self._stderr_lines = self._stderr_lines[-100:]

    def _handle_incoming(self, message: dict[str, Any]) -> None:
        """Handle server-initiated notifications/requests we do not expose yet."""
        method = message.get("method")
        if method == "ping" and "id" in message:
            self._send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {},
            })
            return

        if "id" in message and method:
            self._send({
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {
                    "code": -32601,
                    "message": f"Unsupported client method: {method}",
                },
            })

    def _raise_if_process_exited(self) -> None:
        if self.process is None:
            raise MCPProcessError(f"MCP server '{self.name}' is not running")

        code = self.process.poll()
        if code is None:
            return

        stderr = "\n".join(self._stderr_lines[-10:])
        detail = f"\n{stderr}" if stderr else ""
        raise MCPProcessError(f"MCP server '{self.name}' exited with code {code}{detail}")

    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
