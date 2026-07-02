import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiagent.tools.vision_tool import configure_vision_tool, vision_analyze, vision_status


class FakeOpenAI:
    last_kwargs = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )

    def create(self, **kwargs):
        FakeOpenAI.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="图里有一片森林。")
                )
            ],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8),
        )


class VisionToolTests(unittest.TestCase):
    def tearDown(self):
        configure_vision_tool(None, {})

    def test_disabled_vision_returns_actionable_error(self):
        configure_vision_tool(None, {"enabled": False})

        payload = json.loads(vision_analyze(image_url="https://example.test/image.png"))

        self.assertFalse(payload["ok"])
        self.assertIn("auxiliary.vision", payload["error"])

    def test_analyzes_local_image_with_configured_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            image = workspace / "photo.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            configure_vision_tool(
                str(workspace),
                {
                    "enabled": True,
                    "provider": "openai_compatible",
                    "model": "vision-model",
                    "base_url": "https://vision.example/v1",
                    "api_key": "vision-key",
                },
            )

            with patch("aiagent.vision.OpenAI", FakeOpenAI):
                payload = json.loads(vision_analyze(image_path="photo.png", question="这是什么？"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["answer"], "图里有一片森林。")
        self.assertEqual(payload["route"], "auxiliary_vision")
        self.assertEqual(payload["model"], "vision-model")
        self.assertEqual(payload["usage"]["input"], 12)
        self.assertEqual(FakeOpenAI.last_kwargs["model"], "vision-model")
        content = FakeOpenAI.last_kwargs["messages"][1]["content"]
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_rejects_unsupported_local_file_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            text_file = workspace / "note.txt"
            text_file.write_text("not an image", encoding="utf-8")
            configure_vision_tool(
                str(workspace),
                {
                    "enabled": True,
                    "provider": "openai_compatible",
                    "model": "vision-model",
                    "base_url": "https://vision.example/v1",
                    "api_key": "vision-key",
                },
            )

            payload = json.loads(vision_analyze(image_path="note.txt"))

        self.assertFalse(payload["ok"])
        self.assertIn("unsupported image type", payload["error"])

    def test_status_redacts_connection_details(self):
        configure_vision_tool(
            None,
            {
                "enabled": True,
                "provider": "openai_compatible",
                "route": "main_model",
                "model": "vision-model",
                "base_url": "https://vision.example/v1",
                "api_key": "vision-key",
            },
        )

        status = vision_status()

        self.assertTrue(status["enabled"])
        self.assertEqual(status["route"], "main_model")
        self.assertTrue(status["base_url_set"])
        self.assertTrue(status["api_key_set"])


if __name__ == "__main__":
    unittest.main()
