import unittest

from aiagent.auxiliary_config import resolve_auxiliary_config
from aiagent.capabilities import CapabilityRegistry


class FakeTools:
    def names(self):
        return ["read_file", "vision_analyze", "mcp__demo__ping"]

    def get_definitions(self):
        return [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "vision_analyze"}},
        ]

    def get_entry(self, name):
        class Entry:
            pass

        entry = Entry()
        if name.startswith("mcp__"):
            entry.toolset = "mcp"
        elif name == "vision_analyze":
            entry.toolset = "vision"
        else:
            entry.toolset = "file"
        return entry


class CapabilityRegistryTests(unittest.TestCase):
    def make_config(self):
        return {
            "active_model": "chat",
            "models": {
                "chat": {
                    "name": "chat-model",
                    "base_url": "https://chat.example/v1",
                    "api_key": "chat-secret",
                },
                "vision": {
                    "name": "vision-model",
                    "base_url": "https://vision.example/v1",
                    "api_key": "vision-secret",
                },
            },
            "auxiliary": {
                "vision": {
                    "enabled": True,
                    "provider": "openai_compatible",
                    "credentials_model": "vision",
                    "model": "vision-model",
                },
                "tts": {
                    "enabled": False,
                    "provider": "edge",
                },
            },
        }

    def test_payload_summarizes_auxiliary_runtime_and_redacts_secrets(self):
        auxiliary = resolve_auxiliary_config(self.make_config())
        registry = CapabilityRegistry.from_parts(
            auxiliary_config=auxiliary,
            tools=FakeTools(),
            mcp_status={
                "servers": [{"name": "demo", "enabled": True, "status": "running"}],
                "tools": ["mcp__demo__ping"],
            },
            memory_status={
                "curated": "User likes compact dashboards.",
                "providers": [{"name": "markdown", "available": True}],
            },
            skill_summaries=[{"name": "project-context"}],
            cron_status={"enabled": True, "tasks": [{"id": "cron-1"}]},
            background_status={"enabled": True, "pending_count": 1, "running_count": 0, "failed_count": 0},
        )

        payload = registry.payload()
        vision = payload["by_name"]["vision"]

        self.assertEqual(vision["status"], "ready")
        self.assertTrue(vision["api_key_set"])
        self.assertNotIn("vision-secret", str(payload))
        self.assertEqual(payload["by_name"]["tools"]["metadata"]["total"], 3)
        self.assertEqual(payload["by_name"]["mcp"]["status"], "ready")
        self.assertGreaterEqual(payload["summary"]["ready"], 1)

    def test_prompt_context_keeps_vision_instruction_current(self):
        auxiliary = resolve_auxiliary_config(self.make_config())
        registry = CapabilityRegistry.from_parts(auxiliary_config=auxiliary)

        prompt = registry.prompt_context()

        self.assertIn("Capability Center", prompt)
        self.assertIn("vision: ready", prompt)
        self.assertIn("vision_analyze", prompt)


if __name__ == "__main__":
    unittest.main()
