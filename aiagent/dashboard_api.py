from __future__ import annotations

import base64
import binascii
import json
import os
import queue
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config_validation import StartupConfigError, format_config_issues, validate_model_config
from .gateway import GatewayRuntime, sanitize_gateway_event
from .safety import sanitize_text
from .tools.registry import BRIDGE_TOOL_NAMES


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


class ToolApprovalRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    decision: str = Field(min_length=1, max_length=20)


class UserInputResponseRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=12000)
    label: str = Field(default="", max_length=1000)
    free_text: bool = False
    cancelled: bool = False


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=120)
    text: str = Field(default="", max_length=12000)
    key: str = Field(default="", max_length=200)
    id: str = Field(default="", max_length=200)
    query: str = Field(default="", max_length=12000)
    prompt: str = Field(default="", max_length=12000)
    count: int | None = None
    limit: int | None = None
    interval_minutes: int | None = None
    confirmed: bool = False


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=260)
    content_base64: str = Field(min_length=1, max_length=40_000_000)


class ModelConfigRequest(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=800)
    api_key: str = Field(default="", max_length=4000)
    max_tokens: int = Field(default=4096, ge=1, le=2_000_000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    context_window: int = Field(default=256_000, ge=1, le=10_000_000)


class MCPServerConfigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="stdio", max_length=40)
    command: str = Field(default="", max_length=1000)
    args: list[str] = Field(default_factory=list)
    url: str = Field(default="", max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    cwd: str = Field(default="", max_length=1000)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


def create_dashboard_app(
    agent: Any,
    *,
    config: dict[str, Any] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    make_agent: Callable[[str], Any] | None = None,
    static_dir: str | os.PathLike[str] | None = None,
    sierra_dir: str | os.PathLike[str] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Sierra Dashboard",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    root_dir = Path(sierra_dir or getattr(agent, "sierra_dir", ".")).resolve()
    app.state.agent = agent
    app.state.config = config or {}
    app.state.config_path = Path(config_path).resolve() if config_path else None
    app.state.make_agent = make_agent
    app.state.sierra_dir = root_dir
    app.state.gateway = GatewayRuntime(
        agent,
        config=app.state.config,
        config_path=app.state.config_path,
        make_agent=make_agent,
        id_factory=lambda: uuid.uuid4().hex,
    )
    app.state.chat_lock = app.state.gateway.chat_lock
    app.state.approval_lock = app.state.gateway.approval_lock
    app.state.pending_approvals = app.state.gateway.pending_approvals
    app.state.input_lock = app.state.gateway.input_lock
    app.state.pending_inputs = app.state.gateway.pending_inputs

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "sierra-dashboard",
            "time": datetime.now().isoformat(timespec="seconds"),
        }

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return build_dashboard_payload(
            app.state.gateway.agent,
            config=app.state.config,
            sierra_dir=app.state.sierra_dir,
        )

    @app.get("/api/config/models")
    def config_models() -> dict[str, Any]:
        config = app.state.config if isinstance(app.state.config, dict) else {}
        return {
            "ok": True,
            "active": str(config.get("active_model") or ""),
            "models": _models_from_config(config, include_details=True),
        }

    @app.post("/api/config/models")
    def save_model_config(request: ModelConfigRequest) -> dict[str, Any]:
        with app.state.chat_lock:
            return _save_model_config(app, request)

    @app.delete("/api/config/models/{model_key}")
    def delete_model_config(model_key: str) -> dict[str, Any]:
        with app.state.chat_lock:
            return _delete_model_config(app, model_key)

    @app.get("/api/config/mcp")
    def config_mcp() -> dict[str, Any]:
        config = app.state.config if isinstance(app.state.config, dict) else {}
        return {
            "ok": True,
            "servers": _safe_mcp_servers(config),
            "status": _mcp(app.state.gateway.agent),
        }

    @app.post("/api/config/mcp")
    def save_mcp_config(request: MCPServerConfigRequest) -> dict[str, Any]:
        with app.state.chat_lock:
            return _save_mcp_config(app, request)

    @app.delete("/api/config/mcp/{server_name}")
    def delete_mcp_config(server_name: str) -> dict[str, Any]:
        with app.state.chat_lock:
            return _delete_mcp_config(app, server_name)

    @app.post("/api/skills/reload")
    def reload_skills_endpoint() -> dict[str, Any]:
        with app.state.chat_lock:
            result = _safe_call(app.state.gateway.agent, "reload_skills", default={})
            if not isinstance(result, dict):
                result = {}
            return {
                "ok": bool(result.get("ok", True)),
                "count": result.get("count", len(result.get("skills", []) or [])),
                "skills": result.get("skills", []),
                "errors": result.get("errors", []),
                "text": f"技能已重新加载，共 {result.get('count', len(result.get('skills', []) or []))} 个。",
            }

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> dict[str, Any]:
        message = sanitize_text(request.message.strip(), max_length=12000)
        events: list[dict[str, Any]] = []
        result = app.state.gateway.chat(
            message,
            emit=events.append,
            interaction="deny",
            suppress_output=True,
        )

        return {
            "answer": result.answer,
            "events": events[-80:],
            "usage": _usage(result.usage),
        }

    @app.post("/api/chat/stream")
    def chat_stream(request: ChatRequest) -> StreamingResponse:
        message = sanitize_text(request.message.strip(), max_length=12000)
        event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def emit(event: dict[str, Any]) -> None:
            event_queue.put(event)

        def worker() -> None:
            try:
                result = app.state.gateway.chat(
                    message,
                    emit=emit,
                    interaction="interactive",
                    suppress_output=True,
                )
                if result.interrupted:
                    emit({
                        "type": "interrupted",
                        "text": "已中断当前处理。",
                        "usage": _usage(result.usage),
                    })
                else:
                    emit({
                        "type": "done",
                        "answer": result.answer,
                        "usage": _usage(result.usage),
                    })
            except Exception as exc:
                emit({
                    "type": "error",
                    "text": sanitize_text(str(exc), max_length=1000),
                })
            finally:
                event_queue.put(None)

        def stream_events():
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            while True:
                event = event_queue.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(stream_events(), media_type="application/x-ndjson")

    @app.post("/api/chat/approval")
    def chat_approval(request: ToolApprovalRequest) -> dict[str, Any]:
        return app.state.gateway.respond_tool_approval(request.id, request.decision)

    @app.post("/api/chat/input")
    def chat_input(request: UserInputResponseRequest) -> dict[str, Any]:
        return app.state.gateway.respond_user_input(request.id, {
            "value": request.value,
            "label": request.label,
            "free_text": bool(request.free_text),
            "cancelled": request.cancelled,
        })

    @app.post("/api/chat/cancel")
    def chat_cancel() -> dict[str, Any]:
        return app.state.gateway.cancel_current("web")

    @app.post("/api/command")
    def command(request: CommandRequest) -> dict[str, Any]:
        with app.state.chat_lock:
            return _repair_payload_text(_execute_dashboard_command(app, request))

    @app.get("/api/context/suggestions")
    def context_suggestions(q: str = "", limit: int = 24) -> dict[str, Any]:
        query = sanitize_text(str(q or "").strip(), max_length=240)
        safe_limit = max(1, min(_int(limit, 24), 60))
        workspace = Path(getattr(app.state.gateway.agent, "workspace", "") or app.state.sierra_dir).resolve()
        if not workspace.exists() or not workspace.is_dir():
            workspace = app.state.sierra_dir
        return {
            "items": _context_reference_suggestions(workspace, query, safe_limit),
            "workspace": str(workspace),
        }

    @app.post("/api/uploads")
    def upload_file(request: UploadRequest) -> dict[str, Any]:
        workspace = Path(getattr(app.state.gateway.agent, "workspace", "") or app.state.sierra_dir).resolve()
        if not workspace.exists() or not workspace.is_dir():
            workspace = app.state.sierra_dir
        uploads_dir = (workspace / "uploads").resolve()
        if not _is_relative_to(uploads_dir, workspace):
            return {"ok": False, "error": "upload directory is outside workspace"}

        try:
            raw = base64.b64decode(request.content_base64, validate=True)
        except (binascii.Error, ValueError):
            return {"ok": False, "error": "invalid base64 content"}
        max_bytes = 25 * 1024 * 1024
        if len(raw) > max_bytes:
            return {"ok": False, "error": f"file is too large; limit is {max_bytes // 1024 // 1024} MB"}

        uploads_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_upload_filename(request.filename)
        target = _unique_upload_path(uploads_dir, safe_name)
        if not _is_relative_to(target, uploads_dir):
            return {"ok": False, "error": "invalid upload path"}
        target.write_bytes(raw)
        relative_path = target.relative_to(workspace).as_posix()
        return {
            "ok": True,
            "file_path": str(target),
            "relative_path": relative_path,
            "size": len(raw),
            "reference": f"@file:{_quote_reference_value(relative_path)} ",
        }

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict[str, Any]:
        conversation_id = sanitize_text(conversation_id.strip(), max_length=120)
        if not conversation_id:
            return {"id": "", "messages": []}
        with app.state.chat_lock:
            app.state.gateway.agent.load_conversation(conversation_id)
            usage = app.state.gateway.agent.usage_snapshot()
            messages = _web_messages(getattr(app.state.gateway.agent, "messages", []))
        return {
            "id": conversation_id,
            "messages": messages,
            "usage": _usage(usage if isinstance(usage, dict) else {}),
        }

    @app.post("/api/conversations/new")
    def new_conversation() -> dict[str, Any]:
        with app.state.chat_lock:
            if hasattr(app.state.gateway.agent, "checkpoint_conversation"):
                app.state.gateway.agent.checkpoint_conversation()
            app.state.gateway.agent.reset()
            app.state.gateway.agent.conv_id = None
            usage = app.state.gateway.agent.usage_snapshot()
        return {
            "id": None,
            "messages": [],
            "usage": _usage(usage if isinstance(usage, dict) else {}),
        }

    dist_dir = Path(static_dir) if static_dir is not None else root_dir / "web" / "dist"
    dist_dir = dist_dir.resolve()
    index_file = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"
    brand_dir = dist_dir / "brand"

    @app.get("/brand/{asset_path:path}")
    def brand_asset(asset_path: str) -> FileResponse:
        target = (brand_dir / asset_path).resolve()
        if brand_dir.exists() and target.is_file() and _is_relative_to(target, brand_dir):
            return FileResponse(target)
        fallback = (root_dir / "web" / "public" / "brand" / asset_path).resolve()
        public_brand_dir = (root_dir / "web" / "public" / "brand").resolve()
        if fallback.is_file() and _is_relative_to(fallback, public_brand_dir):
            return FileResponse(fallback)
        return FileResponse(index_file)

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    if brand_dir.exists():
        app.mount("/brand", StaticFiles(directory=str(brand_dir)), name="brand")

    if index_file.exists():
        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            return _index_response(index_file)

    return app


def _index_response(index_file: Path) -> FileResponse:
    return FileResponse(
        index_file,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _sanitize_status_event(event: dict[str, Any]) -> dict[str, Any]:
    return sanitize_gateway_event(event)


def _safe_options(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    options = []
    for item in value[:8]:
        if isinstance(item, str):
            options.append({
                "label": sanitize_text(item, max_length=120),
                "value": sanitize_text(item, max_length=120),
                "description": "",
            })
        elif isinstance(item, dict):
            options.append({
                "label": sanitize_text(str(item.get("label") or item.get("value") or ""), max_length=120),
                "value": sanitize_text(str(item.get("value") or item.get("label") or ""), max_length=120),
                "description": sanitize_text(str(item.get("description") or ""), max_length=400),
            })
    return [item for item in options if item["label"]]


def _execute_dashboard_command(app: FastAPI, request: CommandRequest) -> dict[str, Any]:
    agent = app.state.agent
    command, argument = _normalize_command_request(request)
    config = app.state.config if isinstance(app.state.config, dict) else {}

    if command in {"help", "?"}:
        return _ok("help", _format_help())

    if command in {"list", "sessions"}:
        sessions = _safe_call(agent, "list_conversations", default=[])
        if not isinstance(sessions, list):
            sessions = []
        return _ok("sessions", _format_sessions(sessions), sessions=sessions)

    if command in {"session_search", "session-search"}:
        query = request.query.strip() or argument
        if not query:
            return _ok("session_search", "用法: /session-search <关键词>", success=False)
        results = _search_sessions(agent, query)
        return _ok("session_search", _format_session_search(results), results=results)

    if command in {"session_load", "session-load"}:
        conversation_id = request.id.strip() or argument
        if not conversation_id:
            return _ok("session_load", "用法: /session-load <id>", success=False)
        _auto_save_web(agent)
        result = _safe_call(agent, "load_conversation", conversation_id, default=None)
        if isinstance(result, dict) and result.get("error"):
            return _ok("session_load", f"加载会话失败: {result['error']}", success=False)
        return {
            "ok": True,
            "type": "session_loaded",
            "text": f"已切换到会话 {conversation_id}",
            "id": conversation_id,
            "messages": _web_messages(getattr(agent, "messages", [])),
            "usage": _usage(_usage_snapshot(agent)),
        }

    if command in {"new"}:
        _auto_save_web(agent)
        _safe_call(agent, "reset", default=None)
        try:
            agent.conv_id = None
        except Exception:
            pass
        return {
            "ok": True,
            "type": "new",
            "text": "新会话已创建。Sierra 会从这里重新开始。",
            "messages": [],
            "usage": _usage(_usage_snapshot(agent)),
        }

    if command in {"reset"}:
        _safe_call(agent, "reset", default=None)
        return {
            "ok": True,
            "type": "reset",
            "text": "当前会话已重置。",
            "messages": _web_messages(getattr(agent, "messages", [])),
            "usage": _usage(_usage_snapshot(agent)),
        }

    if command == "undo":
        count = _positive_int(request.count, argument, default=1, maximum=20)
        result = _safe_call(agent, "undo_last_turn", count, default={})
        if not isinstance(result, dict):
            result = {}
        _auto_save_web(agent)
        return {
            "ok": bool(result.get("ok", True)),
            "type": "undo",
            "text": (
                f"已撤回 {result.get('removed_user_turns', count)} 轮对话。"
                if result.get("ok", True)
                else result.get("error", "没有可撤回的对话。")
            ),
            "messages": _web_messages(getattr(agent, "messages", [])),
            "usage": _usage(_usage_snapshot(agent)),
        }

    if command == "retry":
        result = _safe_call(agent, "retry_last_turn", default={})
        if not isinstance(result, dict) or not result.get("ok"):
            return _ok("retry", (result or {}).get("error", "没有可以重试的上一轮。"), success=False)
        _auto_save_web(agent)
        return {
            "ok": True,
            "type": "retry_ready",
            "text": "已回退上一轮，正在重试。",
            "query": result.get("user_message", ""),
            "messages": _web_messages(getattr(agent, "messages", [])),
            "usage": _usage(_usage_snapshot(agent)),
        }

    if command == "compress":
        before_messages = len(getattr(agent, "messages", []) or [])
        result = _safe_call(agent, "compress_messages", default={}, force=True)
        if not isinstance(result, dict):
            result = {}
        if result.get("compressed"):
            text = (
                f"压缩完成: {before_messages} → {len(getattr(agent, 'messages', []) or [])} 条，"
                f"约 {result.get('before_tokens', '?')} → {result.get('after_tokens', '?')} tokens"
            )
        else:
            text = result.get("reason") or "当前没有可安全压缩的完整历史轮次。"
        return _ok("compress", text, usage=_usage(_usage_snapshot(agent)))

    if command == "memory":
        status = _safe_call(agent, "memory_status", default={})
        return _ok("memory", _format_memory_status(status if isinstance(status, dict) else {}), status=status)

    if command in {"memory_search", "memory-search"}:
        query = request.query.strip() or argument
        if not query:
            return _ok("memory_search", "用法: /memory-search <问题>", success=False)
        limit = _positive_int(request.limit, "", default=5, maximum=10)
        results = _safe_call(agent, "memory_search", query, limit=limit, default=[])
        if not isinstance(results, list):
            results = []
        return _ok("memory_search", _format_memory_search(results), results=results)

    if command in {"memory_forget", "memory-forget"}:
        memory_id = request.id.strip() or argument
        try:
            parsed_id = int(memory_id)
            if parsed_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return _ok("memory_action", "记忆 ID 必须是正整数。用法: /memory-forget <ID>", success=False)
        if not request.confirmed:
            return _confirm("memory_forget", f"确认删除向量记忆 #{parsed_id} 吗？")
        result = _safe_call(agent, "memory_forget", parsed_id, default={})
        success = bool(isinstance(result, dict) and result.get("ok"))
        return _ok(
            "memory_action",
            f"已删除向量记忆 #{parsed_id}。" if success else (result or {}).get("error", "删除失败"),
            success=success,
        )

    if command in {"memory_clear", "memory-clear"}:
        if not request.confirmed:
            return _confirm("memory_clear", "确认清空当前工作区的全部向量记忆吗？")
        result = _safe_call(agent, "memory_clear", default={})
        success = bool(isinstance(result, dict) and result.get("ok"))
        deleted = (result or {}).get("deleted", 0) if isinstance(result, dict) else 0
        return _ok(
            "memory_action",
            f"已清空当前工作区的 {deleted} 条向量记忆。" if success else (result or {}).get("error", "清空失败"),
            success=success,
        )

    if command == "audit":
        records = _safe_call(agent, "audit_recent", 20, default=[])
        if not isinstance(records, list):
            records = []
        return _ok("audit", _format_audit(records), records=records)

    if command == "task":
        task = _safe_call(agent, "task_status", default=None)
        return _ok("task_status", _format_task_status(task if isinstance(task, dict) else None), task=task)

    if command in {"task_cancel", "task-cancel", "task_abandon"}:
        task = _safe_call(agent, "task_status", default=None)
        task_id = request.id.strip() or argument or (task or {}).get("id", "")
        if not task_id:
            return _ok("task_recovery_result", "当前没有可放弃的任务。", success=False, task=None)
        if not request.confirmed:
            return _confirm("task_abandon", "确认放弃当前任务计划吗？")
        result = _safe_call(agent, "abandon_task", task_id, default={})
        success = bool(isinstance(result, dict) and result.get("ok"))
        return _ok(
            "task_recovery_result",
            "已放弃当前任务。" if success else (result or {}).get("error", "放弃任务失败"),
            success=success,
            task=None,
        )

    if command in {"task_resume", "task-resume"}:
        task_id = request.id.strip() or argument
        result = _safe_call(agent, "resume_task", task_id, default={})
        success = bool(isinstance(result, dict) and result.get("ok"))
        return _ok(
            "task_recovery_result",
            "已恢复未完成任务。" if success else (result or {}).get("error", "恢复任务失败"),
            success=success,
            task=(result or {}).get("task") if isinstance(result, dict) else None,
        )

    if command == "jobs":
        status = _safe_call(agent, "background_jobs_status", 20, default={})
        text = status.get("text") if isinstance(status, dict) else ""
        return _ok("jobs", text or _format_jobs(status if isinstance(status, dict) else {}), status=status)

    if command == "cron":
        status = _safe_call(agent, "cron_status", default={})
        return _ok("cron", _format_cron_status(status if isinstance(status, dict) else {}), status=status, tasks=(status or {}).get("tasks", []))

    if command in {"cron_add", "cron-add"}:
        interval = _positive_int(request.interval_minutes, "", default=0, maximum=525600)
        prompt = request.prompt.strip()
        if not prompt:
            parts = argument.split(maxsplit=1)
            if len(parts) == 2:
                interval = _positive_int(None, parts[0], default=interval or 60, maximum=525600)
                prompt = parts[1].strip()
        if interval <= 0 or not prompt:
            return _ok("cron", "用法: /cron-add <分钟> <提示>", success=False)
        result = _safe_call(agent, "cron_add", prompt, interval, default={})
        success = bool(isinstance(result, dict) and result.get("ok"))
        status = _safe_call(agent, "cron_status", default={})
        return _ok(
            "cron",
            f"已创建定时提示 {((result or {}).get('task') or {}).get('id', '')}。" if success else (result or {}).get("error", "创建失败"),
            success=success,
            tasks=(status or {}).get("tasks", []) if isinstance(status, dict) else [],
        )

    if command in {"cron_remove", "cron-remove"}:
        task_id = request.id.strip() or argument
        status = _safe_call(agent, "cron_status", default={})
        tasks = (status or {}).get("tasks", []) if isinstance(status, dict) else []
        if not task_id:
            return _ok("cron_remove_options", "请选择要删除的定时提示。", tasks=tasks)
        if not request.confirmed:
            return _confirm("cron_remove", "确认删除这个定时提示吗？")
        result = _safe_call(agent, "cron_remove", task_id, default={})
        success = bool(isinstance(result, dict) and result.get("ok"))
        status = _safe_call(agent, "cron_status", default={})
        return _ok(
            "cron",
            "已删除定时提示。" if success else (result or {}).get("error", "未找到该定时提示。"),
            success=success,
            tasks=(status or {}).get("tasks", []) if isinstance(status, dict) else [],
        )

    if command == "mcp":
        status = _safe_call(agent, "mcp_status", default={})
        return _ok("mcp", _format_mcp(status if isinstance(status, dict) else {}), status=status)

    if command == "skills":
        skills = _safe_call(agent, "skill_summaries", default=[], include_unavailable=True)
        errors = list(getattr(getattr(agent, "skill_loader", None), "errors", []) or [])
        return _ok("skills", _format_skills(skills if isinstance(skills, list) else []), skills=skills, errors=errors)

    if command in {"skills_reload", "skills-reload"}:
        result = _safe_call(agent, "reload_skills", default={})
        skills = result.get("skills", []) if isinstance(result, dict) else []
        errors = result.get("errors", []) if isinstance(result, dict) else []
        return _ok("skills", f"技能已重新加载，共 {len(skills)} 个。", skills=skills, errors=errors, reloaded=True)

    if command in {"skills_stats", "skills-stats"}:
        stats = _safe_call(agent, "skill_usage_stats", 20, default={})
        return _ok("skills_stats", _format_skill_usage_stats(stats if isinstance(stats, dict) else {}), stats=stats)

    if command in {"debug_context", "debug-context"}:
        status = _safe_call(agent, "debug_context_status", default={})
        text = status.get("text") if isinstance(status, dict) else ""
        return _ok("debug_context", text or _format_debug_context(status if isinstance(status, dict) else {}), status=status)

    if command in {"model", "models"}:
        model_key = request.key.strip() or argument
        if not model_key:
            models = _models_from_config(config)
            return _ok("models", _format_models(models), models=models, active=config.get("active_model", ""))
        return _switch_model(app, model_key)

    if command in {"set_model", "set-model"}:
        model_key = request.key.strip() or argument
        return _switch_model(app, model_key)

    if command == "quit":
        return _ok("quit", "Web 模式下不会关闭服务。要退出请停止运行 sierra web 的终端。", success=False)

    return _ok("unknown", f"未知命令: /{command}。输入 /help 查看可用命令。", success=False)


def _normalize_command_request(request: CommandRequest) -> tuple[str, str]:
    raw = (request.text or request.command or "").strip()
    if raw.startswith("/"):
        raw = raw[1:]
    if not raw:
        raw = request.command.strip().lstrip("/")
    if " " in raw:
        command, argument = raw.split(maxsplit=1)
    else:
        command, argument = raw, ""
    command = (request.command.strip().lstrip("/") or command).strip()
    if request.command.strip().startswith("/"):
        command = request.command.strip().lstrip("/").split(maxsplit=1)[0]
    command = command.replace("-", "_")
    return command.lower(), argument.strip()


def _ok(event_type: str, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": bool(extra.pop("success", True)),
        "type": event_type,
        "text": sanitize_text(_repair_mojibake(str(text or "")), max_length=24000),
        **extra,
    }


def _confirm(command: str, text: str) -> dict[str, Any]:
    return {
        "ok": False,
        "type": "confirm",
        "command": command,
        "text": sanitize_text(text, max_length=1000),
        "requires_confirmation": True,
    }


def _usage_snapshot(agent: Any) -> dict[str, Any]:
    snapshot = _safe_call(agent, "usage_snapshot", default={})
    return snapshot if isinstance(snapshot, dict) else {}


def _auto_save_web(agent: Any) -> None:
    messages = getattr(agent, "messages", None)
    if not messages:
        return
    title = ""
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user":
            title = str(message.get("content") or "")[:30]
            break
    usage = _usage_snapshot(agent)
    _safe_call(agent, "save_conversation", default=None, usage=usage, title=title)


def _positive_int(value: Any, fallback_text: str, *, default: int, maximum: int) -> int:
    candidates = [value, fallback_text]
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        try:
            parsed = int(str(candidate).strip().split()[0])
            if parsed > 0:
                return min(parsed, maximum)
        except (TypeError, ValueError, IndexError):
            continue
    return default


def _models_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    active = str(config.get("active_model") or "")
    models = []
    for key, value in (config.get("models") or {}).items():
        if not isinstance(value, dict):
            continue
        models.append({
            "key": key,
            "name": value.get("name", key),
            "active": key == active,
        })
    return models


def _switch_model(app: FastAPI, model_key: str) -> dict[str, Any]:
    model_key = sanitize_text(model_key.strip(), max_length=200)
    config = app.state.config if isinstance(app.state.config, dict) else {}
    make_agent = getattr(app.state, "make_agent", None)
    if not model_key:
        return _ok("models", "请选择要切换的模型。", success=False, models=_models_from_config(config))
    if not config or not callable(make_agent):
        return _ok("model_changed", "Web 后端没有模型切换配置。", success=False)
    if model_key not in (config.get("models") or {}):
        return _ok("model_changed", f"未知模型: {model_key}", success=False)
    try:
        validate_model_config(config, model_key)
    except StartupConfigError as exc:
        return _ok("model_changed", format_config_issues(exc.issues), success=False)

    current_agent = app.state.agent
    _auto_save_web(current_agent)
    previous_messages = list(getattr(current_agent, "messages", []) or [])
    previous_conv_id = getattr(current_agent, "conv_id", None)
    previous_input_tokens = getattr(current_agent, "total_input_tokens", 0)
    previous_output_tokens = getattr(current_agent, "total_output_tokens", 0)
    previous_session_allows = set(getattr(getattr(current_agent, "permission_policy", None), "session_allow_tools", set()) or set())
    previous_task = _safe_call(current_agent, "task_status", default=None)

    config["active_model"] = model_key
    config_path = getattr(app.state, "config_path", None)
    if config_path:
        Path(config_path).write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    _safe_call(current_agent, "close", default=None, preserve_task=True)
    new_agent = make_agent(model_key)
    try:
        new_agent.messages = previous_messages
        new_agent.conv_id = previous_conv_id
        new_agent.total_input_tokens = previous_input_tokens
        new_agent.total_output_tokens = previous_output_tokens
        if hasattr(new_agent, "permission_policy"):
            new_agent.permission_policy.session_allow_tools.update(previous_session_allows)
        _safe_call(new_agent, "sync_memory_review_state", default=None)
        _safe_call(new_agent, "refresh_context_estimate", default=None)
        if isinstance(previous_task, dict) and previous_task.get("status") == "active":
            _safe_call(new_agent, "resume_task", previous_task.get("id"), default=None)
    except Exception:
        pass
    app.state.agent = new_agent
    gateway = getattr(app.state, "gateway", None)
    if gateway is not None:
        gateway.set_agent(new_agent)
    model_name = getattr(getattr(new_agent, "llm", None), "model", None) or getattr(new_agent, "model", "")
    return {
        "ok": True,
        "type": "model_changed",
        "key": model_key,
        "model": model_name,
        "text": f"已切换模型: {model_key}",
        "usage": _usage(_usage_snapshot(new_agent)),
        "messages": _web_messages(getattr(new_agent, "messages", [])),
    }


def _models_from_config(config: dict[str, Any], *, include_details: bool = False) -> list[dict[str, Any]]:
    active = str(config.get("active_model") or "")
    models = []
    for key, value in (config.get("models") or {}).items():
        if not isinstance(value, dict):
            continue
        item = {
            "key": key,
            "name": value.get("name", key),
            "active": key == active,
        }
        if include_details:
            item.update({
                "base_url": value.get("base_url", ""),
                "max_tokens": _int(value.get("max_tokens"), 4096),
                "temperature": float(value.get("temperature", 0.7) or 0.7),
                "context_window": _int(value.get("context_window"), 256000),
                "api_key_set": bool(str(value.get("api_key") or "").strip()),
                "api_key_preview": _secret_preview(value.get("api_key", "")),
            })
        models.append(item)
    return models


def _switch_model(app: FastAPI, model_key: str) -> dict[str, Any]:
    model_key = sanitize_text(model_key.strip(), max_length=200)
    config = app.state.config if isinstance(app.state.config, dict) else {}
    if not model_key:
        return _ok("models", "请选择要切换的模型。", success=False, models=_models_from_config(config))
    if not config:
        return _ok("model_changed", "Web 后端没有模型切换配置。", success=False)
    if model_key not in (config.get("models") or {}):
        return _ok("model_changed", f"未知模型: {model_key}", success=False)
    try:
        validate_model_config(config, model_key)
    except StartupConfigError as exc:
        return _ok("model_changed", format_config_issues(exc.issues), success=False)

    config["active_model"] = model_key
    _write_dashboard_config(app)
    result = _rebuild_agent(app, model_key)
    if not result.get("ok"):
        return result
    return {
        **result,
        "type": "model_changed",
        "key": model_key,
        "text": f"已切换模型: {model_key}",
    }


def _save_model_config(app: FastAPI, request: ModelConfigRequest) -> dict[str, Any]:
    config = app.state.config if isinstance(app.state.config, dict) else {}
    models = config.setdefault("models", {})
    if not isinstance(models, dict):
        config["models"] = {}
        models = config["models"]

    model_key = _safe_config_key(request.key)
    if not model_key:
        return {"ok": False, "text": "模型 key 只能包含字母、数字、下划线、短横线和点。"}

    existing = models.get(model_key, {}) if isinstance(models.get(model_key), dict) else {}
    api_key = request.api_key.strip()
    if not api_key and existing.get("api_key"):
        api_key = str(existing.get("api_key") or "")

    models[model_key] = {
        "name": request.name.strip(),
        "base_url": request.base_url.strip().rstrip("/"),
        "api_key": api_key,
        "max_tokens": int(request.max_tokens),
        "temperature": float(request.temperature),
        "context_window": int(request.context_window),
    }
    if not config.get("active_model"):
        config["active_model"] = model_key

    try:
        validate_model_config(config, str(config.get("active_model") or model_key))
    except StartupConfigError as exc:
        return {
            "ok": False,
            "text": format_config_issues(exc.issues),
            "models": _models_from_config(config, include_details=True),
        }

    _write_dashboard_config(app)
    reloaded = False
    if model_key == str(config.get("active_model") or ""):
        rebuilt = _rebuild_agent(app, model_key)
        if not rebuilt.get("ok"):
            return rebuilt
        reloaded = True

    return {
        "ok": True,
        "type": "model_saved",
        "text": f"模型配置已保存: {model_key}" + ("，当前 Agent 已热重载。" if reloaded else "。"),
        "active": str(config.get("active_model") or ""),
        "models": _models_from_config(config, include_details=True),
    }


def _delete_model_config(app: FastAPI, model_key: str) -> dict[str, Any]:
    config = app.state.config if isinstance(app.state.config, dict) else {}
    models = config.get("models") if isinstance(config.get("models"), dict) else {}
    model_key = _safe_config_key(model_key)
    if not model_key or model_key not in models:
        return {"ok": False, "text": f"未知模型: {model_key or '(empty)'}"}
    if model_key == str(config.get("active_model") or ""):
        return {"ok": False, "text": "不能删除当前正在使用的模型。请先切换到其他模型。"}
    if len(models) <= 1:
        return {"ok": False, "text": "至少需要保留一个模型。"}
    del models[model_key]
    _write_dashboard_config(app)
    return {
        "ok": True,
        "type": "model_deleted",
        "text": f"模型配置已删除: {model_key}",
        "active": str(config.get("active_model") or ""),
        "models": _models_from_config(config, include_details=True),
    }


def _save_mcp_config(app: FastAPI, request: MCPServerConfigRequest) -> dict[str, Any]:
    config = app.state.config if isinstance(app.state.config, dict) else {}
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        config["mcpServers"] = {}
        servers = config["mcpServers"]

    name = _safe_config_key(request.name)
    if not name:
        return {"ok": False, "text": "MCP 名称只能包含字母、数字、下划线、短横线和点。"}

    transport = _normalize_web_mcp_transport(request.type)
    existing = servers.get(name, {}) if isinstance(servers.get(name), dict) else {}
    next_server: dict[str, Any] = {"type": transport, "enabled": bool(request.enabled)}
    if transport == "streamablehttp":
        if not request.url.strip():
            return {"ok": False, "text": "streamablehttp MCP 需要填写 URL。"}
        next_server["url"] = request.url.strip()
        headers = _merge_secret_dict(existing.get("headers"), request.headers)
        if headers:
            next_server["headers"] = headers
    else:
        if not request.command.strip():
            return {"ok": False, "text": "stdio MCP 需要填写 command。"}
        next_server["command"] = request.command.strip()
        next_server["args"] = [str(arg) for arg in request.args if str(arg).strip()]
        if request.cwd.strip():
            next_server["cwd"] = request.cwd.strip()
        env = _merge_secret_dict(existing.get("env"), request.env)
        if env:
            next_server["env"] = env

    servers[name] = next_server
    _write_dashboard_config(app)
    rebuilt = _rebuild_agent(app, str(config.get("active_model") or ""))
    if not rebuilt.get("ok"):
        return rebuilt
    return {
        "ok": True,
        "type": "mcp_saved",
        "text": f"MCP 配置已保存并重新加载: {name}",
        "servers": _safe_mcp_servers(config),
        "status": _mcp(app.state.gateway.agent),
    }


def _delete_mcp_config(app: FastAPI, server_name: str) -> dict[str, Any]:
    config = app.state.config if isinstance(app.state.config, dict) else {}
    servers = config.get("mcpServers") if isinstance(config.get("mcpServers"), dict) else {}
    name = _safe_config_key(server_name)
    if not name or name not in servers:
        return {"ok": False, "text": f"未知 MCP Server: {name or '(empty)'}"}
    del servers[name]
    _write_dashboard_config(app)
    rebuilt = _rebuild_agent(app, str(config.get("active_model") or ""))
    if not rebuilt.get("ok"):
        return rebuilt
    return {
        "ok": True,
        "type": "mcp_deleted",
        "text": f"MCP 配置已删除并重新加载: {name}",
        "servers": _safe_mcp_servers(config),
        "status": _mcp(app.state.gateway.agent),
    }


def _rebuild_agent(app: FastAPI, model_key: str) -> dict[str, Any]:
    make_agent = getattr(app.state, "make_agent", None)
    if not callable(make_agent):
        return _ok("agent_reload", "Web 后端没有可用的 Agent 重建入口。", success=False)
    if not model_key:
        return _ok("agent_reload", "当前没有可用模型，无法重建 Agent。", success=False)

    current_agent = app.state.agent
    _auto_save_web(current_agent)
    previous_messages = list(getattr(current_agent, "messages", []) or [])
    previous_conv_id = getattr(current_agent, "conv_id", None)
    previous_input_tokens = getattr(current_agent, "total_input_tokens", 0)
    previous_output_tokens = getattr(current_agent, "total_output_tokens", 0)
    previous_session_allows = set(getattr(getattr(current_agent, "permission_policy", None), "session_allow_tools", set()) or set())
    previous_task = _safe_call(current_agent, "task_status", default=None)

    _safe_call(current_agent, "close", default=None, preserve_task=True)
    new_agent = make_agent(model_key)
    try:
        new_agent.messages = previous_messages
        new_agent.conv_id = previous_conv_id
        new_agent.total_input_tokens = previous_input_tokens
        new_agent.total_output_tokens = previous_output_tokens
        if hasattr(new_agent, "permission_policy"):
            new_agent.permission_policy.session_allow_tools.update(previous_session_allows)
        _safe_call(new_agent, "sync_memory_review_state", default=None)
        _safe_call(new_agent, "refresh_context_estimate", default=None)
        if isinstance(previous_task, dict) and previous_task.get("status") == "active":
            _safe_call(new_agent, "resume_task", previous_task.get("id"), default=None)
    except Exception:
        pass
    app.state.agent = new_agent
    gateway = getattr(app.state, "gateway", None)
    if gateway is not None:
        gateway.set_agent(new_agent)
    model_name = getattr(getattr(new_agent, "llm", None), "model", None) or getattr(new_agent, "model", "")
    return {
        "ok": True,
        "type": "agent_reloaded",
        "key": model_key,
        "model": model_name,
        "text": f"Agent 已重新加载: {model_key}",
        "usage": _usage(_usage_snapshot(new_agent)),
        "messages": _web_messages(getattr(new_agent, "messages", [])),
    }


def _write_dashboard_config(app: FastAPI) -> None:
    config = app.state.config if isinstance(app.state.config, dict) else {}
    config_path = getattr(app.state, "config_path", None)
    if config_path:
        Path(config_path).write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _safe_config_key(value: str) -> str:
    text = sanitize_text(str(value or "").strip(), max_length=120)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", text):
        return ""
    return text


def _normalize_web_mcp_transport(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "")
    if text in {"http", "streamable", "streamablehttp"}:
        return "streamablehttp"
    return "stdio"


def _merge_secret_dict(existing: Any, incoming: dict[str, str]) -> dict[str, str]:
    base = existing if isinstance(existing, dict) else {}
    result: dict[str, str] = {}
    for key, value in incoming.items():
        clean_key = sanitize_text(str(key).strip(), max_length=160)
        if not clean_key:
            continue
        clean_value = str(value or "")
        if _is_masked_secret(clean_value):
            if clean_key in base:
                result[clean_key] = str(base.get(clean_key) or "")
            continue
        if clean_value:
            result[clean_key] = clean_value
    return result


def _safe_mcp_servers(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_servers = config.get("mcpServers") if isinstance(config.get("mcpServers"), dict) else {}
    servers = []
    for name, server in raw_servers.items():
        if not isinstance(server, dict):
            continue
        servers.append({
            "name": name,
            "type": server.get("type") or ("streamablehttp" if server.get("url") else "stdio"),
            "enabled": server.get("enabled", True) is not False,
            "command": server.get("command", ""),
            "args": server.get("args", []) if isinstance(server.get("args"), list) else [],
            "url": server.get("url", ""),
            "cwd": server.get("cwd", ""),
            "headers": _masked_secret_dict(server.get("headers")),
            "env": _masked_secret_dict(server.get("env")),
        })
    return servers


def _masked_secret_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _mask_secret(str(raw or "")) for key, raw in value.items()}


def _secret_preview(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return _mask_secret(text)


def _mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "********"
    return f"{text[:4]}...{text[-4:]}"


def _is_masked_secret(value: str) -> bool:
    text = str(value or "").strip()
    return not text or text == "********" or ("..." in text and len(text) <= 32)


def _repair_payload_text(value: Any) -> Any:
    if isinstance(value, str):
        return _repair_mojibake(value)
    if isinstance(value, list):
        return [_repair_payload_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _repair_payload_text(item) for key, item in value.items()}
    return value


_MOJIBAKE_HINTS = (
    "�", "鈥", "鈫", "銆", "妯", "浼", "鎬", "璇", "鍛", "鏌", "鍒",
    "褰", "宸", "涓", "鐢", "閫", "鍙", "绋", "犻", "湪", "湁",
)


def _repair_mojibake(text: str) -> str:
    if not text or not any(hint in text for hint in _MOJIBAKE_HINTS):
        return text
    candidates = [text]
    for codec in ("gb18030", "gbk", "cp936"):
        try:
            candidates.append(text.encode(codec, errors="ignore").decode("utf-8", errors="ignore"))
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            continue

    def score(candidate: str) -> tuple[int, int]:
        bad = sum(candidate.count(hint) for hint in _MOJIBAKE_HINTS)
        replacement = candidate.count("�") + candidate.count("?")
        cjk = sum(1 for char in candidate if "\u4e00" <= char <= "\u9fff")
        return (bad * 6 + replacement * 2, -cjk)

    best = min(candidates, key=score)
    return best if score(best) < score(text) else text


def _format_help() -> str:
    return "\n".join([
        "Web 可用命令",
        "/new 新会话",
        "/list 或 /sessions 查看会话",
        "/session-search <关键词> 搜索会话",
        "/session-load <id> 加载会话",
        "/undo [n] 撤回对话",
        "/retry 重试上一轮",
        "/model [key] 查看或切换模型",
        "/compress 手动压缩上下文",
        "/memory 查看记忆",
        "/memory-search <问题> 搜索向量记忆",
        "/memory-forget <ID> 删除指定向量记忆",
        "/memory-clear 清空向量记忆",
        "/task 查看任务计划",
        "/task-cancel 放弃当前任务",
        "/jobs 查看后台任务",
        "/cron 查看定时提示",
        "/cron-add <分钟> <提示> 创建定时提示",
        "/cron-remove [id] 删除定时提示",
        "/mcp 查看 MCP 状态",
        "/skills 查看技能",
        "/skills-reload 重新加载技能",
        "/skills-stats 查看技能统计",
        "/debug-context 查看上下文结构",
        "/audit 查看工具审计",
    ])


def _format_memory_status(status: dict[str, Any]) -> str:
    lines = ["记忆状态"]
    curated = str(status.get("curated") or "").strip()
    lines.append(curated or "暂无精选长期记忆。")
    providers = status.get("providers") if isinstance(status.get("providers"), list) else []
    if providers:
        lines.append("")
        lines.append("Provider")
        for provider in providers:
            name = provider.get("name", "unknown")
            if not provider.get("available", False):
                lines.append(f"- {name}: 不可用 · {provider.get('error', 'unknown error')}")
            elif name == "markdown":
                lines.append(f"- markdown: MEMORY {provider.get('memory_entries', 0)} 条 · USER {provider.get('user_entries', 0)} 条")
            elif name == "local_vector":
                lines.append(f"- local_vector: {provider.get('records', 0)} 条 · {provider.get('embedding_model', 'unknown')}")
            else:
                lines.append(f"- {name}: ready")
    return "\n".join(lines)


def _format_memory_search(results: list[dict[str, Any]]) -> str:
    if not results:
        return "没有找到相关向量记忆。"
    lines = [f"找到 {len(results)} 条相关记忆"]
    for result in results:
        content = " ".join(str(result.get("content", "")).split())
        if len(content) > 300:
            content = content[:300] + "..."
        score = float(result.get("score", 0) or 0)
        created_at = str(result.get("created_at", ""))[:19].replace("T", " ")
        lines.append(f"#{result.get('id', '?')} · {score:.2f} · {created_at or 'unknown'}\n  {content}")
    return "\n".join(lines)


def _format_sessions(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return "暂无历史会话。"
    lines = [f"历史会话 · {len(sessions)} 条"]
    for index, session in enumerate(sessions[:20], 1):
        title = str(session.get("title") or "(untitled)").strip()
        if len(title) > 60:
            title = title[:60] + "..."
        updated = session.get("updated_at", session.get("updated", session.get("created_at", session.get("created"))))
        lines.append(f"[{index}] {session.get('id', '')}\n  {title}\n  {_format_timestamp(updated)}")
    return "\n".join(lines)


def _search_sessions(agent: Any, query: str) -> list[dict[str, Any]]:
    search = getattr(agent, "search_conversations", None)
    if callable(search):
        result = _safe_call(agent, "search_conversations", query, default=[])
        if isinstance(result, list):
            return result
    query_lower = query.lower()
    sessions = _safe_call(agent, "list_conversations", default=[])
    if not isinstance(sessions, list):
        return []
    return [
        session for session in sessions
        if query_lower in str(session.get("title", "")).lower()
        or query_lower in str(session.get("id", "")).lower()
    ][:20]


def _format_session_search(results: list[dict[str, Any]]) -> str:
    if not results:
        return "没有找到相关历史会话。"
    lines = [f"会话搜索 · 找到 {len(results)} 条"]
    for result in results[:20]:
        session_id = result.get("session_id") or result.get("id") or ""
        title = str(result.get("title") or "(untitled)").strip()
        snippet = " ".join(str(result.get("snippet") or result.get("content") or "").split())
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        lines.append(f"{session_id}\n  {title}" + (f"\n  {snippet}" if snippet else ""))
    return "\n".join(lines)


def _format_audit(records: list[dict[str, Any]]) -> str:
    if not records:
        return "暂无工具审计记录。"
    lines = [f"最近工具审计 · {len(records)} 条"]
    for record in records[-20:]:
        tool = record.get("tool") or record.get("tool_name") or record.get("name") or "tool"
        state = "ok" if record.get("success") is True else "failed" if record.get("success") is False else record.get("risk", "event")
        lines.append(f"- {tool} · {state} · {record.get('timestamp', '')}")
    return "\n".join(lines)


def _format_task_status(task: dict[str, Any] | None) -> str:
    if not task:
        return "当前没有任务计划。"
    steps = task.get("steps") if isinstance(task.get("steps"), list) else []
    completed = sum(1 for step in steps if step.get("status") == "completed")
    lines = [
        f"任务: {task.get('objective', task.get('id', ''))}",
        f"状态: {task.get('status', 'unknown')} · {completed}/{len(steps)}",
    ]
    for step in steps:
        icon = {"completed": "✓", "in_progress": "›", "pending": "·"}.get(step.get("status"), "?")
        lines.append(f"{icon} {step.get('step', '')}")
    return "\n".join(lines)


def _format_jobs(status: dict[str, Any]) -> str:
    if not status.get("enabled", False):
        return "后台任务队列未启用。"
    return (
        f"后台任务 · pending {status.get('pending_count', 0)} · "
        f"running {status.get('running_count', 0)} · failed {status.get('failed_count', 0)}"
    )


def _format_cron_status(status: dict[str, Any]) -> str:
    if not status.get("enabled", True):
        return "定时提示未启用。"
    tasks = status.get("tasks") if isinstance(status.get("tasks"), list) else []
    if not tasks:
        return "暂无定时提示。用 /cron-add <分钟> <提示> 创建。"
    lines = [f"定时提示 · {len(tasks)} 个"]
    for task in tasks:
        lines.append(
            f"- {task.get('id', '')} · every {task.get('interval_minutes', '?')} min · "
            f"next {_format_timestamp(task.get('next_run_at'))}\n  {task.get('prompt', '')}"
        )
    return "\n".join(lines)


def _format_mcp(status: dict[str, Any]) -> str:
    servers = status.get("servers")
    if isinstance(servers, dict):
        servers = [{"name": name, **(value if isinstance(value, dict) else {})} for name, value in servers.items()]
    if not isinstance(servers, list) or not servers:
        return "暂无 MCP Server。"
    lines = [f"MCP Server · {len(servers)} 个"]
    for server in servers:
        lines.append(f"- {server.get('name') or server.get('id') or 'mcp'} · {server.get('type') or server.get('transport') or server.get('status') or 'configured'}")
    return "\n".join(lines)


def _format_skills(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return "暂无可用技能。"
    lines = [f"Skills · {len(skills)} 个"]
    for skill in skills[:40]:
        lines.append(f"- {skill.get('category', 'general')}/{skill.get('name', '')} · {skill.get('readiness_status', 'ready')}")
    return "\n".join(lines)


def _format_skill_usage_stats(stats: dict[str, Any]) -> str:
    if not stats.get("enabled", True) and not stats:
        return "Skill 使用追踪未启用。"
    lines = [
        f"Skill 使用统计 · {stats.get('total_turns', 0)} turns · {stats.get('total_events', 0)} events"
    ]
    for item in stats.get("skills", [])[:20]:
        lines.append(f"- {item.get('skill_name', '?')}: view {item.get('views', 0)} · failed {item.get('failures', 0)}")
    if len(lines) == 1:
        lines.append("暂无 Skill 调用记录。")
    return "\n".join(lines)


def _format_debug_context(status: dict[str, Any]) -> str:
    if not status.get("available", False):
        return "上下文调试信息不可用。"
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    blocks = summary.get("blocks") if isinstance(summary.get("blocks"), list) else []
    if not blocks:
        return "上下文调试信息已开启，但暂无分块明细。"
    lines = ["当前上下文结构"]
    for block in blocks:
        lines.append(f"- {block.get('name', 'block')}: {block.get('tokens', '?')} tokens")
    return "\n".join(lines)


def _format_models(models: list[dict[str, Any]]) -> str:
    if not models:
        return "没有配置模型。"
    lines = ["可用模型"]
    for model in models:
        marker = "●" if model.get("active") else "○"
        lines.append(f"{marker} {model.get('key')} · {model.get('name')}")
    return "\n".join(lines)


def _format_help() -> str:
    return "\n".join([
        "Web 可用命令",
        "/new 新会话",
        "/list 或 /sessions 查看会话",
        "/session-search <关键词> 搜索会话",
        "/session-load <id> 加载会话",
        "/undo [n] 撤回对话",
        "/retry 重试上一轮",
        "/model [key] 查看或切换模型",
        "/compress 手动压缩上下文",
        "/memory 查看记忆",
        "/memory-search <问题> 搜索向量记忆",
        "/memory-forget <ID> 删除指定向量记忆",
        "/memory-clear 清空向量记忆",
        "/task 查看任务计划",
        "/task-cancel 放弃当前任务",
        "/jobs 查看后台任务",
        "/cron 查看定时提示",
        "/cron-add <分钟> <提示> 创建定时提示",
        "/cron-remove [id] 删除定时提示",
        "/mcp 查看 MCP 状态",
        "/skills 查看技能",
        "/skills-reload 重新加载技能",
        "/skills-stats 查看技能统计",
        "/debug-context 查看上下文结构",
        "/audit 查看工具审计",
    ])


def _format_memory_status(status: dict[str, Any]) -> str:
    lines = ["记忆状态"]
    curated = str(status.get("curated") or "").strip()
    lines.append(curated or "暂无精选长期记忆。")
    providers = status.get("providers") if isinstance(status.get("providers"), list) else []
    if providers:
        lines.append("")
        lines.append("Provider")
        for provider in providers:
            name = provider.get("name", "unknown")
            if not provider.get("available", False):
                lines.append(f"- {name}: 不可用 · {provider.get('error', 'unknown error')}")
            elif name == "markdown":
                lines.append(f"- markdown: MEMORY {provider.get('memory_entries', 0)} 条 · USER {provider.get('user_entries', 0)} 条")
            elif name == "local_vector":
                lines.append(f"- local_vector: {provider.get('records', 0)} 条 · {provider.get('embedding_model', 'unknown')}")
            else:
                lines.append(f"- {name}: ready")
    return "\n".join(lines)


def _format_memory_search(results: list[dict[str, Any]]) -> str:
    if not results:
        return "没有找到相关向量记忆。"
    lines = [f"找到 {len(results)} 条相关记忆"]
    for result in results:
        content = " ".join(str(result.get("content", "")).split())
        if len(content) > 300:
            content = content[:300] + "..."
        score = float(result.get("score", 0) or 0)
        created_at = str(result.get("created_at", ""))[:19].replace("T", " ")
        lines.append(f"#{result.get('id', '?')} · {score:.2f} · {created_at or 'unknown'}\n  {content}")
    return "\n".join(lines)


def _format_sessions(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return "暂无历史会话。"
    lines = [f"历史会话 · {len(sessions)} 条"]
    for index, session in enumerate(sessions[:20], 1):
        title = str(session.get("title") or "(untitled)").strip()
        if len(title) > 60:
            title = title[:60] + "..."
        updated = session.get("updated_at", session.get("updated", session.get("created_at", session.get("created"))))
        lines.append(f"[{index}] {session.get('id', '')}\n  {title}\n  {_format_timestamp(updated)}")
    return "\n".join(lines)


def _format_session_search(results: list[dict[str, Any]]) -> str:
    if not results:
        return "没有找到相关历史会话。"
    lines = [f"会话搜索 · 找到 {len(results)} 条"]
    for result in results[:20]:
        session_id = result.get("session_id") or result.get("id") or ""
        title = str(result.get("title") or "(untitled)").strip()
        snippet = " ".join(str(result.get("snippet") or result.get("content") or "").split())
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        lines.append(f"{session_id}\n  {title}" + (f"\n  {snippet}" if snippet else ""))
    return "\n".join(lines)


def _format_audit(records: list[dict[str, Any]]) -> str:
    if not records:
        return "暂无工具审计记录。"
    lines = [f"最近工具审计 · {len(records)} 条"]
    for record in records[-20:]:
        tool = record.get("tool") or record.get("tool_name") or record.get("name") or "tool"
        state = "ok" if record.get("success") is True else "failed" if record.get("success") is False else record.get("risk", "event")
        lines.append(f"- {tool} · {state} · {record.get('timestamp', '')}")
    return "\n".join(lines)


def _format_task_status(task: dict[str, Any] | None) -> str:
    if not task:
        return "当前没有任务计划。"
    steps = task.get("steps") if isinstance(task.get("steps"), list) else []
    completed = sum(1 for step in steps if step.get("status") == "completed")
    lines = [
        f"任务: {task.get('objective', task.get('id', ''))}",
        f"状态: {task.get('status', 'unknown')} · {completed}/{len(steps)}",
    ]
    for step in steps:
        icon = {"completed": "✓", "in_progress": "•", "pending": "-"}.get(step.get("status"), "?")
        lines.append(f"{icon} {step.get('step', '')}")
    return "\n".join(lines)


def _format_jobs(status: dict[str, Any]) -> str:
    if not status.get("enabled", False):
        return "后台任务队列未启用。"
    return (
        f"后台任务 · pending {status.get('pending_count', 0)} · "
        f"running {status.get('running_count', 0)} · failed {status.get('failed_count', 0)}"
    )


def _format_cron_status(status: dict[str, Any]) -> str:
    if not status.get("enabled", True):
        return "定时提示未启用。"
    tasks = status.get("tasks") if isinstance(status.get("tasks"), list) else []
    if not tasks:
        return "暂无定时提示。用 /cron-add <分钟> <提示> 创建。"
    lines = [f"定时提示 · {len(tasks)} 个"]
    for task in tasks:
        lines.append(
            f"- {task.get('id', '')} · every {task.get('interval_minutes', '?')} min · "
            f"next {_format_timestamp(task.get('next_run_at'))}\n  {task.get('prompt', '')}"
        )
    return "\n".join(lines)


def _format_mcp(status: dict[str, Any]) -> str:
    servers = status.get("servers")
    if isinstance(servers, dict):
        servers = [{"name": name, **(value if isinstance(value, dict) else {})} for name, value in servers.items()]
    if not isinstance(servers, list) or not servers:
        return "暂无 MCP Server。"
    lines = [f"MCP Server · {len(servers)} 个"]
    for server in servers:
        lines.append(f"- {server.get('name') or server.get('id') or 'mcp'} · {server.get('status') or 'configured'} · {server.get('transport') or server.get('type') or 'unknown'}")
    return "\n".join(lines)


def _format_skills(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return "暂无可用技能。"
    lines = [f"Skills · {len(skills)} 个"]
    for skill in skills[:40]:
        lines.append(f"- {skill.get('category', 'general')}/{skill.get('name', '')} · {skill.get('readiness_status', 'ready')}")
    return "\n".join(lines)


def _format_skill_usage_stats(stats: dict[str, Any]) -> str:
    if not stats.get("enabled", True) and not stats:
        return "Skill 使用追踪未启用。"
    lines = [f"Skill 使用统计 · {stats.get('total_turns', 0)} turns · {stats.get('total_events', 0)} events"]
    for item in stats.get("skills", [])[:20]:
        lines.append(f"- {item.get('skill_name', '?')}: view {item.get('views', 0)} · failed {item.get('failures', 0)}")
    if len(lines) == 1:
        lines.append("暂无 Skill 调用记录。")
    return "\n".join(lines)


def _format_debug_context(status: dict[str, Any]) -> str:
    if not status.get("available", False):
        return "上下文调试信息不可用。"
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    blocks = summary.get("blocks") if isinstance(summary.get("blocks"), list) else []
    if not blocks:
        return "上下文调试信息已开启，但暂无分块明细。"
    lines = ["当前上下文结构"]
    for block in blocks:
        lines.append(f"- {block.get('name', 'block')}: {block.get('tokens', '?')} tokens")
    return "\n".join(lines)


def _format_models(models: list[dict[str, Any]]) -> str:
    if not models:
        return "没有配置模型。"
    lines = ["可用模型"]
    for model in models:
        marker = "●" if model.get("active") else "○"
        lines.append(f"{marker} {model.get('key')} · {model.get('name')}")
    return "\n".join(lines)


def _format_timestamp(value: Any) -> str:
    if not value:
        return "unknown time"
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            return "unknown time"
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:19].replace("T", " ")


def build_dashboard_payload(
    agent: Any,
    *,
    config: dict[str, Any] | None = None,
    sierra_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    config = config if isinstance(config, dict) else {}
    root_dir = Path(sierra_dir or getattr(agent, "sierra_dir", ".")).resolve()

    usage = _safe_call(agent, "refresh_context_estimate", default=None)
    if isinstance(usage, Exception):
        usage = None
    usage_snapshot = _safe_call(agent, "usage_snapshot", default={})
    if not isinstance(usage_snapshot, dict):
        usage_snapshot = {}

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "identity": _identity(agent, config),
        "usage": _usage(usage_snapshot),
        "conversation": _conversation(agent),
        "tools": _tools(agent),
        "memory": _memory(agent),
        "mcp": _mcp(agent),
        "tasks": _tasks(agent),
        "background": _background(agent),
        "cron": _cron(agent),
        "skills": _skills(agent),
        "context": _context(agent),
        "audit": _audit(agent),
        "sierra_frame": _sierra_frame(root_dir),
    }


def _identity(agent: Any, config: dict[str, Any]) -> dict[str, Any]:
    models = []
    active_key = str(config.get("active_model") or "")
    for key, value in (config.get("models") or {}).items():
        if not isinstance(value, dict):
            continue
        models.append({
            "key": key,
            "name": value.get("name", key),
            "active": key == active_key,
        })
    return {
        "name": "Sierra AI Agent",
        "model": getattr(agent, "model", ""),
        "active_model": active_key,
        "models": models,
        "workspace": getattr(agent, "workspace", ""),
        "sierra_dir": getattr(agent, "sierra_dir", ""),
    }


def _usage(snapshot: dict[str, Any]) -> dict[str, Any]:
    context = _int(snapshot.get("context"), 0)
    window = _int(
        snapshot.get("context_budget")
        or snapshot.get("context_window")
        or snapshot.get("model_context_window"),
        1,
    )
    pct = 0 if window <= 0 else min(100, round(context / window * 100, 1))
    return {
        "input": _int(snapshot.get("input"), 0),
        "output": _int(snapshot.get("output"), 0),
        "context": context,
        "context_window": window,
        "model_context_window": _int(snapshot.get("model_context_window"), window),
        "percent": pct,
        "estimated": bool(snapshot.get("context_estimated")),
        "compression_count": _int(snapshot.get("compression_count"), 0),
    }


def _conversation(agent: Any) -> dict[str, Any]:
    messages = getattr(agent, "messages", []) or []
    role_counts: dict[str, int] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1

    conversations = _safe_call(agent, "list_conversations", default=[])
    if not isinstance(conversations, list):
        conversations = []
    return {
        "id": getattr(agent, "conv_id", None),
        "message_count": len(messages),
        "role_counts": role_counts,
        "recent": conversations[:8],
    }


def _tools(agent: Any) -> dict[str, Any]:
    registry = getattr(agent, "tools", None)
    names = []
    entries = []
    direct_names = []
    deferred_names = []
    toolsets: dict[str, int] = {}
    active_bridge = False

    if registry is not None:
        try:
            names = list(registry.names())
        except Exception:
            names = []
        try:
            definitions = registry.get_definitions()
            direct_names = [
                item.get("function", {}).get("name", "")
                for item in definitions
                if isinstance(item, dict)
            ]
            active_bridge = any(name in BRIDGE_TOOL_NAMES for name in direct_names)
        except Exception:
            direct_names = []

        for name in names:
            try:
                entry = registry.get_entry(name)
            except Exception:
                entry = None
            toolset = str(getattr(entry, "toolset", "core") or "core")
            toolsets[toolset] = toolsets.get(toolset, 0) + 1
            item = {
                "name": name,
                "toolset": toolset,
                "emoji": getattr(entry, "emoji", "") if entry else "",
            }
            entries.append(item)
            if active_bridge and name not in direct_names and name not in BRIDGE_TOOL_NAMES:
                deferred_names.append(name)

    return {
        "total": len(names),
        "direct": len([name for name in direct_names if name]),
        "deferred": len(deferred_names),
        "tool_search_active": active_bridge,
        "toolsets": toolsets,
        "items": entries[:80],
    }


def _memory(agent: Any) -> dict[str, Any]:
    status = _safe_call(agent, "memory_status", default={})
    if not isinstance(status, dict):
        return {"curated": "", "providers": []}
    curated = sanitize_text(str(status.get("curated") or ""), max_length=2400)
    providers = status.get("providers")
    return {
        "curated": curated,
        "providers": providers if isinstance(providers, list) else [],
    }


def _mcp(agent: Any) -> dict[str, Any]:
    status = _safe_call(agent, "mcp_status", default={})
    return status if isinstance(status, dict) else {}


def _tasks(agent: Any) -> dict[str, Any]:
    current = _safe_call(agent, "task_status", default=None)
    recovery = _safe_call(agent, "task_recovery", default=None)
    return {
        "current": current if isinstance(current, dict) else None,
        "recovery": recovery if isinstance(recovery, dict) else None,
    }


def _background(agent: Any) -> dict[str, Any]:
    status = _safe_call(agent, "background_jobs_status", 12, default={})
    return status if isinstance(status, dict) else {}


def _cron(agent: Any) -> dict[str, Any]:
    status = _safe_call(agent, "cron_status", default={})
    return status if isinstance(status, dict) else {"enabled": False, "tasks": []}


def _skills(agent: Any) -> dict[str, Any]:
    summaries = _safe_call(agent, "skill_summaries", default=[], include_unavailable=True)
    if not isinstance(summaries, list):
        summaries = []
    items = []
    for summary in summaries[:24]:
        if not isinstance(summary, dict):
            continue
        items.append({
            "name": summary.get("name", ""),
            "category": summary.get("category", ""),
            "readiness_status": summary.get("readiness_status", ""),
            "offered": summary.get("offered", False),
        })
    stats = _safe_call(agent, "skill_usage_stats", 8, default={})
    errors = getattr(getattr(agent, "skill_loader", None), "errors", [])
    return {
        "count": len(summaries),
        "items": items,
        "errors": list(errors or []),
        "stats": stats if isinstance(stats, dict) else {},
    }


def _context(agent: Any) -> dict[str, Any]:
    status = _safe_call(agent, "debug_context_status", default={})
    if not isinstance(status, dict):
        return {"available": False, "summary": {}}
    text = status.get("text")
    if text:
        status = {**status, "text": sanitize_text(str(text), max_length=3000)}
    return status


def _audit(agent: Any) -> dict[str, Any]:
    records = _safe_call(agent, "audit_recent", 12, default=[])
    if not isinstance(records, list):
        records = []
    safe_records = []
    for record in records[-12:]:
        if not isinstance(record, dict):
            continue
        safe_record = {}
        for key, value in record.items():
            if key in {"arguments", "result"}:
                safe_record[key] = sanitize_text(str(value), max_length=280)
            elif isinstance(value, str):
                safe_record[key] = sanitize_text(value, max_length=280)
            else:
                safe_record[key] = value
        safe_records.append(safe_record)
    safe_records.reverse()
    return {"records": safe_records}


def _web_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []
    result = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text") or item)
                for item in content
                if isinstance(item, (str, dict))
            )
        else:
            text = str(content or "")
        text = sanitize_text(text, max_length=12000).strip()
        if text:
            result.append({"role": role, "text": text})
    return result[-80:]


def _sierra_frame(root_dir: Path) -> dict[str, Any] | None:
    frame_path = root_dir / "tui" / "assets" / "sierra" / "thinking-terminal-frames.json"
    if not frame_path.exists():
        return None
    try:
        import json

        data = json.loads(frame_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    frames = data.get("frames") if isinstance(data, dict) else None
    if not isinstance(frames, list) or not frames:
        return None
    selected = None
    for frame in frames:
        if isinstance(frame, dict) and frame.get("name") == "think-idle":
            selected = frame
            break
    if selected is None:
        selected = next((frame for frame in frames if isinstance(frame, dict)), None)
    if not isinstance(selected, dict):
        return None
    return {
        "name": selected.get("name", "sierra"),
        "width": selected.get("width", 0),
        "height": selected.get("height", 0),
        "lines": selected.get("lines", []),
    }


_CONTEXT_STATIC_SUGGESTIONS = [
    {
        "kind": "diff",
        "label": "@diff",
        "detail": "附加当前未暂存的 Git diff",
        "value": "@diff ",
    },
    {
        "kind": "staged",
        "label": "@staged",
        "detail": "附加已暂存的 Git diff",
        "value": "@staged ",
    },
    {
        "kind": "url",
        "label": "@url:",
        "detail": "附加网页正文，继续输入完整链接",
        "value": "@url:",
    },
]


_CONTEXT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".playwright-mcp",
    "dist",
    "build",
    "coverage",
}


def _context_reference_suggestions(workspace: Path, query: str, limit: int) -> list[dict[str, str]]:
    normalized = query.strip().lstrip("@").replace("\\", "/")
    kind_filter = ""
    path_query = normalized
    if normalized.startswith("file:"):
        kind_filter = "file"
        path_query = normalized.removeprefix("file:")
    elif normalized.startswith("folder:"):
        kind_filter = "folder"
        path_query = normalized.removeprefix("folder:")
    elif normalized.startswith("url:"):
        kind_filter = "url"
        path_query = normalized.removeprefix("url:")

    items: list[dict[str, str]] = []
    static_items = [
        item for item in _CONTEXT_STATIC_SUGGESTIONS
        if not kind_filter or item["kind"] == kind_filter
    ]
    for item in static_items:
        haystack = f"{item['label']} {item['detail']}".lower()
        if not normalized or normalized.lower() in haystack or item["kind"] == kind_filter:
            items.append(dict(item))

    if kind_filter == "url":
        return items[:limit]
    if not workspace.exists() or not workspace.is_dir():
        return items[:limit]

    path_query_lower = path_query.strip("`'\"").lower()
    max_scan = max(160, limit * 18)
    scanned = 0
    candidates: list[dict[str, str]] = []

    for root, dirs, files in os.walk(workspace):
        root_path = Path(root)
        rel_root = _safe_relative_path(root_path, workspace)
        depth = 0 if not rel_root else len(Path(rel_root).parts)
        dirs[:] = [
            dirname for dirname in dirs
            if not _should_skip_context_path(dirname) and depth < 5
        ]

        for dirname in dirs:
            rel_path = _safe_relative_path(root_path / dirname, workspace)
            if not rel_path:
                continue
            scanned += 1
            if not kind_filter or kind_filter == "folder":
                candidates.append(_context_path_item("folder", rel_path))
            if scanned >= max_scan:
                break
        if scanned >= max_scan:
            break

        for filename in files:
            if _should_skip_context_path(filename):
                continue
            rel_path = _safe_relative_path(root_path / filename, workspace)
            if not rel_path:
                continue
            scanned += 1
            if not kind_filter or kind_filter == "file":
                candidates.append(_context_path_item("file", rel_path))
            if scanned >= max_scan:
                break
        if scanned >= max_scan:
            break

    for item in sorted(candidates, key=lambda value: _context_sort_key(value, path_query_lower)):
        haystack = f"{item['label']} {item['detail']}".lower()
        if path_query_lower and path_query_lower not in haystack:
            continue
        items.append(item)
        if len(items) >= limit:
            break

    return items[:limit]


def _safe_upload_filename(filename: str) -> str:
    name = Path(str(filename or "upload")).name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "upload"
    if len(name) > 180:
        stem = Path(name).stem[:140].strip(" .") or "upload"
        suffix = Path(name).suffix[:20]
        name = f"{stem}{suffix}"
    return name


def _unique_upload_path(directory: Path, filename: str) -> Path:
    target = (directory / filename).resolve()
    if not target.exists():
        return target
    stem = target.stem or "upload"
    suffix = target.suffix
    for index in range(1, 1000):
        candidate = (directory / f"{stem}-{index}{suffix}").resolve()
        if not candidate.exists():
            return candidate
    return (directory / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}").resolve()


def _context_path_item(kind: str, rel_path: str) -> dict[str, str]:
    label = f"{rel_path}/" if kind == "folder" and not rel_path.endswith("/") else rel_path
    prefix = "@folder:" if kind == "folder" else "@file:"
    return {
        "kind": kind,
        "label": label,
        "detail": f"{kind} · {rel_path}",
        "value": f"{prefix}{_quote_reference_value(rel_path)} ",
    }


def _quote_reference_value(value: str) -> str:
    cleaned = value.replace("\\", "/").strip()
    if not cleaned:
        return "``"
    escaped = cleaned.replace("`", "\\`")
    return f"`{escaped}`"


def _context_sort_key(item: dict[str, str], query: str) -> tuple[int, int, str]:
    label = item.get("label", "").lower()
    if not query:
        rank = 0
    elif label == query:
        rank = 0
    elif label.startswith(query):
        rank = 1
    elif f"/{query}" in label:
        rank = 2
    else:
        rank = 3
    return rank, label.count("/"), label


def _safe_relative_path(path: Path, parent: Path) -> str:
    try:
        return path.resolve().relative_to(parent.resolve()).as_posix()
    except ValueError:
        return ""


def _should_skip_context_path(name: str) -> bool:
    if not name:
        return True
    lower = name.lower()
    if lower in _CONTEXT_SKIP_DIRS:
        return True
    if lower.startswith(".") and lower not in {".env.example", ".editorconfig", ".gitattributes", ".gitignore"}:
        return True
    if lower.endswith((".pyc", ".pyo", ".log", ".tmp", ".cache", ".sqlite", ".db")):
        return True
    return False


def _safe_call(obj: Any, method: str, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    fn = getattr(obj, method, None)
    if not callable(fn):
        return default
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"error": sanitize_text(str(exc), max_length=300)}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False
