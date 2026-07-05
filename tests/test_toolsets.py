import json
import unittest

from aiagent.toolsets import resolve_toolset
from aiagent.tools.registry import ToolRegistry


class ToolsetTests(unittest.TestCase):
    def make_registry(self):
        registry = ToolRegistry()
        registry.register(
            name="read_file",
            description="Read a local file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            handler=lambda **kwargs: json.dumps({"read": kwargs}),
            toolset="file",
        )
        registry.register(
            name="write_file",
            description="Write a local file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            handler=lambda **kwargs: json.dumps({"written": kwargs}),
            toolset="file",
        )
        registry.register(
            name="search_files",
            description="Search local files",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda **kwargs: json.dumps({"matches": []}),
            toolset="file",
        )
        registry.register(
            name="web_search",
            description="Search the web",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda **kwargs: json.dumps({"results": []}),
            toolset="web",
        )
        registry.register(
            name="terminal",
            description="Run a shell command",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}},
            handler=lambda **kwargs: json.dumps({"exit_code": 0}),
            toolset="terminal",
        )
        registry.register(
            name="mcp__demo__ping",
            description="Ping a demo MCP server",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kwargs: json.dumps({"pong": True}),
            toolset="mcp:demo",
        )
        return registry

    def test_resolve_builtin_toolset_with_patterns(self):
        names = ["read_file", "mcp__demo__ping", "mcp__other__echo"]

        self.assertEqual(
            resolve_toolset("mcp", registered_names=names),
            ["mcp__demo__ping", "mcp__other__echo"],
        )
        self.assertIn("read_file", resolve_toolset("file_readonly", registered_names=names))

    def test_toolset_selection_filters_schema_and_execution(self):
        registry = self.make_registry()
        registry.configure_tools(
            {
                "toolsets": {
                    "enabled": ["file_readonly"],
                    "additional_tools": ["mcp__demo__ping"],
                    "disabled_tools": ["search_files"],
                },
                "tool_search": {"enabled": "on"},
            },
            context_window=100000,
        )

        tool_names = {item["function"]["name"] for item in registry.get_definitions()}
        result = json.loads(registry.execute("write_file", {"path": "a.txt"}))
        search = json.loads(registry.execute("tool_search", {"query": "ping"}))

        self.assertIn("read_file", tool_names)
        self.assertNotIn("write_file", tool_names)
        self.assertNotIn("search_files", tool_names)
        self.assertIn("disabled", result["error"])
        self.assertEqual(search["matches"][0]["name"], "mcp__demo__ping")

    def test_custom_toolset_and_diagnostics(self):
        registry = self.make_registry()
        registry.configure_tools(
            {
                "toolsets": {
                    "enabled": ["companion_safe", "missing_set"],
                    "additional_tools": ["missing_tool"],
                    "custom": {
                        "companion_safe": {
                            "description": "Small safe set",
                            "includes": ["core", "web"],
                            "tools": ["read_file"],
                        }
                    },
                }
            }
        )

        status = registry.toolset_status()
        visible = set(status["visible_tools"])

        self.assertIn("read_file", visible)
        self.assertIn("web_search", visible)
        self.assertNotIn("terminal", visible)
        self.assertIn("missing_set", status["unknown_toolsets"])
        self.assertIn("missing_tool", status["unmatched_patterns"])


if __name__ == "__main__":
    unittest.main()
