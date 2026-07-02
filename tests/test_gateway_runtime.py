import threading
import unittest
from types import SimpleNamespace

from aiagent.gateway import GatewayRuntime


class ApprovalAgent:
    def __init__(self):
        self.llm = SimpleNamespace(model="fake")
        self.workspace = "."
        self.messages = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.current_context_tokens = 0
        self.context_window = 1000
        self.context_tokens_estimated = False
        self.decision = None

    def chat(self, message, on_status=None, on_tool_approval=None, on_user_input=None):
        self.messages.append({"role": "user", "content": message})
        self.decision = on_tool_approval({
            "name": "write_file",
            "risk": "high",
            "reason": "write requires approval",
            "arguments": {"file_path": "demo.txt"},
        })
        return f"decision:{self.decision}"

    def usage_snapshot(self):
        return {
            "input": 1,
            "output": 1,
            "context": 2,
            "context_window": self.context_window,
            "context_estimated": False,
        }


class UserInputAgent(ApprovalAgent):
    def __init__(self):
        super().__init__()
        self.answer = None

    def chat(self, message, on_status=None, on_tool_approval=None, on_user_input=None):
        self.answer = on_user_input({
            "question": "Pick one",
            "options": [{"label": "A", "value": "a"}],
            "allow_free_text": True,
        })
        return self.answer.get("value", "")


class StatusAgent(ApprovalAgent):
    def chat(self, message, on_status=None, on_tool_approval=None, on_user_input=None):
        on_status({"type": "thinking"})
        on_status({"type": "thinking"})
        return "finished"


class GatewayRuntimeTests(unittest.TestCase):
    def test_tool_approval_can_be_released_from_another_adapter_call(self):
        runtime = GatewayRuntime(ApprovalAgent(), id_factory=lambda: "abcdef123456")
        events = []
        result_holder = {}

        thread = threading.Thread(
            target=lambda: result_holder.update(
                result=runtime.chat("delete file", emit=events.append)
            ),
            daemon=True,
        )
        thread.start()

        self.assertTrue(_wait_until(lambda: events and events[0]["type"] == "tool_approval_request"))
        approval_id = events[0]["id"]
        response = runtime.respond_tool_approval(approval_id, "once")
        thread.join(timeout=2)

        self.assertTrue(response["ok"])
        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder["result"].answer, "decision:once")
        self.assertEqual(runtime.agent.decision, "once")

    def test_user_input_can_be_released_from_another_adapter_call(self):
        runtime = GatewayRuntime(UserInputAgent(), id_factory=lambda: "123456abcdef")
        events = []
        result_holder = {}

        thread = threading.Thread(
            target=lambda: result_holder.update(
                result=runtime.chat("plan", emit=events.append)
            ),
            daemon=True,
        )
        thread.start()

        self.assertTrue(_wait_until(lambda: events and events[0]["type"] == "user_input_request"))
        input_id = events[0]["id"]
        response = runtime.respond_user_input(input_id, {
            "value": "a",
            "label": "A",
            "free_text": False,
            "cancelled": False,
        })
        thread.join(timeout=2)

        self.assertTrue(response["ok"])
        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder["result"].answer, "a")
        self.assertEqual(runtime.agent.answer["value"], "a")

    def test_cancel_releases_pending_tool_approval(self):
        runtime = GatewayRuntime(ApprovalAgent(), id_factory=lambda: "abcdef123456")
        events = []
        result_holder = {}

        thread = threading.Thread(
            target=lambda: result_holder.update(
                result=runtime.chat("delete file", emit=events.append)
            ),
            daemon=True,
        )
        thread.start()

        self.assertTrue(_wait_until(lambda: events and events[0]["type"] == "tool_approval_request"))
        response = runtime.cancel_current("test")
        thread.join(timeout=2)

        self.assertTrue(response["ok"])
        self.assertEqual(response["released_approvals"], 1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result_holder["result"].interrupted)

    def test_cancel_interrupts_on_next_status_event(self):
        runtime = GatewayRuntime(StatusAgent(), id_factory=lambda: "abcdef123456")
        events = []

        def emit(event):
            events.append(event)
            if len(events) == 1:
                runtime.cancel_current("test")

        result = runtime.chat("hello", emit=emit)

        self.assertTrue(result.interrupted)
        self.assertEqual(events[-1]["type"], "interrupted")


def _wait_until(predicate, timeout=2):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


if __name__ == "__main__":
    unittest.main()
