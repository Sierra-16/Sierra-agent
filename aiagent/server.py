"""JSON-line stdin/stdout server for the TUI frontend."""
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
from .gateway import GatewayRuntime
from .safety import sanitize_arguments


def run_server(
    agent: Agent,
    config: dict | None = None,
    config_path: str | None = None,
    make_agent: Callable[[str], Agent] | None = None,
):
    current_agent = agent
    gateway = GatewayRuntime(
        current_agent,
        config=config,
        config_path=config_path,
        make_agent=make_agent,
        id_factory=lambda: uuid.uuid4().hex,
    )

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
            stdout(json.dumps({
                "type": "init",
                "model": current_agent.llm.model,
                "cwd": getattr(current_agent, "workspace", None) or os.getcwd(),
                "recent": recent,
                "cron_due": _agent_cron_due(current_agent),
                "usage": _usage_payload(current_agent),
                "task": _agent_task_status(current_agent),
                "recovery_task": _agent_task_recovery(current_agent),
            }, ensure_ascii=False))

        elif cmd == "chat":
            user_msg = msg.get("text", "")
            if not user_msg:
                continue
            try:
                def emit(event):
                    sys.__stdout__.write(json.dumps(event, ensure_ascii=False) + "\n")
                    sys.__stdout__.flush()

                def read_interaction(expected_cmd, request_id):
                    while True:
                        response_line = sys.stdin.readline()
                        if not response_line:
                            if expected_cmd == "user_input_response":
                                return {"cancelled": True}
                            return {"decision": "deny"}

                        try:
                            response_msg = json.loads(response_line)
                        except json.JSONDecodeError:
                            continue

                        response_cmd = response_msg.get("cmd")
                        if response_cmd == expected_cmd and response_msg.get("id") == request_id:
                            return response_msg

                        if response_cmd == "quit":
                            _auto_save(current_agent)
                            current_agent.close()
                            stdout(json.dumps({"type": "bye"}))
                            raise SystemExit(0)

                result = gateway.chat(
                    user_msg,
                    emit=emit,
                    interaction="interactive",
                    input_reader=read_interaction,
                    suppress_output=True,
                )
                stdout(json.dumps({
                    "type": "done",
                    "text": result.answer or "",
                    "usage": _usage_payload(current_agent),
                    "task": _agent_task_status(current_agent),
                }, ensure_ascii=False))
                _auto_save(current_agent)
                continue

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
                    "text": "闂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸婂潡鏌ㄩ弴妤€浜惧銈庝簻閸熸潙鐣疯ぐ鎺濇晪闁告侗鍨版慨娲⒒娴ｄ警娼掗柛鏇炵仛閻ｅ墎绱撴担鎻掍壕婵犮垼娉涙径鍥磻閹捐崵宓侀柛顭戝枛婵骸鈹戦悙棰濆殝缂佺姵鎸搁悾? /session-search <闂傚倸鍊搁崐鎼佸磹閹间礁纾归柣鎴ｅГ閸ゅ嫰鏌涢锝嗙５闁逞屽墾缁犳挸鐣锋總绋款潊闁炽儱鍟跨花銉╂⒒娴ｇ儤鍤€妞ゆ洦鍙冨畷鎴︽偄閾忛€涚瑝闂佽鍨庨埀顒勫绩娴犲鐓熸俊顖氭惈缁狙囨煙閸忕厧濮嶉柡宀嬬磿閳ь剨绲洪弲婵嬪礉瀹ュ鐓忛柛銉戝喚浼冨Δ鐘靛仦椤洭骞戦崟顖涘剮闁硅櫣鍋熺粔顕€鏌?",
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
                    "text": "Usage: /session-load <session_id>",
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
                    "Loaded session " + session_id
                    if result.get("ok")
                    else result.get("error", "Failed to load session.")
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
                stdout(json.dumps({
                    "type": "resumed",
                    "title": title,
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

        elif cmd == "undo":
            try:
                count = max(1, min(20, int(msg.get("count", 1) or 1)))
            except (TypeError, ValueError):
                count = 1
            result = current_agent.undo_last_turn(count)
            if result.get("ok"):
                _auto_save(current_agent)
            stdout(json.dumps({
                "type": "history_changed",
                "success": bool(result.get("ok")),
                "text": (
                    "Undid " + str(result.get("removed_user_turns", count)) + " turns."
                    if result.get("ok")
                    else result.get("error", "Undo failed.")
                ),
                "messages": _display_messages(current_agent),
                "usage": _usage_payload(current_agent),
                "task": _agent_task_status(current_agent),
            }, ensure_ascii=False))

        elif cmd == "retry":
            result = current_agent.retry_last_turn()
            if not result.get("ok"):
                stdout(json.dumps({
                    "type": "history_changed",
                    "success": False,
                    "text": result.get("error", "Retry failed; previous user message was not found."),
                    "messages": _display_messages(current_agent),
                    "usage": _usage_payload(current_agent),
                    "task": _agent_task_status(current_agent),
                }, ensure_ascii=False))
                continue
            _auto_save(current_agent)
            stdout(json.dumps({
                "type": "retry_ready",
                "success": True,
                "text": "Ready to retry the previous turn.",
                "query": result.get("user_message", ""),
                "messages": _display_messages(current_agent),
                "usage": _usage_payload(current_agent),
                "task": _agent_task_status(current_agent),
            }, ensure_ascii=False))

        elif cmd == "compress":
            old = len(current_agent.messages)
            result = current_agent.compress_messages(force=True)
            if result.get("compressed"):
                text = (
                    "Compressed: "
                    + str(old)
                    + " -> "
                    + str(len(current_agent.messages))
                    + " messages, approx "
                    + str(result["before_tokens"])
                    + " -> "
                    + str(result["after_tokens"])
                    + " tokens"
                )
            else:
                text = "Current context does not need compression."
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

        elif cmd == "cron":
            status = current_agent.cron_status()
            stdout(json.dumps({
                "type": "cron",
                "text": _format_cron_status(status),
                "tasks": status.get("tasks", []),
                "enabled": bool(status.get("enabled")),
            }, ensure_ascii=False))

        elif cmd == "cron_due":
            due = _agent_cron_due(current_agent)
            stdout(json.dumps({
                "type": "cron_due",
                "tasks": due,
                "text": _format_cron_due(due),
            }, ensure_ascii=False))

        elif cmd == "cron_remove_options":
            status = current_agent.cron_status()
            stdout(json.dumps({
                "type": "cron_remove_options",
                "tasks": status.get("tasks", []),
                "enabled": bool(status.get("enabled")),
            }, ensure_ascii=False))

        elif cmd == "cron_add":
            prompt = str(msg.get("prompt") or "").strip()
            try:
                interval_minutes = max(1, int(msg.get("interval_minutes", 60) or 60))
            except (TypeError, ValueError):
                interval_minutes = 60
            approval = _request_command_approval(
                current_agent,
                "cron_add",
                {"prompt": prompt, "interval_minutes": interval_minutes},
                "Create a scheduled reminder.",
            )
            if not approval["approved"]:
                stdout(json.dumps({
                    "type": "cron",
                    "success": False,
                    "text": "Scheduled reminder creation was cancelled.",
                }, ensure_ascii=False))
                continue
            result = current_agent.cron_add(prompt, interval_minutes)
            stdout(json.dumps({
                "type": "cron",
                "success": bool(result.get("ok")),
                "text": (
                    "Created scheduled reminder " + str(result.get("task", {}).get("id", ""))
                    if result.get("ok")
                    else result.get("error", "Failed to create scheduled reminder.")
                ),
                "tasks": current_agent.cron_status().get("tasks", []),
                "enabled": True,
            }, ensure_ascii=False))

        elif cmd == "cron_remove":
            task_id = str(msg.get("id") or "").strip()
            if not task_id:
                stdout(json.dumps({
                    "type": "cron",
                    "success": False,
                    "text": "Usage: /cron-remove <task_id>",
                    "tasks": current_agent.cron_status().get("tasks", []),
                    "enabled": True,
                }, ensure_ascii=False))
                continue
            if msg.get("confirmed") is True:
                approval = {"approved": True}
            else:
                approval = _request_command_approval(
                    current_agent,
                    "cron_remove",
                    {"id": task_id},
                    "Remove a scheduled reminder.",
                )
            if not approval["approved"]:
                stdout(json.dumps({
                    "type": "cron",
                    "success": False,
                    "text": "Scheduled reminder removal was cancelled.",
                }, ensure_ascii=False))
                continue
            result = current_agent.cron_remove(task_id)
            stdout(json.dumps({
                "type": "cron",
                "success": bool(result.get("ok")),
                "text": "Removed scheduled reminder." if result.get("ok") else result.get("error", "Failed to remove scheduled reminder."),
                "tasks": current_agent.cron_status().get("tasks", []),
                "enabled": True,
            }, ensure_ascii=False))

        elif cmd == "memory_search":
            query = str(msg.get("query", "")).strip()
            if not query:
                stdout(json.dumps({
                    "type": "memory_search",
                    "text": "Usage: /memory-search <query>",
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
                        "text": "Usage: /memory-forget <ID>",
                        "success": False,
                    }, ensure_ascii=False))
                    continue
                arguments = {"id": memory_id}
                reason = "Forget one stored memory item #" + str(memory_id) + "."
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
                        "text": "Vector memory is already empty.",
                        "success": True,
                    }, ensure_ascii=False))
                    continue
                clear_count = int((vector_status or {}).get("records", 0) or 0)
                arguments = {"records": clear_count}
                reason = "Clear vector memory records: " + str(clear_count) + "."

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
                    error="User denied memory action.",
                )
                stdout(json.dumps({
                    "type": "memory_action",
                    "text": "Memory action was cancelled.",
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
                    "Forgot memory #" + str(arguments["id"]) + "."
                    if success
                    else result.get("error", "Failed to forget memory.")
                )
            else:
                text = (
                    "Cleared " + str(result.get("deleted", 0)) + " memory records."
                    if success
                    else result.get("error", "Failed to clear memory.")
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
                    "Task resumed."
                    if result.get("ok")
                    else result.get("error", "Failed to resume task.")
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
                    "Task abandoned."
                    if result.get("ok")
                    else result.get("error", "Failed to abandon task.")
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
            gateway.set_agent(current_agent)
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
        usage = dict(usage_snapshot() or {})
    else:
        usage = {
            "input": getattr(agent, "total_input_tokens", 0),
            "output": getattr(agent, "total_output_tokens", 0),
            "context": getattr(agent, "current_context_tokens", 0),
            "context_estimated": getattr(agent, "context_tokens_estimated", False),
        }
    usage.setdefault("context", getattr(agent, "current_context_tokens", 0))
    usage.setdefault(
        "context_estimated",
        getattr(agent, "context_tokens_estimated", False),
    )
    usage["context_window"] = int(getattr(agent, "context_window", 0) or 0)
    return usage


def _agent_task_status(agent: Agent) -> dict | None:
    task_status = getattr(agent, "task_status", None)
    return task_status() if callable(task_status) else None


def _agent_task_recovery(agent: Agent, task_id: str | None = None) -> dict | None:
    task_recovery = getattr(agent, "task_recovery", None)
    return task_recovery(task_id) if callable(task_recovery) else None


def _agent_cron_due(agent: Agent) -> list[dict]:
    cron_due = getattr(agent, "cron_due", None)
    if not callable(cron_due):
        return []
    try:
        return cron_due()
    except Exception:
        return []


def _display_messages(agent: Agent) -> list[dict[str, str]]:
    messages = []
    for message in getattr(agent, "messages", []):
        role = message.get("role")
        if role not in ("user", "assistant", "system", "error"):
            continue
        content = message.get("content")
        if not content:
            continue
        messages.append({"role": role, "text": str(content)})
    return messages


def _format_memory_status(status: dict) -> str:
    lines = ["Memory status"]
    curated = str(status.get("curated") or "").strip()
    if curated:
        lines.append(curated)
    else:
        lines.append("No curated markdown memory yet.")
    lines.append("")
    lines.append("Providers:")
    for provider in status.get("providers", []):
        name = str(provider.get("name", "unknown"))
        if not provider.get("available", False):
            lines.append("- " + name + ": unavailable (" + str(provider.get("error", "unknown error")) + ")")
        elif name == "markdown":
            lines.append(
                "- markdown: "
                + str(provider.get("memory_entries", 0))
                + " memory entries, "
                + str(provider.get("user_entries", 0))
                + " user entries"
            )
        elif name == "local_vector":
            lines.append(
                "- local_vector: \u5f53\u524d\u5de5\u4f5c\u533a "
                + str(provider.get("records", 0))
                + " \u6761, model "
                + str(provider.get("embedding_model", "unknown"))
            )
        else:
            lines.append("- " + name + ": ready")
    return "\n".join(lines)


def _format_cron_status(status: dict) -> str:
    if not status.get("enabled"):
        return "Cron reminders are not available."
    tasks = status.get("tasks", [])
    if not tasks:
        return "No scheduled reminders. Use /cron-add <prompt> <minutes>."
    lines = ["Scheduled reminders: " + str(len(tasks))]
    for task in tasks:
        next_run = _format_timestamp(task.get("next_run_at"))
        lines.append(
            "- "
            + str(task.get("id", ""))
            + " 路 every "
            + str(task.get("interval_minutes", "?"))
            + " min 路 next "
            + next_run
            + "\n  "
            + str(task.get("prompt", ""))
        )
    return "\n".join(lines)


def _format_cron_due(tasks: list[dict]) -> str:
    if not tasks:
        return ""
    lines = ["Scheduled reminders due:"]
    for task in tasks:
        lines.append("- " + str(task.get("prompt", "")))
    return "\n".join(lines)


def _format_task_status(task: dict | None) -> str:
    if not task:
        return "No active task."
    steps = task.get("steps", [])
    completed = sum(step.get("status") == "completed" for step in steps)
    lines = [
        "Task: " + str(task.get("objective", "")),
        "Status: " + str(task.get("status", "unknown")) + " 路 " + str(completed) + "/" + str(len(steps)),
    ]
    for step in steps:
        icon = {
            "completed": "[x]",
            "in_progress": "[>]",
            "pending": "[ ]",
        }.get(step.get("status"), "[?]")
        note = " 路 " + str(step.get("note")) if step.get("note") else ""
        lines.append(icon + " " + str(step.get("step", "")) + note)
    uncertain = task.get("uncertain_executions", [])
    if uncertain:
        lines.append("Uncertain executions: " + str(len(uncertain)))
    return "\n".join(lines)


def _format_skill_usage_stats(stats: dict) -> str:
    if not stats.get("enabled"):
        return "Skill usage stats are not available."
    total_turns = int(stats.get("total_turns", 0) or 0)
    total_events = int(stats.get("total_events", 0) or 0)
    load_rate = stats.get("skill_load_rate")
    success_rate = stats.get("success_rate")
    load_text = "n/a" if load_rate is None else format(load_rate, ".1%")
    success_text = "n/a" if success_rate is None else format(success_rate, ".1%")
    lines = [
        "Skill usage: " + str(total_turns) + " turns, " + str(total_events) + " events",
        "Load rate: " + load_text + " 路 success rate: " + success_text,
    ]
    for item in stats.get("skills", []):
        lines.append(
            "- "
            + str(item.get("skill_name", "?"))
            + ": view "
            + str(item.get("views", 0))
            + " 路 template "
            + str(item.get("renders", 0))
            + " 路 script "
            + str(item.get("script_runs", 0))
            + " 路 failed "
            + str(item.get("failures", 0))
        )
    if not stats.get("skills"):
        lines.append("No skill usage has been recorded yet.")
    return "\n".join(lines)


def _format_memory_search(results: list[dict]) -> str:
    if not results:
        return "No memory results found."
    lines = ["Memory search results: " + str(len(results))]
    for result in results:
        content = " ".join(str(result.get("content", "")).split())
        if len(content) > 300:
            content = content[:300] + "..."
        score = float(result.get("score", 0) or 0)
        created_at = str(result.get("created_at", ""))[:19].replace("T", " ")
        lines.append(
            "#"
            + str(result.get("id", "?"))
            + " 路 "
            + format(score, ".2f")
            + " 路 "
            + (created_at or "unknown time")
            + "\n  "
            + content
        )
    return "\n".join(lines)


def _format_sessions(sessions: list[dict]) -> str:
    if not sessions:
        return "No saved sessions yet."
    lines = ["Saved sessions: " + str(len(sessions))]
    for index, session in enumerate(sessions, 1):
        title = str(session.get("title") or "(untitled)").strip()
        if len(title) > 60:
            title = title[:60] + "..."
        lines.append(
            "["
            + str(index)
            + "] "
            + str(session.get("id", ""))
            + "\n    "
            + title
            + "\n    "
            + str(session.get("message_count", 0))
            + " messages 路 "
            + _format_timestamp(session.get("updated_at"))
        )
    lines.append("")
    lines.append("Use /session-load <id> to open a session.")
    return "\n".join(lines)


def _format_session_search(results: list[dict]) -> str:
    if not results:
        return "No session results found."
    lines = ["Session search results: " + str(len(results))]
    for result in results:
        snippet = " ".join(str(result.get("snippet") or result.get("content") or "").split())
        if len(snippet) > 260:
            snippet = snippet[:260] + "..."
        title = str(result.get("title") or "(untitled)").strip()
        role = str(result.get("role", "?"))
        lines.append(
            str(result.get("session_id", ""))
            + " 路 "
            + role
            + " 路 "
            + _format_timestamp(result.get("created_at"))
            + "\n  "
            + title
            + "\n  "
            + snippet
        )
    lines.append("")
    lines.append("Use /session-load <session_id> to open a session.")
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
