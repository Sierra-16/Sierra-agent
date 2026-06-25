import os
import unittest
from unittest.mock import patch

from aiagent.memory.config import resolve_memory_config


class MemoryConfigTests(unittest.TestCase):
    def make_config(self):
        return {
            "models": {
                "qwen": {
                    "base_url": "https://example.test/v1",
                    "api_key": "model-key",
                }
            },
            "memory": {
                "vector": {
                    "enabled": True,
                    "embedding": {
                        "credentials_model": "qwen",
                        "model": "embedding-model",
                        "api_key_env": "TEST_EMBEDDING_KEY",
                    },
                }
            },
        }

    def test_resolves_model_credentials_without_mutating_source(self):
        config = self.make_config()

        resolved = resolve_memory_config(config)
        embedding = resolved["vector"]["embedding"]

        self.assertEqual(embedding["base_url"], "https://example.test/v1")
        self.assertEqual(embedding["api_key"], "model-key")
        self.assertNotIn("api_key", config["memory"]["vector"]["embedding"])

    def test_environment_key_overrides_model_key(self):
        config = self.make_config()

        with patch.dict(os.environ, {"TEST_EMBEDDING_KEY": "env-key"}):
            resolved = resolve_memory_config(config)

        self.assertEqual(resolved["vector"]["embedding"]["api_key"], "env-key")


if __name__ == "__main__":
    unittest.main()
