import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from aiagent.plugins import PluginManager, PluginManifest


class PluginSystemTests(unittest.TestCase):
    def test_builtin_plugins_register_provider_surfaces(self):
        manager = PluginManager.from_config(
            {"roots": []},
            sierra_dir=".",
            workspace=".",
        ).discover_and_load()

        status = manager.status({
            "image_generation": {
                "enabled": True,
                "provider": "openai_compatible",
                "model": "wanx-test",
                "base_url": "https://example.test/v1",
                "api_key": "secret",
            },
            "tts": {
                "enabled": True,
                "provider": "edge",
                "voice": "zh-CN-XiaoxiaoNeural",
                "format": "mp3",
            },
            "stt": {
                "enabled": False,
                "provider": "local",
            },
        })

        self.assertGreaterEqual(status["total"], 3)
        self.assertEqual(status["failed"], 0)
        provider_keys = {
            f"{item['kind']}:{item['name']}"
            for item in status["providers"]["items"]
        }
        self.assertIn("image_generation:openai_compatible", provider_keys)
        self.assertIn("tts:edge", provider_keys)
        self.assertIn("stt:local", provider_keys)
        image_provider = next(
            item
            for item in status["providers"]["items"]
            if item["kind"] == "image_generation"
        )
        self.assertTrue(image_provider["enabled"])
        self.assertTrue(image_provider["available"])

    def test_disabled_plugin_is_discovered_but_not_loaded(self):
        manager = PluginManager.from_config(
            {"roots": [], "disabled": ["image_generation.openai_compatible"]},
            sierra_dir=".",
            workspace=".",
        ).discover_and_load()

        status = manager.status({})
        image_plugin = next(
            item
            for item in status["items"]
            if item["id"] == "image_generation.openai_compatible"
        )

        self.assertFalse(image_plugin["enabled"])
        self.assertFalse(image_plugin["loaded"])
        self.assertNotIn(
            "image_generation:openai_compatible",
            {item.key for item in manager.provider_registry.registrations()},
        )

    def test_external_plugin_manifest_can_register_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = Path(tmp) / "demo_plugin"
            plugin_dir.mkdir()
            (plugin_dir / "plugin.json").write_text(
                json.dumps({
                    "id": "demo.provider",
                    "name": "Demo Provider",
                    "kind": "provider",
                    "version": "0.1.0",
                    "description": "Test plugin.",
                    "entrypoint": "register",
                    "enabled_by_default": True,
                }),
                encoding="utf-8",
            )
            (plugin_dir / "provider.py").write_text(
                textwrap.dedent(
                    """
                    class DemoProvider:
                        def status(self, config=None):
                            return {"enabled": True, "available": True, "issues": []}

                    def register(context):
                        context.register_provider(
                            kind="demo",
                            name="provider",
                            factory=DemoProvider,
                            title="Demo",
                        )
                    """
                ).strip(),
                encoding="utf-8",
            )

            manager = PluginManager.from_config(
                {"roots": [tmp]},
                sierra_dir=".",
                workspace=".",
            ).discover_and_load()

        registration = manager.provider_registry.get("demo", "provider")
        self.assertIsNotNone(registration)
        self.assertEqual(registration.plugin_id, "demo.provider")

    def test_manifest_public_payload_is_redacted_and_stable(self):
        manifest = PluginManifest.from_dict({
            "id": "Demo.Plugin",
            "name": "Demo Plugin",
            "kind": "provider",
            "version": "1.2.3",
            "description": "A plugin.",
            "capabilities": ["demo"],
            "config_schema": {"api_key": "secret shape only"},
        })

        payload = manifest.public_dict()

        self.assertEqual(payload["id"], "demo.plugin")
        self.assertEqual(payload["version"], "1.2.3")
        self.assertEqual(payload["capabilities"], ["demo"])


if __name__ == "__main__":
    unittest.main()
