from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .client import MCPClient, MCPError
from .http_client import MCPHTTPClient


MCP_TOOL_PREFIX = "mcp__"


@dataclass
class MCPServerState:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] | None = None
    cwd: str | None = None
    env: dict[str, str] | None = None
    enabled: bool = True
    client: Any = None
    status: str = "stopped"
    error: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)


class MCPManager:
    """Manage configured stdio MCP servers and expose their tools to Sierra."""

    def __init__(
        self,
        servers: list[MCPServerState],
        workspace: str,
        sierra_dir: str,
        tool_prefix: str = MCP_TOOL_PREFIX,
    ):
        self.servers = {server.name: server for server in servers}
        self.workspace = workspace
        self.sierra_dir = sierra_dir
        self.tool_prefix = tool_prefix
        self.tool_map: dict[str, tuple[str, str]] = {}
        self._registered_tool_names: set[str] = set()

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any] | None,
        workspace: str,
        sierra_dir: str,
    ) -> "MCPManager":
        raw_servers = (config or {}).get("mcpServers", {})
        servers: list[MCPServerState] = []

        if not isinstance(raw_servers, dict):
            raw_servers = {}

        for name, raw in raw_servers.items():
            if not isinstance(raw, dict):
                continue

            server_name = unique_name(sanitize_name(name), [server.name for server in servers])
            transport = normalize_transport(raw.get("type") or ("streamablehttp" if raw.get("url") else "stdio"))
            raw_args = raw.get("args", [])
            if isinstance(raw_args, str):
                raw_args = [raw_args]
            elif not isinstance(raw_args, list):
                raw_args = []
            headers = {
                str(key): expand_value(str(value), workspace, sierra_dir)
                for key, value in raw.get("headers", {}).items()
            } if isinstance(raw.get("headers"), dict) else None

            if transport == "stdio":
                command = raw.get("command")
                if not command:
                    continue

                servers.append(
                    MCPServerState(
                        name=server_name,
                        transport=transport,
                        command=expand_value(str(command), workspace, sierra_dir),
                        args=[
                            expand_value(str(arg), workspace, sierra_dir)
                            for arg in raw_args
                        ],
                        cwd=expand_value(str(raw["cwd"]), workspace, sierra_dir)
                        if raw.get("cwd")
                        else None,
                        env={
                            str(key): expand_value(str(value), workspace, sierra_dir)
                            for key, value in raw.get("env", {}).items()
                        }
                        if isinstance(raw.get("env"), dict)
                        else None,
                        enabled=raw.get("enabled", True) is not False,
                    )
                )
                continue

            if transport == "streamablehttp":
                url = raw.get("url")
                if not url:
                    continue

                servers.append(
                    MCPServerState(
                        name=server_name,
                        transport=transport,
                        url=expand_value(str(url), workspace, sierra_dir),
                        headers=headers,
                        enabled=raw.get("enabled", True) is not False,
                    )
                )

        return cls(servers=servers, workspace=workspace, sierra_dir=sierra_dir)

    def start_all(self) -> None:
        for server in self.servers.values():
            if server.enabled:
                self.start_server(server.name)

    def start_server(self, name: str) -> MCPServerState:
        server = self.servers[name]
        if server.status == "running" and server.client and server.client.is_running:
            return server

        if server.transport == "streamablehttp":
            server.client = MCPHTTPClient(
                name=server.name,
                url=server.url,
                headers=server.headers,
            )
        else:
            server.client = MCPClient(
                name=server.name,
                command=server.command,
                args=server.args,
                cwd=server.cwd or self.workspace,
                env=server.env,
            )

        try:
            server.status = "starting"
            server.error = ""
            server.client.initialize()
            server.tools = server.client.list_tools()
            server.status = "running"
        except Exception as exc:
            server.status = "failed"
            server.error = str(exc)
            try:
                server.client.close()
            except Exception:
                pass
        return server

    def register_tools(self, registry: Any) -> None:
        registry.unregister_prefix(self.tool_prefix)
        self.tool_map.clear()
        self._registered_tool_names.clear()

        for server in self.servers.values():
            if server.status != "running":
                continue

            for tool in server.tools:
                original_name = str(tool.get("name", "")).strip()
                if not original_name:
                    continue

                exposed_name = self._make_tool_name(server.name, original_name)
                description = tool.get("description") or f"MCP tool {original_name} from {server.name}"
                schema = normalize_schema(tool.get("inputSchema"))

                registry.register(
                    name=exposed_name,
                    description=f"[MCP:{server.name}] {description}",
                    parameters=schema,
                    handler=self._make_handler(exposed_name),
                )
                self.tool_map[exposed_name] = (server.name, original_name)
                self._registered_tool_names.add(exposed_name)

    def _make_handler(self, exposed_name: str) -> Callable[..., str]:
        def handler(**arguments):
            return self.call_tool(exposed_name, arguments)

        return handler

    def call_tool(self, exposed_name: str, arguments: dict[str, Any] | None = None) -> str:
        if exposed_name not in self.tool_map:
            return json.dumps({"error": f"Unknown MCP tool: {exposed_name}"}, ensure_ascii=False)

        server_name, original_name = self.tool_map[exposed_name]
        server = self.servers.get(server_name)
        if not server or not server.client or server.status != "running":
            return json.dumps({"error": f"MCP server is not running: {server_name}"}, ensure_ascii=False)

        try:
            result = server.client.call_tool(original_name, arguments or {})
            text = extract_text(result)
            payload = {
                "server": server_name,
                "tool": original_name,
                "result": result,
            }
            if text:
                payload["text"] = text
            return json.dumps(
                payload,
                ensure_ascii=False,
            )
        except MCPError as exc:
            return json.dumps(
                {"server": server_name, "tool": original_name, "error": str(exc)},
                ensure_ascii=False,
            )

    def status(self) -> dict[str, Any]:
        return {
            "servers": [
                {
                    "name": server.name,
                    "status": server.status,
                    "transport": server.transport,
                    "enabled": server.enabled,
                    "tools": len(server.tools),
                    "error": server.error,
                    "command": server.command,
                    "url": server.url,
                }
                for server in self.servers.values()
            ],
            "tools": sorted(self._registered_tool_names),
        }

    def close_all(self) -> None:
        for server in self.servers.values():
            if server.client:
                try:
                    server.client.close()
                except Exception:
                    pass
            server.status = "stopped"

    def _make_tool_name(self, server_name: str, tool_name: str) -> str:
        base = f"{self.tool_prefix}{sanitize_name(server_name)}__{sanitize_name(tool_name)}"[:64]
        if base not in self.tool_map:
            return base

        suffix = 2
        while True:
            suffix_text = f"_{suffix}"
            candidate = f"{base[:64 - len(suffix_text)]}{suffix_text}"
            if candidate not in self.tool_map:
                return candidate
            suffix += 1


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip())
    cleaned = cleaned.strip("_").lower()
    return cleaned or "server"


def normalize_transport(value: Any) -> str:
    raw = str(value or "stdio").strip().lower().replace("_", "").replace("-", "")
    if raw in ("streamablehttp", "http"):
        return "streamablehttp"
    return "stdio"


def unique_name(base: str, existing: list[str]) -> str:
    if base not in existing:
        return base

    suffix = 2
    while f"{base}_{suffix}" in existing:
        suffix += 1
    return f"{base}_{suffix}"


def expand_value(value: str, workspace: str, sierra_dir: str) -> str:
    expanded = (
        value.replace("${workspace}", workspace)
        .replace("${cwd}", workspace)
        .replace("${sierra}", sierra_dir)
    )
    return re.sub(
        r"\$\{env:([^}]+)\}",
        lambda match: os.environ.get(match.group(1), ""),
        expanded,
    )


def normalize_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    normalized = dict(schema)
    normalized.setdefault("type", "object")
    normalized.setdefault("properties", {})
    return normalized


def extract_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""

    blocks = result.get("content")
    if not isinstance(blocks, list):
        return ""

    parts = [
        str(block.get("text", "")).strip()
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
    ]
    return "\n".join(part for part in parts if part)
