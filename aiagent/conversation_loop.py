import json
import time

from .context_budget import (
    fit_messages_to_budget,
    prepare_conversation_messages_for_request,
)
from .context_errors import (
    CONTEXT_OVERFLOW,
    OUTPUT_LIMIT,
    PAYLOAD_TOO_LARGE,
    classify_llm_error,
    extract_available_output_tokens,
    extract_context_window,
)
from .safety import sanitize_arguments, sanitize_text
from .token_utils import estimate_tokens
from .turn_context import build_memory_context, build_turn_context


SKILL_EVENT_BY_TOOL = {
    "skill_view": "view",
    "skill_render_template": "template_render",
    "skill_run_script": "script_run",
}


def summarize_tool_result(result, max_length=160):
    """Build a compact, user-facing status summary for a tool result."""
    success, error = _tool_result_status_from_value(result)
    if error:
        return {
            "success": False,
            "summary": sanitize_text(error, max_length=max_length),
        }

    value = _parse_tool_result(result)
    summary = ""
    if isinstance(value, dict):
        summary = _pick_result_summary(value)
    elif isinstance(value, list):
        summary = f"{len(value)} item(s)"
    elif value not in (None, ""):
        summary = str(value)

    summary = sanitize_text(summary or "done", max_length=max_length)
    return {"success": success, "summary": summary}


def _parse_tool_result(result):
    if not isinstance(result, str):
        return result
    try:
        return json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return result


def _tool_result_status_from_value(result):
    value = _parse_tool_result(result)
    if not isinstance(value, dict):
        return True, ""
    if value.get("error"):
        return False, sanitize_text(str(value["error"]), max_length=300)
    if value.get("ok") is False or value.get("success") is False:
        detail = (
            value.get("stderr")
            or value.get("message")
            or value.get("detail")
            or value.get("reason")
            or "tool returned failure status"
        )
        return False, sanitize_text(str(detail), max_length=300)

    nested = value.get("result")
    if isinstance(nested, dict) and nested.get("isError"):
        return False, "MCP tool returned isError=true"
    return True, ""


def _pick_result_summary(value):
    for key in ("message", "summary", "title", "path", "file_path", "url"):
        item = value.get(key)
        if item:
            return str(item)

    if "directories" in value or "files" in value:
        directories = len(value.get("directories") or [])
        files = len(value.get("files") or [])
        return f"{directories} folder(s), {files} file(s)"

    if "matches" in value and isinstance(value.get("matches"), list):
        return f"{len(value['matches'])} match(es)"

    for key in ("deleted", "saved", "count", "records"):
        if key in value:
            return f"{key}: {value.get(key)}"

    stdout = value.get("stdout")
    if stdout:
        return _first_nonempty_line(str(stdout))

    text = value.get("text") or value.get("content")
    if text:
        return _first_nonempty_line(str(text))

    nested = value.get("result")
    if isinstance(nested, dict):
        nested_summary = _pick_result_summary(nested)
        if nested_summary:
            return nested_summary
    elif nested not in (None, ""):
        return str(nested)

    return "done"


def _first_nonempty_line(text):
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def run_conversation_loop(
    agent,
    user_message: str,
    on_status=None,
    on_tool_approval=None,
    on_user_input=None,
):
    turn_start_index = len(agent.messages)
    checkpoint_manager = getattr(agent, "checkpoints", None)
    if checkpoint_manager is not None:
        try:
            checkpoint_manager.new_turn()
        except Exception:
            pass
    agent.messages.append({"role": "user", "content": user_message})
    checkpoint_conversation = getattr(agent, "checkpoint_conversation", None)
    if callable(checkpoint_conversation):
        checkpoint_conversation()
    memory_manager = getattr(agent, "memory_manager", None)
    task_manager = getattr(agent, "task_manager", None)
    skill_usage = getattr(agent, "skill_usage", None)
    skill_turn_id = None
    if skill_usage is not None:
        try:
            skill_turn_id = skill_usage.start_turn(
                user_query=user_message,
                conversation_id=getattr(agent, "conv_id", None),
                model=getattr(agent, "model", ""),
                workspace=getattr(agent, "workspace", ""),
            )
        except Exception:
            skill_turn_id = None
    turn_context = build_turn_context(agent, user_message, on_status=on_status)
    try:
        agent.last_turn_context = turn_context
    except Exception:
        pass

    def on_delta(event):
        if event["type"] == "reasoning":
            if not on_delta.state["in_reasoning"]:
                print("\n🧠 思考中")
                on_delta.state["in_reasoning"] = True
                if on_status:
                    on_status({"type": "thinking"})

        elif event["type"] == "content":
            if on_status:
                on_status({"type": "assistant_delta", "text": event["text"]})
            if on_delta.state["in_reasoning"]:
                print("\n")
                on_delta.state["in_reasoning"] = False
            for char in event["text"]:
                print(char, end="", flush=True)
                time.sleep(0.025)

        elif event["type"] == "tool_start":
            if on_status:
                on_status({
                        "type": "tool_start",
                        "name": event.get("name", "tool"),
                    })
            if on_delta.state["in_reasoning"]:
                on_delta.state["in_reasoning"] = False
            print(f"\n🔧 调用工具: {event['name']}")
            if on_status:
                on_status({"type": "tool", "name": event["name"]})

    def _exec_tool(tc):
        name = tc["function"]["name"]
        args = json.loads(tc["function"]["arguments"])
        if name == "request_user_input":
            return _request_user_input(tc, args)

        safe_arguments = sanitize_arguments(args)
        risk = agent.safety.assess(name, args)
        decision = agent.permission_policy.decide(name, risk.level)

        if decision.action == "deny":
            result = {
                "error": "权限策略禁止执行该工具",
                "tool": name,
                "risk": risk.level,
                "reason": decision.reason,
            }
            _write_audit({
                "tool": name,
                "risk": risk.level,
                "policy_action": decision.action,
                "decision": "deny",
                "approved": False,
                "executed": False,
                "success": False,
                "duration_ms": 0,
                "arguments": safe_arguments,
                "reason": decision.reason,
                "error": result["error"],
            })
            _record_skill_event(
                name,
                args,
                success=False,
                executed=False,
                duration_ms=0,
                error=result["error"],
            )
            return tc["id"], name, json.dumps(result, ensure_ascii=False)

        effective_decision = "allow"
        approval_duration_ms = 0
        if decision.action == "ask":
            if on_status:
                on_status({
                    "type": "tool_approval_waiting",
                    "name": name,
                    "risk": risk.level,
                })

            approval = "deny"
            approval_started = time.perf_counter()
            if on_tool_approval:
                approval = on_tool_approval({
                    "name": name,
                    "arguments": safe_arguments,
                    "risk": risk.level,
                    "reason": f"{decision.reason}; {risk.reason}",
                })
            approval_duration_ms = round(
                (time.perf_counter() - approval_started) * 1000
            )
            if approval is True:
                approval = "once"
            elif approval is False:
                approval = "deny"

            if approval == "session":
                agent.permission_policy.allow_for_session(name)

            if approval not in ("once", "session"):
                result = {
                    "error": "用户拒绝执行该工具",
                    "tool": name,
                    "risk": risk.level,
                    "reason": f"{decision.reason}; {risk.reason}",
                }
                _write_audit({
                    "tool": name,
                    "risk": risk.level,
                    "policy_action": decision.action,
                    "decision": "deny",
                    "approved": False,
                    "executed": False,
                    "success": False,
                    "duration_ms": 0,
                    "approval_duration_ms": approval_duration_ms,
                    "arguments": safe_arguments,
                    "reason": result["reason"],
                    "error": result["error"],
                })
                _record_skill_event(
                    name,
                    args,
                    success=False,
                    executed=False,
                    duration_ms=0,
                    error=result["error"],
                )
                return tc["id"], name, json.dumps(result, ensure_ascii=False)

            effective_decision = approval

        execution_started = time.perf_counter()
        task_execution_id = None
        if task_manager is not None:
            try:
                task_execution_id = task_manager.start_tool_execution(
                    tool_call_id=str(tc.get("id") or ""),
                    tool_name=name,
                    risk=risk.level,
                    arguments=safe_arguments,
                )
            except Exception:
                task_execution_id = None
        try:
            checkpoint_before_tool = getattr(agent, "checkpoint_before_tool", None)
            if callable(checkpoint_before_tool):
                try:
                    checkpoint_before_tool(name, args)
                except Exception:
                    pass
            result = agent.tools.execute(name, args)
        except Exception as exc:
            if task_manager is not None:
                try:
                    task_manager.finish_tool_execution(
                        task_execution_id,
                        success=False,
                        result_summary=sanitize_text(str(exc), max_length=1000),
                    )
                except Exception:
                    pass
            _record_skill_event(
                name,
                args,
                success=False,
                executed=True,
                duration_ms=round((time.perf_counter() - execution_started) * 1000),
                error=str(exc),
            )
            raise
        duration_ms = round((time.perf_counter() - execution_started) * 1000)
        success, error = _tool_result_status(result)
        if task_manager is not None:
            try:
                task_manager.finish_tool_execution(
                    task_execution_id,
                    success=success,
                    result_summary=sanitize_text(str(result), max_length=1000),
                )
            except Exception:
                pass
        audit_event = {
            "tool": name,
            "risk": risk.level,
            "policy_action": decision.action,
            "decision": effective_decision,
            "approved": True,
            "executed": True,
            "success": success,
            "duration_ms": duration_ms,
            "arguments": safe_arguments,
            "reason": decision.reason,
        }
        if approval_duration_ms:
            audit_event["approval_duration_ms"] = approval_duration_ms
        if error:
            audit_event["error"] = error
        _write_audit(audit_event)
        _record_skill_event(
            name,
            args,
            success=success,
            executed=True,
            duration_ms=duration_ms,
            error=error,
        )
        return tc["id"], name, result

    def _request_user_input(tc, args):
        request = _normalize_user_input_request(args)
        if on_status:
            on_status({
                "type": "user_input_waiting",
                "name": "request_user_input",
            })

        if on_user_input is None:
            result = {
                "error": "当前界面不支持交互式用户输入",
                "cancelled": True,
            }
        else:
            response = on_user_input(request)
            if isinstance(response, str):
                response = {
                    "value": response,
                    "label": response,
                    "free_text": True,
                }
            if not isinstance(response, dict):
                response = {"cancelled": True}
            result = {
                "status": "cancelled" if response.get("cancelled") else "answered",
                "answer": response,
            }

        return (
            tc["id"],
            "request_user_input",
            json.dumps(result, ensure_ascii=False),
        )

    def _normalize_user_input_request(args):
        question = str(args.get("question", "")).strip()
        raw_options = args.get("options")
        options = []
        if isinstance(raw_options, list):
            for raw_option in raw_options[:3]:
                if not isinstance(raw_option, dict):
                    continue
                label = str(raw_option.get("label", "")).strip()
                if not label:
                    continue
                options.append({
                    "label": label,
                    "description": str(raw_option.get("description", "")).strip(),
                    "value": str(raw_option.get("value") or label),
                })
        return {
            "question": question or "请补充你的需求",
            "options": options,
            "allow_free_text": args.get("allow_free_text", True) is not False,
        }

    def _write_audit(event):
        audit = getattr(agent, "audit", None)
        if audit is None:
            return
        event = {
            "conversation_id": getattr(agent, "conv_id", None),
            "model": getattr(agent, "model", ""),
            **event,
        }
        try:
            audit.log(event)
        except Exception:
            pass

    def _record_skill_event(
        tool_name,
        arguments,
        *,
        success,
        executed,
        duration_ms,
        error="",
    ):
        event_type = SKILL_EVENT_BY_TOOL.get(tool_name)
        if event_type is None or skill_usage is None:
            return
        try:
            skill_usage.record(
                turn_id=skill_turn_id,
                skill_name=str(arguments.get("name") or ""),
                event_type=event_type,
                file_path=str(arguments.get("file_path") or ""),
                success=success,
                executed=executed,
                duration_ms=duration_ms,
                conversation_id=getattr(agent, "conv_id", None),
                model=getattr(agent, "model", ""),
                workspace=getattr(agent, "workspace", ""),
                user_query=user_message,
                error=error,
            )
        except Exception:
            pass

    def _tool_result_status(result):
        return _tool_result_status_from_value(result)

    def _prepare_request_messages():
        return prepare_conversation_messages_for_request(
            agent.messages,
            old_tool_result_max_chars=getattr(
                agent,
                "old_tool_result_max_chars",
                2400,
            ),
            recent_tool_result_max_chars=getattr(
                agent,
                "recent_tool_result_max_chars",
                12000,
            ),
            recent_message_count=getattr(
                agent,
                "recent_tool_result_message_count",
                8,
            ),
        )

    def _call_compress_messages(*, force=False, keep_tokens=None):
        compress_messages = getattr(agent, "compress_messages", None)
        if not callable(compress_messages):
            return {"compressed": False, "reason": "compression_unavailable"}
        try:
            return compress_messages(force=force, keep_tokens=keep_tokens)
        except TypeError as exc:
            message = str(exc)
            if "unexpected keyword" not in message and "positional argument" not in message:
                raise
            try:
                if keep_tokens is None:
                    return compress_messages()
                return compress_messages(keep_tokens=keep_tokens)
            except TypeError as inner_exc:
                inner_message = str(inner_exc)
                if (
                    "unexpected keyword" not in inner_message
                    and "positional argument" not in inner_message
                ):
                    raise
                return compress_messages()

    def _compact_if_needed(current_tokens, *, phase, recompute_tokens):
        if not getattr(agent, "compression_enabled", True):
            return False

        max_tokens = int(getattr(agent, "max_compress_tokens", 0) or 0)
        if max_tokens <= 0 or current_tokens <= max_tokens:
            return False

        attempts = 0
        max_attempts = int(getattr(agent, "compression_max_passes", 1) or 1)
        compacted = False
        while current_tokens > max_tokens and attempts < max_attempts:
            attempts += 1
            before_compaction_tokens = current_tokens
            if on_status:
                on_status({
                    "type": "context_compaction_start",
                    "phase": phase,
                    "before_tokens": before_compaction_tokens,
                })
            else:
                print("\n⚠️ 上下文过长，正在压缩...")

            keep_tokens = max(
                1,
                min(
                    getattr(agent, "compression_keep_tokens", max_tokens),
                    getattr(agent, "compression_target_tokens", max_tokens),
                ),
            )
            compaction_result = _call_compress_messages(
                force=False,
                keep_tokens=keep_tokens,
            )
            if not isinstance(compaction_result, dict):
                compaction_result = {"compressed": False, "reason": "unknown"}

            if not compaction_result.get("compressed"):
                event_type = (
                    "context_compaction_failed"
                    if compaction_result.get("reason") == "summary_failed"
                    else "context_compaction_skipped"
                )
                if on_status:
                    on_status({
                        "type": event_type,
                        "phase": phase,
                        "before_tokens": before_compaction_tokens,
                    })
                else:
                    print("ℹ️ 当前没有可安全压缩的完整历史轮次。")
                break

            compacted = True
            try:
                current_tokens = int(recompute_tokens() or 0)
            except Exception:
                current_tokens = estimate_tokens(agent.messages)
            if on_status:
                on_status({
                    "type": "context_compaction_done",
                    "phase": phase,
                    "before_tokens": before_compaction_tokens,
                    "after_tokens": current_tokens,
                    "summarized_messages": compaction_result.get(
                        "summarized_messages", 0
                    ),
                    "kept_messages": compaction_result.get("kept_messages", 0),
                })
            else:
                print(
                    f"✅ 压缩完成：{before_compaction_tokens} → {current_tokens} tokens。"
                )
        return compacted

    def _estimate_persistent_history_tokens():
        return estimate_tokens(agent.messages)

    def _prepare_api_messages(tools):
        request_messages, request_prepare_stats = _prepare_request_messages()
        api_messages = turn_context.build_messages(request_messages)
        estimated_context_tokens = estimate_tokens(api_messages, tools=tools)
        if _compact_if_needed(
            estimated_context_tokens,
            phase="preflight",
            recompute_tokens=lambda: estimate_tokens(
                turn_context.build_messages(_prepare_request_messages()[0]),
                tools=tools,
            ),
        ):
            if callable(checkpoint_conversation):
                checkpoint_conversation()
            request_messages, request_prepare_stats = _prepare_request_messages()
            api_messages = turn_context.build_messages(request_messages)
            estimated_context_tokens = estimate_tokens(api_messages, tools=tools)
        context_budget = int(getattr(agent, "context_window", 0) or 0)
        if context_budget > 0 and estimated_context_tokens > context_budget:
            api_messages, omitted_messages = fit_messages_to_budget(
                turn_context.system_messages(),
                request_messages,
                tools=tools,
                max_tokens=context_budget,
            )
            trimmed_tokens = estimate_tokens(api_messages, tools=tools)
            if omitted_messages and on_status:
                on_status({
                    "type": "context_budget_trimmed",
                    "before_tokens": estimated_context_tokens,
                    "after_tokens": trimmed_tokens,
                    "omitted_messages": omitted_messages,
                })
            estimated_context_tokens = trimmed_tokens
        if request_prepare_stats.get("truncated_tool_results") and on_status:
            on_status({
                "type": "context_tool_results_trimmed",
                "count": request_prepare_stats.get("truncated_tool_results", 0),
                "omitted_chars": request_prepare_stats.get("omitted_tool_result_chars", 0),
            })
        return api_messages, estimated_context_tokens

    def _update_context_window_from_error(error):
        detected_window = extract_context_window(error)
        if not detected_window:
            return False
        current_window = int(getattr(agent, "model_context_window", 0) or 0)
        if current_window and detected_window >= current_window:
            return False
        update_context_window = getattr(agent, "update_context_window", None)
        if callable(update_context_window):
            try:
                update_context_window(detected_window)
            except Exception:
                return False
        else:
            agent.model_context_window = detected_window
            agent.compression_context_window = detected_window
        if on_status:
            on_status({
                "type": "context_window_updated",
                "context_window": detected_window,
            })
        return True

    def _reduce_output_tokens_from_error(error, estimated_context_tokens):
        current_max = int(getattr(agent.llm, "max_tokens", 0) or 0)
        if current_max <= 0:
            return False

        available = extract_available_output_tokens(error)
        if not available:
            model_window = int(
                getattr(
                    agent,
                    "model_context_window",
                    getattr(agent, "compression_context_window", 0),
                )
                or 0
            )
            if model_window > 0:
                available = model_window - int(estimated_context_tokens or 0) - 128
        if not available or available <= 128:
            return False

        new_max = min(current_max - 1, max(128, int(available) - 64))
        if new_max <= 0 or new_max >= current_max:
            return False
        agent.llm.max_tokens = new_max
        if on_status:
            on_status({
                "type": "context_output_tokens_reduced",
                "from": current_max,
                "to": new_max,
            })
        return True

    def _context_recovery_failed_response(error, category):
        if category == OUTPUT_LIMIT:
            content = (
                "模型可用输出空间不足，我已经尝试降低本次输出长度，但仍然无法继续。"
                "请先压缩会话或开启新会话后再试。"
            )
        else:
            content = (
                "当前会话已经超过模型上下文窗口，我尝试压缩后仍然放不下。"
                "请使用 /compress 或 /new 后继续。"
            )
        if on_status:
            on_status({
                "type": "context_recovery_failed",
                "category": category,
                "error": sanitize_text(str(error), max_length=500),
            })
        return {
            "content": content,
            "tool_calls": None,
            "usage": {"input": 0, "output": 0},
            "finish_reason": "context_recovery_failed",
        }

    def _call_llm_with_recovery(api_messages, tools, estimated_context_tokens):
        attempts = 0
        max_attempts = max(
            1,
            int(getattr(agent, "compression_max_passes", 1) or 1) + 1,
        )
        while True:
            try:
                return (
                    agent.llm.stream_chat(api_messages, tools, on_delta),
                    estimated_context_tokens,
                )
            except Exception as exc:
                category = classify_llm_error(exc)
                if category == OUTPUT_LIMIT:
                    if attempts < max_attempts and _reduce_output_tokens_from_error(
                        exc,
                        estimated_context_tokens,
                    ):
                        attempts += 1
                        continue
                    return _context_recovery_failed_response(exc, category), estimated_context_tokens

                if category not in (CONTEXT_OVERFLOW, PAYLOAD_TOO_LARGE):
                    raise

                if attempts >= max_attempts:
                    return _context_recovery_failed_response(exc, category), estimated_context_tokens

                attempts += 1
                _update_context_window_from_error(exc)
                if not getattr(agent, "compression_enabled", True):
                    return _context_recovery_failed_response(exc, category), estimated_context_tokens
                if on_status:
                    on_status({
                        "type": "context_overflow_recovering",
                        "category": category,
                        "attempt": attempts,
                    })
                keep_tokens = max(
                    1,
                    min(
                        getattr(agent, "compression_keep_tokens", 1),
                        getattr(agent, "compression_target_tokens", 1),
                    ),
                )
                compaction_result = _call_compress_messages(
                    force=True,
                    keep_tokens=keep_tokens,
                )
                if not isinstance(compaction_result, dict) or not compaction_result.get("compressed"):
                    return _context_recovery_failed_response(exc, category), estimated_context_tokens
                if callable(checkpoint_conversation):
                    checkpoint_conversation()
                api_messages, estimated_context_tokens = _prepare_api_messages(tools)

    on_delta.state = {"in_reasoning": False}

    for _ in range(agent.max_iterations):
        tools = agent.tools.get_definitions()
        task_context = ""
        if task_manager is not None:
            try:
                task_context = task_manager.prompt_context()
            except Exception:
                task_context = ""
        turn_context.system_prompt = getattr(agent, "system_prompt", "")
        turn_context.task_context = task_context
        api_messages, estimated_context_tokens = _prepare_api_messages(tools)
        turn_context.estimated_context_tokens = estimated_context_tokens
        response, estimated_context_tokens = _call_llm_with_recovery(
            api_messages,
            tools,
            estimated_context_tokens,
        )
        turn_context.estimated_context_tokens = estimated_context_tokens
        agent.count_tokens(response["usage"])
        update_current_context = getattr(agent, "update_current_context", None)
        if callable(update_current_context):
            update_current_context(
                response["usage"].get("input", 0),
                estimated_tokens=estimated_context_tokens,
            )

        if response["tool_calls"]:
            agent.messages.append(
                {
                    "role": "assistant",
                    "content": response["content"],
                    "tool_calls": response["tool_calls"],
                }
            )
            if callable(checkpoint_conversation):
                checkpoint_conversation()
            for tc in response["tool_calls"]:
                tc_id, name, result = _exec_tool(tc)
                if on_status:
                    summary = summarize_tool_result(result)
                    on_status({
                        "type": "tool_result",
                        "name": name,
                        "text": summary["summary"],
                        "success": summary["success"],
                    })
                agent.messages.append({"role": "tool", "content": result, "tool_call_id": tc_id})
                if callable(checkpoint_conversation):
                    checkpoint_conversation()
                if name in ("update_plan", "resolve_task_execution") and on_status:
                    task_status = getattr(agent, "task_status", None)
                    on_status({
                        "type": "plan_updated",
                        "task": task_status() if callable(task_status) else None,
                    })
            continue

        final_text = response["content"] or ""
        agent.messages.append({"role": "assistant", "content": final_text})
        if callable(checkpoint_conversation):
            checkpoint_conversation()
        skill_suggestion = getattr(agent, "skill_suggestion_for_turn", None)
        if callable(skill_suggestion):
            try:
                suggestion = skill_suggestion(
                    user_message,
                    final_text,
                    turn_start_index=turn_start_index,
                )
            except Exception:
                suggestion = None
            if suggestion and on_status:
                on_status({
                    "type": "skill_suggestion",
                    "title": suggestion.get("title", ""),
                    "reason": suggestion.get("reason", ""),
                    "text": suggestion.get("text", ""),
                })
        if _compact_if_needed(
            _estimate_persistent_history_tokens(),
            phase="post_turn",
            recompute_tokens=_estimate_persistent_history_tokens,
        ) and callable(checkpoint_conversation):
            checkpoint_conversation()
        schedule_maintenance = getattr(agent, "schedule_post_turn_maintenance", None)
        if callable(schedule_maintenance):
            try:
                schedule_maintenance(
                    user_message,
                    final_text,
                    messages_snapshot=list(agent.messages),
                    on_status=on_status,
                )
            except Exception:
                pass
        else:
            if memory_manager is not None:
                try:
                    memory_manager.sync_turn(
                        user_message,
                        final_text,
                        metadata={
                            "conversation_id": getattr(agent, "conv_id", None),
                            "model": getattr(agent, "model", ""),
                            "workspace": getattr(agent, "workspace", ""),
                        },
                    )
                except Exception:
                    pass
            review_due = getattr(agent, "memory_review_due", None)
            review_memory = getattr(agent, "review_recent_memory", None)
            if callable(review_due) and callable(review_memory) and review_due():
                if on_status:
                    on_status({"type": "memory_check"})
                memory_result = review_memory()
                saved = memory_result.get("saved", [])
                if on_status and saved:
                    on_status({"type": "memory_saved", "count": len(saved)})
        return final_text

    return "已达到最大迭代次数，未能得到最终回答。"
