import json
import unittest

from aiagent.token_utils import estimate_text_tokens, estimate_tokens


class TokenUtilsTests(unittest.TestCase):
    def test_ascii_uses_four_chars_per_token(self):
        self.assertEqual(estimate_text_tokens("a" * 400), 100)

    def test_chinese_characters_are_not_divided_by_four(self):
        self.assertEqual(estimate_text_tokens("你" * 100), 100)

    def test_tool_json_is_not_counted_as_one_and_a_half_tokens_per_char(self):
        tools = [{
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search a remote catalog " * 20,
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
        }]
        compact_chars = len(json.dumps(tools, separators=(",", ":")))
        estimated = estimate_tokens([], tools=tools)

        self.assertLess(estimated, compact_chars)
        self.assertGreater(estimated, compact_chars / 6)

    def test_message_framing_has_small_fixed_overhead(self):
        self.assertEqual(
            estimate_tokens([{"role": "user", "content": "test"}]),
            5,
        )


if __name__ == "__main__":
    unittest.main()
