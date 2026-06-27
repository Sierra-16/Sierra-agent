import unittest

from aiagent.context_errors import (
    CONTEXT_OVERFLOW,
    OUTPUT_LIMIT,
    PAYLOAD_TOO_LARGE,
    classify_llm_error,
    extract_available_output_tokens,
    extract_context_window,
)
from aiagent.conversation_loop import run_conversation_loop
from aiagent.token_utils import estimate_tokens


class FakeAPIError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class EmptyTools:
    def get_definitions(self):
        return []


class OverflowThenSuccessLLM:
    def __init__(self):
        self.calls = []
        self.max_tokens = 1024

    def stream_chat(self, messages, tools, on_delta):
        self.calls.append(messages)
        if len(self.calls) == 1:
            raise FakeAPIError(
                "context length exceeded: maximum context window is 8192 tokens"
            )
        return {
            "content": "recovered",
            "tool_calls": None,
            "usage": {"input": 10, "output": 2},
        }


class OutputLimitThenSuccessLLM:
    def __init__(self):
        self.calls = []
        self.max_tokens = 1000

    def stream_chat(self, messages, tools, on_delta):
        self.calls.append(messages)
        if len(self.calls) == 1:
            raise FakeAPIError("max_tokens is too large; available_tokens: 512")
        return {
            "content": "short answer",
            "tool_calls": None,
            "usage": {"input": 5, "output": 1},
        }


class RecoveryAgent:
    def __init__(self, llm):
        self.messages = [
            {"role": "user", "content": "old " + "x" * 6000},
            {"role": "assistant", "content": "old answer " + "y" * 6000},
        ]
        self.llm = llm
        self.tools = EmptyTools()
        self.memory_manager = None
        self.history_recall_config = {"enabled": False}
        self.system_prompt = "system"
        self.max_iterations = 2
        self.max_compress_tokens = 100000
        self.context_window = 100000
        self.model_context_window = 100000
        self.compression_context_window = 100000
        self.compression_enabled = True
        self.compression_max_passes = 2
        self.compression_keep_tokens = 2000
        self.compression_target_tokens = 2000
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.conv_id = "c1"
        self.model = "test-model"
        self.compress_calls = 0
        self.updated_context_window = None

    def count_tokens(self, usage):
        self.total_input_tokens += usage["input"]
        self.total_output_tokens += usage["output"]

    def update_current_context(self, actual_tokens, estimated_tokens=0):
        self.current_context_tokens = actual_tokens or estimated_tokens

    def update_context_window(self, context_window):
        self.updated_context_window = context_window
        self.model_context_window = context_window
        self.compression_context_window = context_window
        self.context_window = min(self.context_window, context_window - 1024)
        return {"model_context_window": context_window}

    def compress_messages(self, force=False, keep_tokens=None):
        self.compress_calls += 1
        before_tokens = estimate_tokens(self.messages)
        latest = self.messages[-1]
        self.messages = [
            {"role": "system", "content": "<conversation-summary>old work</conversation-summary>"},
            latest,
        ]
        return {
            "compressed": True,
            "reason": "compressed",
            "before_messages": 3,
            "after_messages": len(self.messages),
            "before_tokens": before_tokens,
            "after_tokens": estimate_tokens(self.messages),
        }


class ContextErrorTests(unittest.TestCase):
    def test_classifies_payload_context_and_output_errors(self):
        self.assertEqual(
            classify_llm_error(FakeAPIError("request entity too large", 413)),
            PAYLOAD_TOO_LARGE,
        )
        self.assertEqual(
            classify_llm_error(FakeAPIError("context length exceeded maximum context window 8192")),
            CONTEXT_OVERFLOW,
        )
        self.assertEqual(
            classify_llm_error(FakeAPIError("max_tokens too large; available_tokens: 512")),
            OUTPUT_LIMIT,
        )

    def test_extracts_provider_limits(self):
        error = FakeAPIError(
            "context length exceeded: maximum context window is 131,072 tokens"
        )
        self.assertEqual(extract_context_window(error), 131072)
        self.assertEqual(
            extract_available_output_tokens(
                FakeAPIError("max_tokens too large; available_tokens: 512")
            ),
            512,
        )


class ConversationLoopRecoveryTests(unittest.TestCase):
    def test_context_overflow_forces_compression_and_retries(self):
        agent = RecoveryAgent(OverflowThenSuccessLLM())
        events = []

        result = run_conversation_loop(agent, "current task", on_status=events.append)

        self.assertEqual(result, "recovered")
        self.assertEqual(agent.compress_calls, 1)
        self.assertEqual(len(agent.llm.calls), 2)
        self.assertEqual(agent.updated_context_window, 8192)
        self.assertIn(
            "context_overflow_recovering",
            [event["type"] for event in events],
        )

    def test_output_limit_reduces_max_tokens_without_compression(self):
        llm = OutputLimitThenSuccessLLM()
        agent = RecoveryAgent(llm)
        events = []

        result = run_conversation_loop(agent, "current task", on_status=events.append)

        self.assertEqual(result, "short answer")
        self.assertEqual(agent.compress_calls, 0)
        self.assertEqual(len(llm.calls), 2)
        self.assertLess(llm.max_tokens, 1000)
        self.assertIn(
            "context_output_tokens_reduced",
            [event["type"] for event in events],
        )


if __name__ == "__main__":
    unittest.main()
