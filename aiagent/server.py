"""JSON-line stdin/stdout server for the TUI frontend."""
import io
import json
import os
import sys
import time
import uuid
from typing import Callable

from .encoding import ensure_utf8_stdio

ensure_utf8_stdio()

from .agent import Agent
from .config_validation import (
    StartupConfigError,
    format_config_issues,
    validate_model_config,
)
from .safety import sanitize_arguments


def run_server(
    agent: Agent,
    config: dict | None = None,
    config_path: str | None = None,
    make_agent: Callable[[str], Agent] | None = None,
):
    current_agent = agent

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        cmd = msg.get("cmd", "chat")

        if cmd == "init":
            convs = current_agent.list_conversations()
            recent = None
            if convs:
                recent = {"id": convs[0]["id"], "title": convs[0]["title"]}
            companion_handoff = ""
            handoff = getattr(current_agent, "companion_handoff", None)
            if callable(handoff):
                companion_handoff = handoff()
            stdout(json.dumps({
                "type": "init",
                "model": current_agent.llm.model,
                "cwd": os.getcwd(),
                "recent": recent,
                "companion_hint": companion_handoff,
                "usage": _usage_payload(current_agent),
                "task": _agent_task_status(current_agent),
                "recovery_task": _agent_task_recovery(current_agent),
            }, ensure_ascii=False))

        elif cmd == "chat":
            user_msg = msg.get("text", "")
            if not user_msg:
                continue
            try:
                real_stdout = sys.stdout
                sys.stdout = io.StringIO()

                def on_status(event):
                    sys.__stdout__.write(json.dumps(event, ensure_ascii=False) + "\n")
                    sys.__stdout__.flush()

                def on_tool_approval(request):
                    approval_id = f"tool-{uuid.uuid4().hex[:12]}"
                    on_status({
                        "type": "tool_approval_request",
                        "id": approval_id,
                        "name": request.get("name", "tool"),
                        "risk": request.get("risk", "medium"),
                        "reason": request.get("reason", ""),
                        "arguments": request.get("arguments", "{}"),
                    })

                    while True:
                        approval_line = sys.stdin.readline()
                        if not approval_line:
                            on_status({
                                "type": "tool_approval_result",
                                "id": approval_id,
                                "name": request.get("name", "tool"),
                                "decision": "deny",
                                "approved": False,
                            })
                            return "deny"

                        try:
                            approval_msg = json.loads(approval_line)
                        except json.JSONDecodeError:
                            continue

                        cmd = approval_msg.get("cmd")
                        if cmd == "tool_approval" and approval_msg.get("id") == approval_id:
                            decision = approval_msg.get("decision")
                            if decision not in ("once", "session", "deny"):
                                approved = bool(approval_msg.get("approved"))
                                decision = "once" if approved else "deny"
                            on_status({
                                "type": "tool_approval_result",
                                "id": approval_id,
                                "name": request.get("name", "tool"),
                                "decision": decision,
                                "approved": decision in ("once", "session"),
                            })
                            return decision

                        if cmd == "quit":
                            _auto_save(current_agent)
                            current_agent.close()
                            stdout(json.dumps({"type": "bye"}))
                            raise SystemExit(0)

                def on_user_input(request):
                    request_id = f"input-{uuid.uuid4().hex[:12]}"
                    on_status({
                        "type": "user_input_request",
                        "id": request_id,
                        "question": request.get("question", "请补充你的需求"),
                        "options": request.get("options", []),
                        "allow_free_text": request.get("allow_free_text", True),
                    })

                    while True:
                        response_line = sys.stdin.readline()
                        if not response_line:
                            response = {"cancelled": True}
                            on_status({
                                "type": "user_input_result",
                                "id": request_id,
                                **response,
                            })
                            return response

                        try:
                            response_msg = json.loads(response_line)
                        except json.JSONDecodeError:
                            continue

                        cmd = response_msg.get("cmd")
                        if cmd == "user_input_response" and response_msg.get("id") == request_id:
                            response = {
                                "value": str(response_msg.get("value", "")),
                                "label": str(response_msg.get("label", "")),
                                "free_text": bool(response_msg.get("free_text")),
                                "cancelled": bool(response_msg.get("cancelled")),
                            }
                            on_status({
                                "type": "user_input_result",
                                "id": request_id,
                                **response,
                            })
                            return response

                        if cmd == "quit":
                            _auto_save(current_agent)
                            current_agent.close()
                            stdout(json.dumps({"type": "bye"}))
                            raise SystemExit(0)

                response = current_agent.chat(
                    user_msg,
                    on_status=on_status,
                    on_tool_approval=on_tool_approval,
                    on_user_input=on_user_input,
                )
                sys.stdout = real_stdout
                stdout(json.dumps({
                    "type": "done",
                    "text": response or "",
                    "usage": _usage_payload(current_agent),
                    "task": _agent_task_status(current_agent),
                }, ensure_ascii=False))
                _auto_save(current_agent)
            except Exception as e:
                sys.stdout = sys.__stdout__
                stdout(json.dumps({"type": "error", "text": str(e)}, ensure_ascii=False))

        elif cmd == "list":
            stdout(json.dumps({
                "type": "convs",
                "convs": current_agent.list_conversations(),
            }, ensure_ascii=False))

        elif cmd == "sessions":
            try:
                limit = max(1, min(50, int(msg.get("limit", 20) or 20)))
            except (TypeError, ValueError):
                limit = 20
            sessions = current_agent.list_sessions(limit=limit)
            stdout(json.dumps({
                "type": "sessions",
                "sessions": sessions,
                "text": _format_sessions(sessions),
            }, ensure_ascii=False))

        elif cmd == "session_search":
            query = str(msg.get("query", "")).strip()
            if not query:
                stdout(json.dumps({
                    "type": "session_search",
                    "text": "用法: /session-search <关键词>",
                }, ensure_ascii=False))
                continue
            try:
                limit = max(1, min(20, int(msg.get("limit", 10) or 10)))
            except (TypeError, ValueError):
                limit = 10
            results = current_agent.search_sessions(query, limit=limit)
            stdout(json.dumps({
                "type": "session_search",
                "results": results,
                "text": _format_session_search(results),
            }, ensure_ascii=False))

        elif cmd == "session_load":
            session_id = str(msg.get("id") or "").strip()
            if not session_id:
                stdout(json.dumps({
                    "type": "session_loaded",
                    "success": False,
                    "text": "用法: /session-load <session_id>",
                }, ensure_ascii=False))
                continue
            _auto_save(current_agent)
            result = current_agent.load_session(session_id)
            stdout(json.dumps({
                "type": "session_loaded",
                "success": bool(result.get("ok")),
                "title": (result.get("session") or {}).get("title", ""),
                "usage": _usage_payload(current_agent),
                "task": _agent_task_status(current_agent),
                "text": (
                    f"已加载会话 {session_id}"
                    if result.get("ok")
                    else result.get("error", "加载会话失败")
                ),
            }, ensure_ascii=False))

        elif cmd == "resume":
            sid = msg.get("id", "")
            if sid:
                current_agent.load_conversation(sid)
                title = ""
                for m in current_agent.messages:
                    if m["role"] == "user":
                        title = m["content"][:30]
                companion_handoff = ""
                handoff = getattr(current_agent, "companion_handoff", None)
                if callable(handoff):
                    companion_handoff = handoff()
                stdout(json.dumps({
                    "type": "resumed",
                    "title": title,
                    "companion_hint": companion_handoff,
                    "usage": _usage_payload(current_agent),
                    "task": _agent_task_status(current_agent),
                    "recovery_task": _agent_task_recovery(current_agent),
                }, ensure_ascii=False))

        elif cmd == "new":
            _auto_save(current_agent)
            current_agent.reset()
            current_agent.conv_id = None
            stdout(json.dumps({
                "type": "ok",
                "usage": _usage_payload(current_agent),
                "task": None,
            }, ensure_ascii=False))

        elif cmd == "compress":
            old = len(current_agent.messages)
            result = current_agent.compress_messages(force=True)
            if result.get("compressed"):
                text = (
                    f"压缩完成: {old} → {len(current_agent.messages)} 条，"
                    f"约 {result['before_tokens']} → {result['after_tokens']} tokens"
                )
            else:
                text = "当前没有可安全压缩的完整历史轮次，消息未改变。"
            stdout(json.dumps({
                "type": "ok",
                "text": text,
                "usage": _usage_payload(current_agent),
            }, ensure_ascii=False))

        elif cmd == "memory":
            status = current_agent.memory_status()
            stdout(json.dumps({
                "type": "memory",
                "text": _format_memory_status(status),
            }, ensure_ascii=False))

        elif cmd == "companion":
            status = current_agent.companion_status()
            stdout(json.dumps({
                "type": "companion",
                "text": status.get("text", "暂无陪伴状态。"),
            }, ensure_ascii=False))

        elif cmd == "debug_context":
            status = current_agent.debug_context_status()
            stdout(json.dumps({
                "type": "debug_context",
                "summary": status.get("summary", {}),
                "text": status.get("text", ""),
                "available": bool(status.get("available")),
            }, ensure_ascii=False))

        elif cmd == "jobs":
            status_fn = getattr(current_agent, "background_jobs_status", None)
            status = (
                status_fn(limit=20)
                if callable(status_fn)
                else {"enabled": False, "jobs": [], "text": "Background jobs are not available."}
            )
            stdout(json.dumps({
                "type": "jobs",
                "jobs": status.get("jobs", []),
                "text": status.get("text", ""),
                "enabled": bool(status.get("enabled")),
            }, ensure_ascii=False))

        elif cmd == "memory_search":
            query = str(msg.get("query", "")).strip()
            if not query:
                stdout(json.dumps({
                    "type": "memory_search",
                    "text": "用法: /memory-search <问题>",
                }, ensure_ascii=False))
                continue
            try:
                limit = max(1, min(10, int(msg.get("limit", 5) or 5)))
            except (TypeError, ValueError):
                limit = 5
            results = current_agent.memory_search(query, limit=limit)
            stdout(json.dumps({
                "type": "memory_search",
                "text": _format_memory_search(results),
            }, ensure_ascii=False))

        elif cmd in ("memory_forget", "memory_clear"):
            tool_name = cmd
            arguments = {}
            if cmd == "memory_forget":
                try:
                    memory_id = int(msg.get("id"))
                    if memory_id <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    stdout(json.dumps({
                        "type": "memory_action",
                        "text": "记忆 ID 必须是正整数。用法: /memory-forget <ID>",
                        "success": False,
                    }, ensure_ascii=False))
                    continue
                arguments = {"id": memory_id}
                reason = f"删除当前工作区的向量记忆 #{memory_id}"
            else:
                memory_status = current_agent.memory_status()
                vector_status = next(
                    (
                        provider for provider in memory_status.get("providers", [])
                        if provider.get("name") == "local_vector"
                    ),
                    None,
                )
                if vector_status is not None and int(vector_status.get("records", 0) or 0) == 0:
                    stdout(json.dumps({
                        "type": "memory_action",
                        "text": "当前工作区没有向量记忆，无需清空。",
                        "success": True,
                    }, ensure_ascii=False))
                    continue
                clear_count = int((vector_status or {}).get("records", 0) or 0)
                arguments = {"records": clear_count}
                reason = f"清空当前工作区的全部向量记忆（{clear_count} 条）"

            approval = _request_command_approval(
                current_agent,
                tool_name,
                arguments,
                reason,
            )
            if not approval["approved"]:
                _audit_memory_command(
                    current_agent,
                    tool_name,
                    arguments,
                    approval,
                    success=False,
                    executed=False,
                    error="用户或权限策略拒绝操作",
                )
                stdout(json.dumps({
                    "type": "memory_action",
                    "text": "已取消记忆删除操作。",
                    "success": False,
                }, ensure_ascii=False))
                continue

            started = time.perf_counter()
            result = (
                current_agent.memory_forget(arguments["id"])
                if cmd == "memory_forget"
                else current_agent.memory_clear()
            )
            duration_ms = round((time.perf_counter() - started) * 1000)
            success = bool(result.get("ok"))
            _audit_memory_command(
                current_agent,
                tool_name,
                arguments,
                approval,
                success=success,
                executed=True,
                duration_ms=duration_ms,
                error=result.get("error", ""),
            )
            if cmd == "memory_forget":
                text = (
                    f"已删除向量记忆 #{arguments['id']}。"
                    if success
                    else result.get("error", "删除失败")
                )
            else:
                text = (
                    f"已清空当前工作区的 {result.get('deleted', 0)} 条向量记忆。"
                    if success
                    else result.get("error", "清空失败")
                )
            stdout(json.dumps({
                "type": "memory_action",
                "text": text,
                "success": success,
            }, ensure_ascii=False))

        elif cmd == "audit":
            stdout(json.dumps({
                "type": "audit",
                "records": current_agent.audit_recent(20),
            }, ensure_ascii=False))

        elif cmd == "task":
            task = current_agent.task_status()
            stdout(json.dumps({
                "type": "task_status",
                "task": task,
                "text": _format_task_status(task),
            }, ensure_ascii=False))

        elif cmd == "task_resume":
            task_id = str(msg.get("id") or "")
            recoverable = current_agent.task_recovery(task_id)
            if recoverable and recoverable.get("conversation_id"):
                conversation_id = recoverable["conversation_id"]
                if conversation_id != current_agent.conv_id:
                    _auto_save(current_agent)
                    current_agent.load_conversation(conversation_id)
            result = current_agent.resume_task(task_id)
            stdout(json.dumps({
                "type": "task_recovery_result",
                "action": "resume",
                "success": bool(result.get("ok")),
                "task": result.get("task"),
                "text": (
                    "已恢复未完成任务。"
                    if result.get("ok")
                    else result.get("error", "恢复任务失败")
                ),
            }, ensure_ascii=False))

        elif cmd == "task_abandon":
            task_id = str(msg.get("id") or "")
            result = current_agent.abandon_task(task_id)
            stdout(json.dumps({
                "type": "task_recovery_result",
                "action": "abandon",
                "success": bool(result.get("ok")),
                "task": None,
                "text": (
                    "已放弃未完成任务。"
                    if result.get("ok")
                    else result.get("error", "放弃任务失败")
                ),
            }, ensure_ascii=False))

        elif cmd == "skills":
            stdout(json.dumps({
                "type": "skills",
                "skills": current_agent.skill_summaries(include_unavailable=True),
                "errors": list(current_agent.skill_loader.errors),
            }, ensure_ascii=False))

        elif cmd == "skills_reload":
            result = current_agent.reload_skills()
            stdout(json.dumps({
                "type": "skills",
                "skills": result["skills"],
                "errors": result["errors"],
                "reloaded": True,
            }, ensure_ascii=False))

        elif cmd == "skills_stats":
            stats = current_agent.skill_usage_stats(limit=20)
            stdout(json.dumps({
                "type": "skills_stats",
                "text": _format_skill_usage_stats(stats),
                "stats": stats,
            }, ensure_ascii=False))

        elif cmd == "mcp":
            stdout(json.dumps({
                "type": "mcp",
                "status": current_agent.mcp_status(),
            }, ensure_ascii=False))

        elif cmd == "models":
            if not config:
                stdout(json.dumps({"type": "error", "text": "No model config loaded"}))
                continue

            active = config.get("active_model", "")
            models = [
                {
                    "key": key,
                    "name": value.get("name", key),
                    "active": key == active,
                }
                for key, value in config.get("models", {}).items()
            ]
            stdout(json.dumps({
                "type": "models",
                "models": models,
                "active": active,
            }, ensure_ascii=False))

        elif cmd == "set_model":
            if not config or not make_agent:
                stdout(json.dumps({"type": "error", "text": "No model config loaded"}))
                continue

            model_key = msg.get("key", "")
            if model_key not in config.get("models", {}):
                stdout(json.dumps({
                    "type": "error",
                    "text": f"Unknown model: {model_key}",
                }, ensure_ascii=False))
                continue
            try:
                validate_model_config(config, model_key)
            except StartupConfigError as exc:
                stdout(json.dumps({
                    "type": "error",
                    "text": format_config_issues(exc.issues),
                }, ensure_ascii=False))
                continue

            _auto_save(current_agent)
            previous_messages = list(current_agent.messages)
            previous_conv_id = current_agent.conv_id
            previous_input_tokens = current_agent.total_input_tokens
            previous_output_tokens = current_agent.total_output_tokens
            previous_session_allows = set(
                current_agent.permission_policy.session_allow_tools
            )
            previous_task = _agent_task_status(current_agent)
            config["active_model"] = model_key
            if config_path:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                    f.write("\n")

            current_agent.close(preserve_task=True)
            current_agent = make_agent(model_key)
            current_agent.messages = previous_messages
            current_agent.sync_memory_review_state()
            current_agent.refresh_context_estimate()
            current_agent.conv_id = previous_conv_id
            current_agent.total_input_tokens = previous_input_tokens
            current_agent.total_output_tokens = previous_output_tokens
            current_agent.permission_policy.session_allow_tools.update(
                previous_session_allows
            )
            if previous_task and previous_task.get("status") == "active":
                current_agent.resume_task(previous_task["id"])
            stdout(json.dumps({
                "type": "model_changed",
                "key": model_key,
                "model": current_agent.llm.model,
                "usage": _usage_payload(current_agent),
                "task": _agent_task_status(current_agent),
            }, ensure_ascii=False))

        elif cmd == "quit":
            _auto_save(current_agent)
            current_agent.close()
            stdout(json.dumps({"type": "bye"}))
            break

    try:
        current_agent.close()
    except Exception:
        pass


def stdout(s: str):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def _auto_save(agent: Agent):
    if not agent.messages:
        return

    title = ""
    for m in agent.messages:
        if m["role"] == "user":
            title = m["content"][:30]

    usage_snapshot = getattr(agent, "usage_snapshot", None)
    usage = usage_snapshot() if callable(usage_snapshot) else {
        "input": agent.total_input_tokens,
        "output": agent.total_output_tokens,
    }
    agent.save_conversation(usage=usage, title=title)


def _usage_payload(agent: Agent) -> dict:
    usage_snapshot = getattr(agent, "usage_snapshot", None)
    if callable(usage_snapshot):
        return usage_snapshot()
    return {
        "input": getattr(agent, "total_input_tokens", 0),
        "output": getattr(agent, "total_output_tokens", 0),
        "context": getattr(agent, "current_context_tokens", 0),
        "context_window": getattr(agent, "context_window", 0),
        "context_estimated": getattr(agent, "context_tokens_estimated", False),
    }


def _agent_task_status(agent: Agent) -> dict | None:
    task_status = getattr(agent, "task_status", None)
    return task_status() if callable(task_status) else None


def _agent_task_recovery(agent: Agent, task_id: str | None = None) -> dict | None:
    task_recovery = getattr(agent, "task_recovery", None)
    return task_recovery(task_id) if callable(task_recovery) else None


def _format_memory_status(status: dict) -> str:
    lines = []
    curated = str(status.get("curated") or "").strip()
    lines.append("精选记忆")
    lines.append(curated or "（暂无）")
    lines.append("")
    lines.append("记忆 Provider")
    for provider in status.get("providers", []):
        name = provider.get("name", "unknown")
        if not provider.get("available", False):
            lines.append(f"- {name}: 不可用 · {provider.get('error', 'unknown error')}")
        elif name == "markdown":
            lines.append(
                f"- markdown: 项目 {provider.get('memory_entries', 0)} 条 · "
                f"用户 {provider.get('user_entries', 0)} 条"
            )
        elif name == "local_vector":
            lines.append(
                f"- local_vector: 当前工作区 {provider.get('records', 0)} 条 · "
                f"模型 {provider.get('embedding_model', 'unknown')}"
            )
        else:
            lines.append(f"- {name}: ready")
    return "\n".join(lines)


def _format_task_status(task: dict | None) -> str:
    if not task:
        return "当前没有任务计划。"
    completed = sum(
        step.get("status") == "completed" for step in task.get("steps", [])
    )
    lines = [
        f"任务: {task.get('objective', '')}",
        f"状态: {task.get('status', 'unknown')} · {completed}/{len(task.get('steps', []))}",
    ]
    for step in task.get("steps", []):
        icon = {
            "completed": "✓",
            "in_progress": "›",
            "pending": "·",
        }.get(step.get("status"), "?")
        note = f" · {step['note']}" if step.get("note") else ""
        lines.append(f"{icon} {step.get('step', '')}{note}")
    uncertain = task.get("uncertain_executions", [])
    if uncertain:
        lines.append(f"注意: {len(uncertain)} 个中断工具调用结果不确定，继续前需要验证。")
    return "\n".join(lines)


def _format_skill_usage_stats(stats: dict) -> str:
    if not stats.get("enabled"):
        return "Skill 使用追踪未启用。"
    total_turns = int(stats.get("total_turns", 0) or 0)
    total_events = int(stats.get("total_events", 0) or 0)
    load_rate = stats.get("skill_load_rate")
    success_rate = stats.get("success_rate")
    lines = [
        f"Skill 使用统计 · {total_turns} turns · {total_events} events",
        (
            "加载率 " + (f"{load_rate:.1%}" if load_rate is not None else "暂无")
            + " · 成功率 "
            + (f"{success_rate:.1%}" if success_rate is not None else "暂无")
        ),
    ]
    for item in stats.get("skills", []):
        lines.append(
            f"- {item.get('skill_name', '?')}: "
            f"view {item.get('views', 0)} · template {item.get('renders', 0)} · "
            f"script {item.get('script_runs', 0)} · failed {item.get('failures', 0)}"
        )
    if not stats.get("skills"):
        lines.append("暂无 Skill 调用记录。")
    return "\n".join(lines)


def _format_memory_search(results: list[dict]) -> str:
    if not results:
        return "没有找到相关向量记忆。"
    lines = [f"找到 {len(results)} 条相关记忆"]
    for result in results:
        content = " ".join(str(result.get("content", "")).split())
        if len(content) > 300:
            content = content[:300] + "..."
        score = float(result.get("score", 0) or 0)
        created_at = str(result.get("created_at", ""))[:19].replace("T", " ")
        lines.append(
            f"#{result.get('id', '?')} · {score:.2f} · {created_at or 'unknown time'}\n"
            f"  {content}"
        )
    return "\n".join(lines)


def _format_sessions(sessions: list[dict]) -> str:
    if not sessions:
        return "暂无历史会话。"
    lines = [f"历史会话 · {len(sessions)} 条"]
    for index, session in enumerate(sessions, 1):
        title = str(session.get("title") or "(untitled)").strip()
        if len(title) > 60:
            title = title[:60] + "..."
        lines.append(
            f"[{index}] {session.get('id', '')}\n"
            f"    {title}\n"
            f"    {session.get('message_count', 0)} messages · "
            f"{_format_timestamp(session.get('updated_at'))}"
        )
    lines.append("")
    lines.append("使用 /session-load <id> 恢复某个会话。")
    return "\n".join(lines)


def _format_session_search(results: list[dict]) -> str:
    if not results:
        return "没有找到相关历史会话。"
    lines = [f"历史搜索 · 找到 {len(results)} 条"]
    for result in results:
        snippet = " ".join(str(result.get("snippet") or result.get("content") or "").split())
        if len(snippet) > 260:
            snippet = snippet[:260] + "..."
        title = str(result.get("title") or "(untitled)").strip()
        role = result.get("role", "?")
        lines.append(
            f"{result.get('session_id', '')} · {role} · {_format_timestamp(result.get('created_at'))}\n"
            f"  {title}\n"
            f"  {snippet}"
        )
    lines.append("")
    lines.append("使用 /session-load <session_id> 恢复完整会话。")
    return "\n".join(lines)


def _format_timestamp(value) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return "unknown time"


def _request_command_approval(
    agent: Agent,
    tool_name: str,
    arguments: dict,
    reason: str,
) -> dict:
    decision = agent.permission_policy.decide(tool_name, "high")
    if decision.action == "deny":
        return {
            "approved": False,
            "decision": "deny",
            "policy_action": decision.action,
            "reason": decision.reason,
            "approval_duration_ms": 0,
        }
    if decision.action == "allow":
        return {
            "approved": True,
            "decision": "allow",
            "policy_action": decision.action,
            "reason": decision.reason,
            "approval_duration_ms": 0,
        }

    approval_id = f"tool-{uuid.uuid4().hex[:12]}"
    stdout(json.dumps({
        "type": "tool_approval_request",
        "id": approval_id,
        "name": tool_name,
        "risk": "high",
        "reason": f"{decision.reason}; {reason}",
        "arguments": sanitize_arguments(arguments),
    }, ensure_ascii=False))
    started = time.perf_counter()
    approval = "deny"
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if response.get("cmd") == "tool_approval" and response.get("id") == approval_id:
            approval = response.get("decision", "deny")
            if approval not in ("once", "session", "deny"):
                approval = "once" if response.get("approved") else "deny"
            break

    if approval == "session":
        agent.permission_policy.allow_for_session(tool_name)
    approved = approval in ("once", "session")
    stdout(json.dumps({
        "type": "tool_approval_result",
        "id": approval_id,
        "name": tool_name,
        "decision": approval,
        "approved": approved,
    }, ensure_ascii=False))
    return {
        "approved": approved,
        "decision": approval,
        "policy_action": decision.action,
        "reason": f"{decision.reason}; {reason}",
        "approval_duration_ms": round((time.perf_counter() - started) * 1000),
    }


def _audit_memory_command(
    agent: Agent,
    tool_name: str,
    arguments: dict,
    approval: dict,
    success: bool,
    executed: bool,
    duration_ms: int = 0,
    error: str = "",
) -> None:
    event = {
        "conversation_id": getattr(agent, "conv_id", None),
        "model": getattr(agent, "model", ""),
        "tool": tool_name,
        "risk": "high",
        "policy_action": approval.get("policy_action", "ask"),
        "decision": approval.get("decision", "deny"),
        "approved": approval.get("approved", False),
        "executed": executed,
        "success": success,
        "duration_ms": duration_ms,
        "approval_duration_ms": approval.get("approval_duration_ms", 0),
        "arguments": sanitize_arguments(arguments),
        "reason": approval.get("reason", ""),
    }
    if error:
        event["error"] = str(error)[:300]
    try:
        agent.audit.log(event)
    except Exception:
        pass
