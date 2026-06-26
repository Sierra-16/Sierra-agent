import unittest

from aiagent.agent import _resolve_prompt_budget


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


if __name__ == "__main__":
    unittest.main()
