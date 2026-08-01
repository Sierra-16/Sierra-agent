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
    from aiagent.conversation_store import ConversationStore
    from aiagent.skills.loader import SkillLoader
    from aiagent.skills.prompt_index import SkillPromptIndex
    from aiagent.tools.registry import ToolRegistry
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

    def compress_messages(self, force=False):
        self.messages = [
            {"role": "system", "content": "[summary] compressed history"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        return {
            "compressed": True,
            "before_tokens": 1200,
            "after_tokens": 320,
            "force": force,
        }

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


class StoreBackedFakeAgent(FakeAgent):
    def __init__(self, store):
        self.store = store
        self.session_db = None
        self.conv_id = "active"
        self.messages = [{"role": "user", "content": "active message"}]

    def usage_snapshot(self):
        return {
            "input": 10,
            "output": 5,
            "context": 100,
            "context_window": 256000,
            "context_estimated": True,
            "compression_count": 0,
        }

    def load_conversation(self, conv_id):
        self.conv_id = conv_id
        self.messages, _usage = self.store.load(conv_id)

    def list_conversations(self):
        return self.store.list_all()

    def rename_conversation(self, conv_id, title):
        return {"ok": self.store.rename(conv_id, title), "id": conv_id, "title": title}

    def delete_conversation(self, conv_id):
        deleted = self.store.delete(conv_id)
        if self.conv_id == conv_id:
            self.conv_id = None
            self.messages = []
        return {"ok": deleted, "id": conv_id, "deleted": deleted}


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


class SkillApiFakeAgent(FakeAgent):
    def __init__(self, skills_dir):
        self.skill_loader = SkillLoader(str(skills_dir))
        self.skills = self.skill_loader.load()
        self.skill_index = SkillPromptIndex({})
        self.tools = FakeTools()

    def reload_skills(self):
        self.skills = self.skill_loader.reload()
        self.skill_index.clear_cache()
        return {
            "ok": not self.skill_loader.errors,
            "count": len(self.skills),
            "skills": self.skill_summaries(include_unavailable=True),
            "errors": list(self.skill_loader.errors),
        }

    def skill_summaries(self, include_unavailable=False):
        return self.skill_index.summaries(
            self.skills,
            available_tools=self.tools.names(),
            include_unavailable=include_unavailable,
        )


class ToolsetConfigFakeAgent(FakeAgent):
    def __init__(self):
        self.tools = ToolRegistry()
        self.tools.register(
            name="read_file",
            description="Read file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            handler=lambda **kwargs: json.dumps({"ok": True}),
            toolset="file",
        )
        self.tools.register(
            name="write_file",
            description="Write file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            handler=lambda **kwargs: json.dumps({"ok": True}),
            toolset="file",
        )
        self.messages = []
        self.conv_id = "toolsets"

    def refresh_capabilities(self):
        return None


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
        read_tool = next(item for item in payload["tools"]["items"] if item["name"] == "read_file")
        self.assertEqual(read_tool["risk"], "low")
        self.assertEqual(read_tool["exposure"], "direct")
        self.assertIn("description", read_tool)
        self.assertEqual(payload["tools"]["diagnostics"]["summary"]["total"], 2)
        self.assertEqual(payload["memory"]["providers"][0]["records"], 3)
        self.assertEqual(payload["mcp"]["servers"][0]["name"], "demo")
        self.assertIn("capabilities", payload)
        self.assertEqual(payload["capabilities"]["by_name"]["tools"]["metadata"]["total"], 2)

    def test_diagnostics_endpoints_report_model_mcp_and_tool_health(self):
        config = {
            "active_model": "ready",
            "models": {
                "ready": {
                    "name": "ready-model",
                    "base_url": "https://ready.example/v1",
                    "api_key": "ready-key",
                    "max_tokens": 4096,
                    "context_window": 128000,
                },
                "missing": {
                    "name": "missing-model",
                    "base_url": "",
                    "api_key": "YOUR_API_KEY",
                },
            },
            "mcpServers": {
                "demo": {
                    "type": "stdio",
                    "command": "definitely_missing_sierra_mcp_command",
                    "enabled": True,
                }
            },
        }
        app = create_dashboard_app(
            FakeAgent(),
            config=config,
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        model_response = client.get("/api/config/models/diagnostics")
        mcp_response = client.get("/api/config/mcp/diagnostics")
        tool_response = client.get("/api/tools/diagnostics")

        self.assertEqual(model_response.status_code, 200)
        model_items = model_response.json()["diagnostics"]["items"]
        self.assertEqual(next(item for item in model_items if item["key"] == "ready")["status"], "active")
        self.assertEqual(next(item for item in model_items if item["key"] == "missing")["status"], "needs_setup")
        self.assertEqual(mcp_response.status_code, 200)
        mcp_items = mcp_response.json()["diagnostics"]["items"]
        self.assertEqual(mcp_items[0]["name"], "demo")
        self.assertTrue(mcp_items[0]["issues"])
        self.assertEqual(tool_response.status_code, 200)
        self.assertEqual(tool_response.json()["diagnostics"]["summary"]["total"], 2)

    def test_mcp_diagnostics_matches_config_names_to_sanitized_runtime_names(self):
        agent = FakeAgent()
        agent.mcp_status = lambda: {
            "servers": [
                {
                    "name": "mcd_mcp",
                    "type": "streamablehttp",
                    "status": "running",
                    "running": True,
                    "tools": 29,
                },
                {
                    "name": "amap_maps",
                    "type": "streamablehttp",
                    "status": "running",
                    "running": True,
                    "tools": 15,
                },
            ]
        }
        config = {
            "mcpServers": {
                "mcd-mcp": {
                    "type": "streamablehttp",
                    "url": "https://mcp.example.test",
                },
                "amap-maps": {
                    "type": "streamablehttp",
                    "url": "https://maps.example.test",
                },
            }
        }
        app = create_dashboard_app(
            agent,
            config=config,
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.get("/api/config/mcp/diagnostics")

        self.assertEqual(response.status_code, 200)
        diagnostics = response.json()["diagnostics"]
        self.assertEqual(diagnostics["summary"]["total"], 2)
        self.assertEqual(diagnostics["summary"]["running"], 2)
        self.assertEqual(diagnostics["summary"]["tools"], 44)
        self.assertEqual(
            [(item["name"], item["status"], item["tools"]) for item in diagnostics["items"]],
            [("mcd-mcp", "running", 29), ("amap-maps", "running", 15)],
        )

    def test_capabilities_endpoint_returns_unified_status(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.get("/api/capabilities")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["by_name"]["tools"]["metadata"]["total"], 2)
        self.assertIn("memory", payload["by_name"])

    def test_toolset_config_endpoint_saves_and_applies_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = {
                "active_model": "test",
                "models": {"test": {"name": "test-model", "context_window": 128000}},
                "tools": {"toolsets": {"enabled": ["default"]}},
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")
            agent = ToolsetConfigFakeAgent()
            app = create_dashboard_app(
                agent,
                config=config,
                config_path=config_path,
                sierra_dir=".",
                static_dir="missing-dist",
            )
            client = TestClient(app)

            response = client.post(
                "/api/config/toolsets",
                json={
                    "enabled": ["file_readonly"],
                    "disabled": [],
                    "additional_tools": [],
                    "disabled_tools": [],
                    "custom": {},
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertTrue(agent.tools.is_tool_enabled("read_file"))
            self.assertFalse(agent.tools.is_tool_enabled("write_file"))
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["tools"]["toolsets"]["enabled"], ["file_readonly"])

    def test_skill_api_reads_creates_and_updates_documents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skills_dir = Path(temp_dir) / "skills"
            demo_dir = skills_dir / "custom" / "demo-skill"
            demo_dir.mkdir(parents=True)
            demo_path = demo_dir / "SKILL.md"
            demo_path.write_text(
                "---\n"
                "name: demo-skill\n"
                "description: Demo skill.\n"
                "---\n\n"
                "# Demo\n\n"
                "Follow the demo workflow.\n",
                encoding="utf-8",
            )
            agent = SkillApiFakeAgent(skills_dir)
            app = create_dashboard_app(
                agent,
                config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
                sierra_dir=".",
                static_dir="missing-dist",
            )
            client = TestClient(app)

            catalog_response = client.get("/api/skills")
            detail_response = client.get("/api/skills/demo-skill")
            update_response = client.put(
                "/api/skills/demo-skill",
                json={
                    "content": (
                        "---\n"
                        "name: demo-skill\n"
                        "description: Updated skill.\n"
                        "---\n\n"
                        "# Demo\n\n"
                        "Use the updated workflow.\n"
                    )
                },
            )
            create_response = client.post(
                "/api/skills",
                json={
                    "name": "new-skill",
                    "category": "custom",
                    "content": (
                        "---\n"
                        "name: new-skill\n"
                        "description: New skill.\n"
                        "---\n\n"
                        "# New Skill\n\n"
                        "Use the new workflow.\n"
                    ),
                },
            )

            self.assertEqual(catalog_response.status_code, 200)
            self.assertTrue(any(item["name"] == "demo-skill" for item in catalog_response.json()["items"]))
            self.assertEqual(detail_response.status_code, 200)
            self.assertIn("Follow the demo workflow.", detail_response.json()["content"])
            self.assertEqual(update_response.status_code, 200)
            self.assertTrue(update_response.json()["ok"])
            self.assertIn("Use the updated workflow.", demo_path.read_text(encoding="utf-8"))
            self.assertEqual(agent.skill_loader.get("demo-skill").description, "Updated skill.")
            self.assertEqual(create_response.status_code, 200)
            self.assertTrue(create_response.json()["ok"])
            self.assertIsNotNone(agent.skill_loader.get("new-skill"))
            self.assertTrue((skills_dir / "custom" / "new-skill" / "SKILL.md").exists())

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

    def test_command_catalog_and_completion_are_registry_backed(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        catalog = client.get("/api/commands/catalog")
        completion = client.get("/api/commands/complete", params={"q": "/mem", "limit": 5})

        self.assertEqual(catalog.status_code, 200)
        catalog_items = catalog.json()["items"]
        self.assertTrue(any(item["label"] == "/memory-search" for item in catalog_items))
        self.assertEqual(completion.status_code, 200)
        labels = [item["label"] for item in completion.json()["items"]]
        self.assertIn("/memory", labels)
        self.assertIn("/memory-search", labels)

    def test_command_endpoint_resolves_registry_aliases(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.post("/api/command", json={"command": "/list", "text": "/list"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["type"], "sessions")

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

    def test_command_endpoint_compress_accepts_slash_command(self):
        app = create_dashboard_app(
            FakeAgent(),
            config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.post("/api/command", json={"command": "/compress", "text": "/compress"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["type"], "compress")
        self.assertIn("压缩完成", payload["text"])

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
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["id"])
        self.assertEqual(payload["messages"], [])
        self.assertIsNone(payload["conversation"]["id"])
        self.assertEqual(payload["conversation"]["message_count"], 0)

    def test_conversation_preview_does_not_activate_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(storage_dir=temp_dir)
            store.save(
                "conv-1",
                [{"role": "user", "content": "preview hello"}],
                {"input": 1},
                "preview",
            )
            agent = StoreBackedFakeAgent(store)
            app = create_dashboard_app(
                agent,
                config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
                sierra_dir=".",
                static_dir="missing-dist",
            )
            client = TestClient(app)

            response = client.get("/api/conversations/conv-1/preview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["messages"][0]["text"], "preview hello")
        self.assertEqual(agent.conv_id, "active")

    def test_conversation_activate_rename_and_delete_endpoints(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(storage_dir=temp_dir)
            store.save(
                "conv-1",
                [{"role": "user", "content": "loaded hello"}],
                {"input": 1},
                "old",
            )
            agent = StoreBackedFakeAgent(store)
            app = create_dashboard_app(
                agent,
                config={"active_model": "test", "models": {"test": {"name": "test-model"}}},
                sierra_dir=".",
                static_dir="missing-dist",
            )
            client = TestClient(app)

            activate = client.post("/api/conversations/conv-1/activate")
            rename = client.patch("/api/conversations/conv-1", json={"title": "new name"})
            delete = client.delete("/api/conversations/conv-1")

        self.assertEqual(activate.status_code, 200)
        self.assertTrue(activate.json()["ok"])
        self.assertEqual(agent.conv_id, None)
        self.assertEqual(rename.status_code, 200)
        self.assertTrue(rename.json()["ok"])
        self.assertEqual(delete.status_code, 200)
        self.assertTrue(delete.json()["ok"])

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

    def test_upload_endpoint_marks_image_files(self):
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
                    "filename": "forest.png",
                    "content_base64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii"),
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["kind"], "image")
            self.assertEqual(payload["mime_type"], "image/png")

    def test_model_config_saves_vision_capability_flag(self):
        config = {
            "active_model": "base",
            "models": {
                "base": {
                    "name": "base-model",
                    "base_url": "https://base.example/v1",
                    "api_key": "base-key",
                }
            },
        }
        app = create_dashboard_app(
            FakeAgent(),
            config=config,
            sierra_dir=".",
            static_dir="missing-dist",
        )
        client = TestClient(app)

        response = client.post(
            "/api/config/models",
            json={
                "key": "vision",
                "name": "vision-model",
                "base_url": "https://vision.example/v1",
                "api_key": "vision-key",
                "max_tokens": 4096,
                "temperature": 0.2,
                "context_window": 128000,
                "supports_vision": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(config["models"]["vision"]["supports_vision"])
        models = response.json()["models"]
        vision = next(model for model in models if model["key"] == "vision")
        self.assertTrue(vision["supports_vision"])

    def test_reload_config_command_rebuilds_agent_from_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = {
                "active_model": "base",
                "models": {
                    "base": {
                        "name": "memory-model",
                        "base_url": "https://memory.example/v1",
                        "api_key": "memory-key",
                    }
                },
            }
            disk_config = {
                "active_model": "base",
                "models": {
                    "base": {
                        "name": "disk-model",
                        "base_url": "https://disk.example/v1",
                        "api_key": "disk-key",
                    }
                },
                "auxiliary": {
                    "vision": {
                        "enabled": True,
                        "provider": "auto",
                        "credentials_model": "base",
                        "model": "disk-vision",
                    }
                },
            }
            config_path.write_text(json.dumps(disk_config), encoding="utf-8")

            def make_agent(model_key):
                agent = FakeAgent()
                agent.llm = SimpleNamespace(model=config["models"][model_key]["name"])
                agent.model = agent.llm.model
                return agent

            app = create_dashboard_app(
                FakeAgent(),
                config=config,
                config_path=config_path,
                make_agent=make_agent,
                sierra_dir=".",
                static_dir="missing-dist",
            )
            client = TestClient(app)

            response = client.post(
                "/api/command",
                json={"command": "/reload-config", "text": "/reload-config"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["type"], "config_reloaded")
        self.assertEqual(config["models"]["base"]["name"], "disk-model")
        self.assertEqual(app.state.agent.llm.model, "disk-model")


if __name__ == "__main__":
    unittest.main()
