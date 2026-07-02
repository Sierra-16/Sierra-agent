import os
import unittest
from unittest.mock import patch

from aiagent.auxiliary_config import auxiliary_status, resolve_auxiliary_config
from aiagent.config_validation import StartupConfigError, validate_startup_config


class AuxiliaryConfigTests(unittest.TestCase):
    def make_config(self):
        return {
            "models": {
                "deepseek": {
                    "name": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                    "api_key": "main-key",
                },
                "qwen": {
                    "name": "qwen-plus",
                    "base_url": "https://dashscope.example/v1",
                    "api_key": "model-key",
                },
                "qwen_vl": {
                    "name": "qwen-vl-max",
                    "base_url": "https://dashscope-vl.example/v1",
                    "api_key": "vl-key",
                    "supports_vision": True,
                },
            },
            "active_model": "deepseek",
            "search": {"backend": "duckduckgo"},
            "memory": {"vector": {"enabled": False}},
            "auxiliary": {
                "vision": {
                    "enabled": True,
                    "provider": "openai_compatible",
                    "credentials_model": "qwen",
                    "model": "qwen-vl-max",
                    "api_key_env": "SIERRA_TEST_VISION_KEY",
                },
                "tts": {
                    "enabled": False,
                    "provider": "edge",
                    "api_key": "YOUR_UNUSED_TTS_KEY",
                },
            },
        }

    def test_resolves_model_credentials_without_mutating_source(self):
        config = self.make_config()

        resolved = resolve_auxiliary_config(config)
        vision = resolved["vision"]

        self.assertEqual(vision["base_url"], "https://dashscope.example/v1")
        self.assertEqual(vision["api_key"], "model-key")
        self.assertEqual(vision["model"], "qwen-vl-max")
        self.assertNotIn("base_url", config["auxiliary"]["vision"])
        self.assertNotIn("api_key", config["auxiliary"]["vision"])

    def test_environment_key_overrides_model_key(self):
        config = self.make_config()

        with patch.dict(os.environ, {"SIERRA_TEST_VISION_KEY": "env-key"}):
            resolved = resolve_auxiliary_config(config)

        self.assertEqual(resolved["vision"]["api_key"], "env-key")

    def test_auto_vision_uses_active_multimodal_model(self):
        config = self.make_config()
        config["active_model"] = "qwen_vl"
        config["auxiliary"]["vision"] = {
            "enabled": True,
            "provider": "auto",
            "credentials_model": "qwen",
            "model": "fallback-vision-model",
        }

        resolved = resolve_auxiliary_config(config)
        vision = resolved["vision"]

        self.assertEqual(vision["route"], "main_model")
        self.assertEqual(vision["credentials_model"], "qwen_vl")
        self.assertEqual(vision["model"], "qwen-vl-max")
        self.assertEqual(vision["base_url"], "https://dashscope-vl.example/v1")
        self.assertEqual(vision["api_key"], "vl-key")

    def test_auto_vision_falls_back_when_active_model_is_text_only(self):
        config = self.make_config()
        config["auxiliary"]["vision"] = {
            "enabled": True,
            "provider": "auto",
            "credentials_model": "qwen_vl",
            "model": "qwen-vl-max",
        }

        resolved = resolve_auxiliary_config(config)
        vision = resolved["vision"]

        self.assertEqual(vision["route"], "auxiliary_vision")
        self.assertEqual(vision["provider"], "openai_compatible")
        self.assertEqual(vision["credentials_model"], "qwen_vl")
        self.assertEqual(vision["api_key"], "vl-key")

    def test_disabled_placeholder_does_not_block_startup(self):
        config = self.make_config()

        validate_startup_config(config)

    def test_enabled_model_backed_capability_requires_real_credentials(self):
        config = self.make_config()
        config["auxiliary"]["vision"]["credentials_model"] = "missing-model"

        with self.assertRaises(StartupConfigError) as ctx:
            validate_startup_config(config)

        self.assertIn("auxiliary.vision.credentials_model", str(ctx.exception))

    def test_auto_vision_without_multimodal_main_requires_fallback(self):
        config = self.make_config()
        config["auxiliary"]["vision"] = {
            "enabled": True,
            "provider": "auto",
        }

        with self.assertRaises(StartupConfigError) as ctx:
            validate_startup_config(config)

        self.assertIn("auxiliary.vision.model", str(ctx.exception))

    def test_status_redacts_secret_values(self):
        config = self.make_config()
        resolved = resolve_auxiliary_config(config)

        status = auxiliary_status(resolved)
        vision = next(item for item in status["capabilities"] if item["name"] == "vision")

        self.assertTrue(vision["api_key_set"])
        self.assertNotIn("model-key", str(status))
        self.assertIn("api_key_preview", vision)


if __name__ == "__main__":
    unittest.main()
