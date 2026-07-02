from __future__ import annotations

import contextlib
import io
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..safety import sanitize_text


GatewayEmit = Callable[[dict[str, Any]], None]
GatewayInputReader = Callable[[str, str], dict[str, Any] | None]


@dataclass
class GatewayChatResult:
    answer: str
    usage: dict[str, Any]
    interrupted: bool = False

    def done_event(self) -> dict[str, Any]:
        return {
            "type": "done",
            "answer": self.answer,
            "text": self.answer,
            "usage": self.usage,
            "interrupted": self.interrupted,
        }


def sanitize_gateway_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    safe_event: dict[str, Any] = {}
    for key, value in event.items():
        if isinstance(value, str):
            safe_event[key] = sanitize_text(value, max_length=1200)
        else:
            safe_event[key] = value
    return safe_event


class GatewayInterrupted(Exception):
    """Raised inside adapter callbacks when the active web/TUI turn is cancelled."""


class GatewayRuntime:
    """Shared runtime used by Web/TUI adapters.

    The runtime owns cross-interface concerns: one chat turn at a time,
    pending tool approvals, pending user-input requests, and terminal-output
    suppression for UI transports.
    """

    def __init__(
        self,
        agent: Any,
        *,
        config: dict[str, Any] | None = None,
        config_path: str | Path | None = None,
        make_agent: Callable[[str], Any] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._agent = agent
        self.config = config or {}
        self.config_path = Path(config_path).resolve() if config_path else None
        self.make_agent = make_agent
        self.chat_lock = threading.Lock()
        self.approval_lock = threading.Lock()
        self.pending_approvals: dict[str, dict[str, Any]] = {}
        self.input_lock = threading.Lock()
        self.pending_inputs: dict[str, dict[str, Any]] = {}
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self.cancel_lock = threading.Lock()
        self.active_cancel_event: threading.Event | None = None

    @property
    def agent(self) -> Any:
        return self._agent

    def set_agent(self, agent: Any) -> None:
        self._agent = agent

    def request_id(self, prefix: str) -> str:
        return f"{prefix}-{self.id_factory()[:12]}"

    def chat(
        self,
        message: str,
        *,
        emit: GatewayEmit | None = None,
        interaction: str = "interactive",
        input_reader: GatewayInputReader | None = None,
        suppress_output: bool = True,
        approval_timeout: float = 300.0,
        input_timeout: float = 600.0,
    ) -> GatewayChatResult:
        message = sanitize_text(str(message or "").strip(), max_length=12000)
        emit_safe = self._safe_emitter(emit)
        cancel_event = threading.Event()

        def ensure_not_cancelled() -> None:
            if cancel_event.is_set():
                raise GatewayInterrupted

        def on_status(event: dict[str, Any]) -> None:
            ensure_not_cancelled()
            emit_safe(event)
            ensure_not_cancelled()

        def on_tool_approval(request: dict[str, Any]) -> str:
            ensure_not_cancelled()
            if interaction == "deny":
                emit_safe({
                    "type": "tool_denied_by_web",
                    "name": request.get("name", "tool"),
                    "risk": request.get("risk", "unknown"),
                })
                return "deny"
            decision = self.request_tool_approval(
                request,
                emit=emit_safe,
                input_reader=input_reader,
                timeout=approval_timeout,
            )
            ensure_not_cancelled()
            return decision

        def on_user_input(request: dict[str, Any]) -> dict[str, Any]:
            ensure_not_cancelled()
            if interaction == "deny":
                emit_safe({
                    "type": "user_input_cancelled_by_web",
                    "question": request.get("question", ""),
                })
                return {"cancelled": True}
            response = self.request_user_input(
                request,
                emit=emit_safe,
                input_reader=input_reader,
                timeout=input_timeout,
            )
            ensure_not_cancelled()
            return response

        output_sink = io.StringIO()
        redirect_context = (
            contextlib.redirect_stdout(output_sink),
            contextlib.redirect_stderr(output_sink),
        )
        with self.chat_lock:
            with self.cancel_lock:
                self.active_cancel_event = cancel_event
            try:
                ensure_not_cancelled()
                if suppress_output:
                    with redirect_context[0], redirect_context[1]:
                        answer = self._agent.chat(
                            message,
                            on_status=on_status,
                            on_tool_approval=on_tool_approval,
                            on_user_input=on_user_input,
                        )
                else:
                    answer = self._agent.chat(
                        message,
                        on_status=on_status,
                        on_tool_approval=on_tool_approval,
                        on_user_input=on_user_input,
                    )
                usage = self.usage_payload()
                return GatewayChatResult(
                    answer=sanitize_text(str(answer or ""), max_length=24000),
                    usage=usage,
                )
            except GatewayInterrupted:
                usage = self.usage_payload()
                emit_safe({
                    "type": "interrupted",
                    "text": "Interrupted by user.",
                })
                return GatewayChatResult(answer="", usage=usage, interrupted=True)
            finally:
                with self.cancel_lock:
                    if self.active_cancel_event is cancel_event:
                        self.active_cancel_event = None

    def request_tool_approval(
        self,
        request: dict[str, Any],
        *,
        emit: GatewayEmit,
        input_reader: GatewayInputReader | None = None,
        timeout: float = 300.0,
    ) -> str:
        approval_id = self.request_id("tool")
        waiter = {
            "event": threading.Event(),
            "decision": "deny",
        }
        with self.approval_lock:
            self.pending_approvals[approval_id] = waiter
        emit({
            "type": "tool_approval_request",
            "id": approval_id,
            "name": sanitize_text(str(request.get("name", "tool")), max_length=120),
            "risk": sanitize_text(str(request.get("risk", "unknown")), max_length=80),
            "reason": sanitize_text(str(request.get("reason", "")), max_length=1000),
            "arguments": request.get("arguments", {}),
        })

        if input_reader is not None:
            response = input_reader("tool_approval", approval_id) or {}
            if str(response.get("cmd") or "") == "quit":
                self._drop_approval(approval_id)
                raise SystemExit(0)
            decision = normalize_approval_decision(response.get("decision", response.get("approved")))
            answered = True
        else:
            answered = waiter["event"].wait(timeout=timeout)
            decision = str(waiter.get("decision") or "deny") if answered else "deny"

        self._drop_approval(approval_id)
        emit({
            "type": "tool_approval_result",
            "id": approval_id,
            "name": request.get("name", "tool"),
            "decision": decision,
            "approved": decision in {"once", "session"},
            "timed_out": not answered,
        })
        return decision

    def request_user_input(
        self,
        request: dict[str, Any],
        *,
        emit: GatewayEmit,
        input_reader: GatewayInputReader | None = None,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        input_id = self.request_id("input")
        waiter = {
            "event": threading.Event(),
            "response": {"cancelled": True},
        }
        with self.input_lock:
            self.pending_inputs[input_id] = waiter
        emit({
            "type": "user_input_request",
            "id": input_id,
            "question": sanitize_text(str(request.get("question", "")), max_length=1000),
            "options": safe_options(request.get("options")),
            "allow_free_text": bool(request.get("allow_free_text", True)),
        })

        if input_reader is not None:
            response = input_reader("user_input_response", input_id) or {"cancelled": True}
            if str(response.get("cmd") or "") == "quit":
                self._drop_input(input_id)
                raise SystemExit(0)
            answered = True
            response = normalize_user_input_response(response)
        else:
            answered = waiter["event"].wait(timeout=timeout)
            response = dict(waiter.get("response") or {"cancelled": True}) if answered else {"cancelled": True}

        self._drop_input(input_id)
        emit({
            "type": "user_input_result",
            "id": input_id,
            "cancelled": bool(response.get("cancelled")),
            "value": sanitize_text(str(response.get("value", "")), max_length=300),
            "label": sanitize_text(str(response.get("label", "")), max_length=300),
            "free_text": bool(response.get("free_text")),
            "timed_out": not answered,
        })
        return response

    def respond_tool_approval(self, approval_id: str, decision: str | bool) -> dict[str, Any]:
        approval_id = sanitize_text(str(approval_id or "").strip(), max_length=120)
        normalized = normalize_approval_decision(decision)
        with self.approval_lock:
            waiter = self.pending_approvals.get(approval_id)
            if not waiter:
                return {"ok": False, "error": "approval request not found"}
            waiter["decision"] = normalized
            waiter["event"].set()
        return {"ok": True, "id": approval_id, "decision": normalized}

    def respond_user_input(self, input_id: str, response: dict[str, Any]) -> dict[str, Any]:
        input_id = sanitize_text(str(input_id or "").strip(), max_length=120)
        normalized = normalize_user_input_response(response)
        with self.input_lock:
            waiter = self.pending_inputs.get(input_id)
            if not waiter:
                return {"ok": False, "error": "input request not found"}
            waiter["response"] = normalized
            waiter["event"].set()
        return {"ok": True, "id": input_id}

    def cancel_current(self, reason: str = "user") -> dict[str, Any]:
        reason = sanitize_text(str(reason or "user"), max_length=120)
        with self.cancel_lock:
            active = self.active_cancel_event
            active_cancelled = active is not None
            if active is not None:
                active.set()

        released_approvals = 0
        with self.approval_lock:
            for waiter in self.pending_approvals.values():
                waiter["decision"] = "deny"
                waiter["event"].set()
                released_approvals += 1

        released_inputs = 0
        with self.input_lock:
            for waiter in self.pending_inputs.values():
                waiter["response"] = {"cancelled": True, "label": "", "value": "", "free_text": False}
                waiter["event"].set()
                released_inputs += 1

        return {
            "ok": True,
            "reason": reason,
            "active_cancelled": active_cancelled,
            "released_approvals": released_approvals,
            "released_inputs": released_inputs,
        }

    def usage_payload(self) -> dict[str, Any]:
        usage_snapshot = getattr(self._agent, "usage_snapshot", None)
        if callable(usage_snapshot):
            usage = dict(usage_snapshot() or {})
        else:
            usage = {
                "input": getattr(self._agent, "total_input_tokens", 0),
                "output": getattr(self._agent, "total_output_tokens", 0),
                "context": getattr(self._agent, "current_context_tokens", 0),
                "context_estimated": getattr(self._agent, "context_tokens_estimated", False),
            }
        usage.setdefault("context", getattr(self._agent, "current_context_tokens", 0))
        usage.setdefault("context_estimated", getattr(self._agent, "context_tokens_estimated", False))
        usage["context_window"] = int(getattr(self._agent, "context_window", 0) or usage.get("context_window") or 0)
        return usage

    def task_status(self) -> dict[str, Any] | None:
        task_status = getattr(self._agent, "task_status", None)
        return task_status() if callable(task_status) else None

    def task_recovery(self, task_id: str | None = None) -> dict[str, Any] | None:
        task_recovery = getattr(self._agent, "task_recovery", None)
        return task_recovery(task_id) if callable(task_recovery) else None

    def cron_due(self) -> list[dict[str, Any]]:
        cron_due = getattr(self._agent, "cron_due", None)
        if not callable(cron_due):
            return []
        try:
            return cron_due()
        except Exception:
            return []

    def auto_save(self) -> None:
        auto_save_agent(self._agent)

    def _safe_emitter(self, emit: GatewayEmit | None) -> GatewayEmit:
        def emit_safe(event: dict[str, Any]) -> None:
            safe_event = sanitize_gateway_event(event)
            if safe_event and emit is not None:
                emit(safe_event)

        return emit_safe

    def _drop_approval(self, approval_id: str) -> None:
        with self.approval_lock:
            self.pending_approvals.pop(approval_id, None)

    def _drop_input(self, input_id: str) -> None:
        with self.input_lock:
            self.pending_inputs.pop(input_id, None)


def normalize_approval_decision(value: Any) -> str:
    if value is True:
        return "once"
    if value is False or value is None:
        return "deny"
    decision = sanitize_text(str(value).strip().lower(), max_length=20)
    if decision in {"allow", "approve", "run", "yes", "true", "y"}:
        return "once"
    if decision in {"reject", "no", "false", "n"}:
        return "deny"
    if decision not in {"once", "session", "deny"}:
        return "deny"
    return decision


def normalize_user_input_response(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {"cancelled": True}
    return {
        "value": sanitize_text(str(response.get("value", "")), max_length=12000),
        "label": sanitize_text(str(response.get("label", "")), max_length=1000),
        "free_text": bool(response.get("free_text")),
        "cancelled": bool(response.get("cancelled")),
    }


def safe_options(value: Any) -> list[dict[str, str]]:
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


def auto_save_agent(agent: Any) -> None:
    if not getattr(agent, "messages", None):
        return
    title = ""
    for message in getattr(agent, "messages", []):
        if message.get("role") == "user":
            title = str(message.get("content", ""))[:30]
            break
    usage_snapshot = getattr(agent, "usage_snapshot", None)
    if callable(usage_snapshot):
        usage = usage_snapshot()
    else:
        usage = {
            "input": getattr(agent, "total_input_tokens", 0),
            "output": getattr(agent, "total_output_tokens", 0),
        }
    save_conversation = getattr(agent, "save_conversation", None)
    if callable(save_conversation):
        save_conversation(usage=usage, title=title)
