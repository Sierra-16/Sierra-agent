import unittest

from aiagent.agent import _resolve_compression_window, _resolve_prompt_budget


class ContextConfigTests(unittest.TestCase):
    def test_default_prompt_budget_caps_large_model_windows(self):
        budget = _resolve_prompt_budget(
            1_000_000,
            16_384,
            {},
        )

        self.assertEqual(budget, 120_000)

    def test_model_budget_can_be_used_when_cap_is_disabled(self):
        budget = _resolve_prompt_budget(
            128_000,
            8_192,
            {"max_prompt_tokens": "model"},
        )

        self.assertEqual(budget, 119_808)

    def test_compression_window_defaults_to_model_window(self):
        window = _resolve_compression_window(
            1_000_000,
            {"max_prompt_tokens": 120_000},
        )

        self.assertEqual(window, 1_000_000)

    def test_compression_window_can_be_overridden(self):
        window = _resolve_compression_window(
            1_000_000,
            {"compression_context_window": 256_000},
        )

        self.assertEqual(window, 256_000)


if __name__ == "__main__":
    unittest.main()
