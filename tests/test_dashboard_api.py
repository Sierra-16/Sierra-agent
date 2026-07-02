import contextlib
import base64
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


try:
    from fastapi.testclient import TestClient

    from aiagent.dashboard_api import create_dashboard_app
except ModuleNotFoundError as exc:
    TestClient = None
    create_dashboard_app = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


class FakeTools:
    def names(self):
        return ["read_file", "project_inspect"]

    def get_definitions(self):
        return [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "project_inspect"}},
        ]

    def get_entry(self, name):
        return SimpleNamespace(
            toolset="file" if name == "read_file" else "project",
            emoji="",
            description=f"{name} description",
        )


class FakeAgent:
    model = "test-model"
    workspace = "E:\\workspace"
    sierra_dir = "E:\\Sierra"
    conv_id = "conv-1"
    tools = FakeTools()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    def refresh_context_estimate(self):
        return None

    def usage_snapshot(self):
        return {
            "input": 100,
            "output": 25,
            "context": 128000,
            "context_window": 256000,
            "context_estimated": True,
            "compression_count": 2,
        }

    def list_conversations(self):
        return [{"id": "conv-1", "title": "hello", "updated": 1}]

    def load_conversation(self, conv_id):
        self.conv_id = conv_id
        self.messages = [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "loaded hello"},
            {"role": "assistant", "content": "loaded hi"},
        ]

    def checkpoint_conversation(self):
        return True

    def reset(self):
        self.messages = []

    def memory_status(self):
        return {
            "curated": "User likes compact dashboards.",
            "providers": [{"name": "local_vector", "available": True, "records": 3}],
        }

    def memory_search(self, query, limit=5):
        return [
            {
                "id": 1,
                "score": 0.87,
                "content": f"remembered {query}",
                "created_at": "2026-06-29T12:00:00",
            }
        ][:limit]

    def mcp_status(self):
        return {"servers": [{"name": "demo", "type": "stdio", "running": True}]}

    def task_status(self):
        return {"id": "task-1", "status": "active"}

    def task_recovery(self):
        return None

    def background_jobs_status(self, limit=20):
        return {
            "enabled": True,
            "pending_count": 0,
            "running_count": 0,
            "failed_count": 0,
            "jobs": [],
        }

    def cron_status(self):
        return {"enabled": True, "tasks": []}

    def skill_summaries(self, include_unavailable=False):
        return [{"name": "software/project-context"}]

    def skill_usage_stats(self, limit=20):
        return {"rows": []}

    def debug_context_status(self):
        return {
            "available": True,
            "summary": {
                "blocks": [
                    {"name": "system_prompt", "tokens": 100},
                    {"name": "tools_schema", "tokens": 50},
                ]
            },
        }

    def audit_recent(self, limit=20):
        return [{"timestamp": "2026-06-29T12:00:00", "tool": "read_file", "success": True}]

    def chat(self, message, on_status=None, on_tool_approval=None, on_user_input=None):
        if on_status:
            on_status({"type": "assistant_delta", "text": "ok"})
        self.messages.append({"role": "user", "content": message})
        self.messages.append({"role": "assistant", "content": "Sierra heard you."})
        return "Sierra heard you."


class NoisyFakeAgent(FakeAgent):
    def chat(self, message, on_status=None, on_tool_approval=None, on_user_input=None):
        print("assistant delta leaked to stdout")
        print("tool log leaked to stderr", file=sys.stderr)
        return super().chat(
            message,
            on_status=on_status,
            on_tool_approval=on_tool_approval,
            on_user_input=on_user_input,
        )


class ApprovalFakeAgent(FakeAgent):
    def chat(self, message, on_status=None, on_tool_approval=None, on_user_input=None):
        if on_status:
            on_status({"type": "thinking"})
        decision = on_tool_approval({
            "name": "write_file",
            "arguments": "{\n  \"file_path\": \"demo.txt\"\n}",
            "risk": "high",
            "reason": "writing files requires approval",
        })
        if on_status:
            on_status({
                "type": "tool_result",
                "name": "write_file",
                "text": f"decision: {decision}",
                "success": decision in {"once", "session"},
            })
        return f"decision:{decision}"


@unittest.skipIf(FASTAPI_IMPORT_ERROR is not None, f"FastAPI unavailable: {FASTAPI_IMPORT_ERROR}")
class DashboardApiTest(unittest.TestCase):
    def test_dashboard_payload_is_structured(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={
                "active_model": "test",
                "models": {"test": {"name": "test-model"}},
            },
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["identity"]["model"], "test-model")
        self.assertEqual(payload["usage"]["percent"], 50)
        self.assertEqual(payload["tools"]["total"], 2)
        self.assertEqual(payload["memory"]["providers"][0]["records"], 3)
        self.assertEqual(payload["mcp"]["servers"][0]["name"], "demo")

    def test_chat_endpoint_returns_answer(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.post("/api/chat", json={"message": "你好"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer"], "Sierra heard you.")
        self.assertEqual(payload["usage"]["percent"], 50)
        self.assertEqual(payload["events"][0]["type"], "assistant_delta")

    def test_chat_endpoint_suppresses_agent_terminal_output(self):
        app = create_dashboard_app(
            NoisyFakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            response = client.post("/api/chat", json={"message": "hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_chat_stream_endpoint_returns_events_without_terminal_output(self):
        app = create_dashboard_app(
            NoisyFakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with client.stream("POST", "/api/chat/stream", json={"message": "hello"}) as response:
                self.assertEqual(response.status_code, 200)
                events = [
                    json.loads(line)
                    for line in response.iter_lines()
                    if line
                ]

        self.assertTrue(any(event["type"] == "assistant_delta" for event in events))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["answer"], "Sierra heard you.")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_chat_approval_endpoint_releases_pending_request(self):
        app = create_dashboard_app(
            ApprovalFakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)
        approval_id = "approval-test"
        waiter = {"event": threading.Event(), "decision": "deny"}
        with app.state.approval_lock:
            app.state.pending_approvals[approval_id] = waiter

        response = client.post(
            "/api/chat/approval",
            json={"id": approval_id, "decision": "once"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(waiter["event"].is_set())
        self.assertEqual(waiter["decision"], "once")

    def test_chat_input_endpoint_releases_pending_request(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)
        input_id = "input-test"
        waiter = {"event": threading.Event(), "response": {"cancelled": True}}
        with app.state.input_lock:
            app.state.pending_inputs[input_id] = waiter

        response = client.post(
            "/api/chat/input",
            json={"id": input_id, "value": "A", "label": "Plan A"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(waiter["event"].is_set())
        self.assertEqual(waiter["response"]["value"], "A")

    def test_chat_cancel_endpoint_releases_pending_requests(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)
        approval_waiter = {"event": threading.Event(), "decision": "once"}
        input_waiter = {"event": threading.Event(), "response": {"cancelled": False}}
        with app.state.approval_lock:
            app.state.pending_approvals["tool-test"] = approval_waiter
        with app.state.input_lock:
            app.state.pending_inputs["input-test"] = input_waiter

        response = client.post("/api/chat/cancel")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["released_approvals"], 1)
        self.assertEqual(payload["released_inputs"], 1)
        self.assertTrue(approval_waiter["event"].is_set())
        self.assertEqual(approval_waiter["decision"], "deny")
        self.assertTrue(input_waiter["event"].is_set())
        self.assertTrue(input_waiter["response"]["cancelled"])

    def test_command_endpoint_returns_help(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.post("/api/command", json={"command": "/help", "text": "/help"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("/model", payload["text"])

    def test_command_endpoint_searches_memory(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.post(
            "/api/command",
            json={"command": "/memory-search", "text": "/memory-search dashboard"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("remembered dashboard", payload["text"])

    def test_conversation_endpoint_loads_messages(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.get("/api/conversations/conv-1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], "conv-1")
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(payload["messages"][0]["text"], "loaded hello")

    def test_new_conversation_endpoint_resets_agent(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.post("/api/conversations/new")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["messages"], [])

    def test_context_suggestions_include_workspace_references(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "main.py").write_text("print('hello')\n", encoding="utf-8")
            (workspace / "aiagent").mkdir()
            (workspace / "aiagent" / "agent.py").write_text("class Agent: pass\n", encoding="utf-8")
            (workspace / "node_modules").mkdir()
            (workspace / "node_modules" / "ignored.js").write_text("", encoding="utf-8")

            agent = FakeAgent()
            agent.workspace = str(workspace)
            app = create_dashboard_app(
                agent,
                config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
                sierra_dir=".",
                static_dir="missing-dist",
            )
            client = TestClient(app)

            response = client.get("/api/context/suggestions", params={"q": "main", "limit": 10})

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertTrue(any(item["value"] == "@file:`main.py` " for item in items))
        self.assertFalse(any("node_modules" in item["value"] for item in items))

    def test_upload_endpoint_saves_file_under_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            agent = FakeAgent()
            agent.workspace = str(workspace)
            app = create_dashboard_app(
                agent,
                config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
                sierra_dir=".",
                static_dir="missing-dist",
            )
            client = TestClient(app)

            response = client.post(
                "/api/uploads",
                json={
                    "filename": "../brief.pdf",
                    "content_base64": base64.b64encode(b"demo pdf bytes").decode("ascii"),
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["relative_path"], "uploads/brief.pdf")
            self.assertEqual(payload["reference"], "@file:`uploads/brief.pdf` ")
            self.assertEqual((workspace / "uploads" / "brief.pdf").read_bytes(), b"demo pdf bytes")


if __name__ == "__main__":
    unittest.main()
