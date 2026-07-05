import json
import unittest

from aiagent.tools.registry import ToolRegistry


class ToolSearchTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(
            name="read_file",
            description="Read a local file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=lambda path: json.dumps({"path": path, "content": "ok"}),
            toolset="file",
        )
        self.registry.register(
            name="mcp__github__create_issue",
            description="Create an issue in a GitHub repository",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title"],
            },
            handler=lambda **kwargs: json.dumps({"created": True, "args": kwargs}),
            toolset="mcp-github",
        )
        self.registry.register(
            name="mcp__github__search_issues",
            description="Search GitHub issues",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=lambda **kwargs: json.dumps({"results": [kwargs]}),
            toolset="mcp-github",
        )

    def test_tool_search_hides_deferred_tools_and_exposes_bridges(self):
        self.registry.configure_tool_search({"enabled": "on"}, context_window=100000)

        tool_names = {
            item["function"]["name"]
            for item in self.registry.get_definitions()
        }

        self.assertIn("read_file", tool_names)
        self.assertIn("tool_search", tool_names)
        self.assertIn("tool_describe", tool_names)
        self.assertIn("tool_call", tool_names)
        self.assertNotIn("mcp__github__create_issue", tool_names)

    def test_tool_search_describe_and_call_deferred_tool(self):
        self.registry.configure_tool_search({"enabled": "on"}, context_window=100000)
        self.registry.get_definitions()

        search = json.loads(self.registry.execute("tool_search", {"query": "create github issue"}))
        self.assertGreaterEqual(search["count"], 1)
        self.assertEqual(search["matches"][0]["name"], "mcp__github__create_issue")

        describe = json.loads(
            self.registry.execute("tool_describe", {"name": "mcp__github__create_issue"})
        )
        self.assertEqual(describe["name"], "mcp__github__create_issue")
        self.assertIn("title", describe["parameters"]["properties"])

        result = json.loads(
            self.registry.execute(
                "tool_call",
                {
                    "name": "mcp__github__create_issue",
                    "arguments": {"title": "Bug", "body": "Details"},
                },
            )
        )
        self.assertTrue(result["created"])
        self.assertEqual(result["args"]["title"], "Bug")

    def test_tool_call_rejects_non_deferred_core_tool(self):
        self.registry.configure_tool_search({"enabled": "on"}, context_window=100000)
        self.registry.get_definitions()

        result = json.loads(
            self.registry.execute(
                "tool_call",
                {"name": "read_file", "arguments": {"path": "notes.txt"}},
            )
        )

        self.assertIn("error", result)
        self.assertIn("deferred", result["error"])

    def test_auto_mode_does_not_activate_below_threshold(self):
        self.registry.configure_tool_search(
            {"enabled": "auto", "threshold_pct": 99},
            context_window=1_000_000,
        )

        tool_names = {
            item["function"]["name"]
            for item in self.registry.get_definitions()
        }

        self.assertIn("mcp__github__create_issue", tool_names)
        self.assertNotIn("tool_search", tool_names)

    def test_unavailable_tool_is_hidden_from_schema_and_search(self):
        self.registry.register(
            name="mcp__github__delete_repo",
            description="Delete a GitHub repository",
            parameters={
                "type": "object",
                "properties": {"repo": {"type": "string"}},
                "required": ["repo"],
            },
            handler=lambda **kwargs: json.dumps({"deleted": True}),
            toolset="danger",
            check_fn=lambda: False,
            requires_env=["GITHUB_TOKEN"],
        )
        self.registry.configure_tool_search({"enabled": "on"}, context_window=100000)

        tool_names = {
            item["function"]["name"]
            for item in self.registry.get_definitions()
        }
        search = json.loads(self.registry.execute("tool_search", {"query": "delete repo"}))
        result = json.loads(
            self.registry.execute(
                "tool_call",
                {"name": "mcp__github__delete_repo", "arguments": {"repo": "demo"}},
            )
        )

        self.assertNotIn("mcp__github__delete_repo", tool_names)
        self.assertFalse(any(match["name"] == "mcp__github__delete_repo" for match in search["matches"]))
        self.assertIn("unavailable", result["error"])
        available, unavailable = self.registry.check_tool_availability()
        self.assertIn("file", available)
        danger_info = next(item for item in unavailable if item["name"] == "danger")
        self.assertIn("GITHUB_TOKEN", danger_info["env_vars"])

    def test_availability_cache_can_be_invalidated(self):
        state = {"ready": False}
        self.registry.register(
            name="optional_tool",
            description="Optional tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kwargs: json.dumps({"ok": True}),
            toolset="optional",
            check_fn=lambda: state["ready"],
        )

        self.assertFalse(self.registry.is_tool_available("optional_tool"))
        state["ready"] = True
        self.assertFalse(self.registry.is_tool_available("optional_tool"))
        self.registry.invalidate_availability_cache()

        self.assertTrue(self.registry.is_tool_available("optional_tool"))


if __name__ == "__main__":
    unittest.main()
