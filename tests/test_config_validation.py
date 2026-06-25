import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiagent.config_validation import (
    StartupConfigError,
    format_config_issues,
    load_and_validate_config,
    load_config,
    validate_model_config,
    validate_startup_config,
)


class ConfigValidationTests(unittest.TestCase):
    def base_config(self):
        return {
            "models": {
                "deepseek": {
                    "name": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                    "api_key": "real-model-key",
                },
                "qwen": {
                    "name": "qwen-plus",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "YOUR_QWEN_API_KEY",
                },
            },
            "active_model": "deepseek",
            "search": {
                "backend": "duckduckgo",
            },
            "memory": {
                "vector": {
                    "enabled": False,
                }
            },
        }

    def test_missing_config_file_has_actionable_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"

            with self.assertRaises(StartupConfigError) as ctx:
                load_config(missing)

        text = format_config_issues(ctx.exception.issues)
        self.assertIn("找不到 config.json", text)
        self.assertIn("config.example.json", text)

    def test_active_model_must_have_real_api_key(self):
        config = self.base_config()
        config["models"]["deepseek"]["api_key"] = "YOUR_DEEPSEEK_API_KEY"

        with self.assertRaises(StartupConfigError) as ctx:
            validate_startup_config(config)

        self.assertIn("models.deepseek.api_key", str(ctx.exception))

    def test_inactive_model_placeholder_does_not_block_startup(self):
        validate_startup_config(self.base_config())

    def test_switching_to_placeholder_model_is_rejected(self):
        with self.assertRaises(StartupConfigError) as ctx:
            validate_model_config(self.base_config(), "qwen")

        self.assertIn("models.qwen.api_key", str(ctx.exception))

    def test_missing_environment_reference_is_reported(self):
        config = self.base_config()
        config["models"]["deepseek"]["api_key"] = "$SIERRA_TEST_MODEL_KEY"

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(StartupConfigError) as ctx:
                validate_startup_config(config)

        self.assertIn("SIERRA_TEST_MODEL_KEY", str(ctx.exception))

    def test_environment_reference_is_resolved_after_validation(self):
        config = self.base_config()
        config["models"]["deepseek"]["api_key"] = "$SIERRA_TEST_MODEL_KEY"
        config["search"] = {
            "backend": "bocha",
            "api_key": "Bearer ${env:SIERRA_TEST_SEARCH_KEY}",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SIERRA_TEST_MODEL_KEY": "env-model-key",
                    "SIERRA_TEST_SEARCH_KEY": "env-search-key",
                },
            ):
                loaded = load_and_validate_config(path)

        self.assertEqual(loaded["models"]["deepseek"]["api_key"], "env-model-key")
        self.assertEqual(loaded["search"]["api_key"], "Bearer env-search-key")

    def test_vector_memory_requires_embedding_credentials_when_enabled(self):
        config = self.base_config()
        config["memory"]["vector"] = {
            "enabled": True,
            "embedding": {
                "provider": "openai_compatible",
                "model": "text-embedding-v4",
                "base_url": "https://example.test/v1",
                "api_key": "YOUR_EMBEDDING_KEY",
            },
        }

        with self.assertRaises(StartupConfigError) as ctx:
            validate_startup_config(config)

        self.assertIn("memory.vector.embedding.api_key", str(ctx.exception))

    def test_disabled_mcp_server_can_keep_placeholder_token(self):
        config = self.base_config()
        config["mcpServers"] = {
            "example": {
                "type": "streamablehttp",
                "url": "https://example.test/mcp",
                "headers": {"Authorization": "Bearer YOUR_MCP_TOKEN"},
                "enabled": False,
            }
        }

        validate_startup_config(config)

    def test_invalid_json_is_reported_with_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"models": ', encoding="utf-8")

            with self.assertRaises(StartupConfigError) as ctx:
                load_config(path)

        self.assertIn("第 1 行", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
