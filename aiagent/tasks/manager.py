from __future__ import annotations

import json
import os
import uuid
from typing import Any

from ..safety import sanitize_text
from .store import STEP_STATUSES, TaskCheckpointStore


UPDATE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {
            "type": "string",
            "description": "当前任务的明确目标",
        },
        "explanation": {
            "type": "string",
            "description": "这次更新计划的简短原因，可省略",
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "已有步骤的稳定 ID；首次创建可以省略",
                    },
                    "step": {"type": "string", "description": "可验证的任务步骤"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                    },
                    "note": {
                        "type": "string",
                        "description": "结果、阻塞原因或必要说明，可省略",
                    },
                },
                "required": ["step", "status"],
            },
        },
    },
    "required": ["objective", "steps"],
}

RESOLVE_EXECUTION_SCHEMA = {
    "type": "object",
    "properties": {
        "execution_id": {
            "type": "string",
            "description": "uncertain 工具调用的 execution ID",
        },
        "resolution": {
            "type": "string",
            "enum": ["completed", "failed"],
            "description": "只读验证后的实际结果",
        },
        "note": {
            "type": "string",
            "description": "验证依据或用户确认结果",
        },
    },
    "required": ["execution_id", "resolution", "note"],
}


class TaskManager:
    def __init__(self, store: TaskCheckpointStore, workspace: str):
        self.store = store
        self.workspace = os.path.abspath(workspace or ".")
        self.conversation_id = ""
        self.active_task_id: str | None = None
        self.store.mark_interrupted(self.workspace)

    def register_tools(self, registry) -> None:
        registry.register(
            name="update_plan",
            description=(
                "创建或更新多步骤任务计划。仅用于需要多个可验证步骤的复杂任务；"
                "简单问题不要创建计划。开始步骤前设为 in_progress，完成后立即更新为 completed，"
                "同一时间最多一个 in_progress。"
            ),
            parameters=UPDATE_PLAN_SCHEMA,
            handler=self.update_plan,
        )
        registry.register(
            name="get_plan",
            description="读取当前任务计划、步骤进度和中断时结果不确定的工具调用。",
            parameters={"type": "object", "properties": {}},
            handler=self.get_plan_tool,
        )
        registry.register(
            name="resolve_task_execution",
            description=(
                "仅在中断恢复后使用：先通过只读检查或用户确认，"
                "再把结果不确定的工具调用标记为 completed 或 failed。"
                "该工具只更新检查点，不会重新执行原工具。"
            ),
            parameters=RESOLVE_EXECUTION_SCHEMA,
            handler=self.resolve_execution,
        )

    def bind_conversation(self, conversation_id: str | None) -> None:
        self.conversation_id = str(conversation_id or "")
        if not self.conversation_id:
            self.active_task_id = None
            return
        task = self.store.latest_task(
            self.workspace,
            conversation_id=self.conversation_id,
            statuses=("active",),
        )
        self.active_task_id = task["id"] if task else None

    def update_plan(
        self,
        objective: str,
        steps: list[dict[str, Any]],
        explanation: str = "",
    ) -> str:
        objective = sanitize_text(str(objective or "").strip(), max_length=500)
        explanation = sanitize_text(
            str(explanation or "").strip(),
            max_length=1000,
        )
        normalized_steps = self._validate_steps(steps)
        if not objective:
            return json.dumps({"error": "任务目标不能为空"}, ensure_ascii=False)

        task_id = self.active_task_id or f"task-{uuid.uuid4().hex}"
        task = self.store.update_plan(
            task_id=task_id,
            conversation_id=self.conversation_id,
            workspace=self.workspace,
            objective=objective,
            explanation=explanation,
            steps=normalized_steps,
        )
        self.active_task_id = task_id if task.get("status") == "active" else None
        return json.dumps({"ok": True, "task": task}, ensure_ascii=False)

    def _validate_steps(self, steps: Any) -> list[dict[str, str]]:
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise ValueError("计划必须包含 1-20 个步骤")
        normalized = []
        in_progress_count = 0
        for index, item in enumerate(steps, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"步骤 #{index} 必须是对象")
            text = str(item.get("step") or "").strip()
            status = str(item.get("status") or "").strip()
            if not text:
                raise ValueError(f"步骤 #{index} 不能为空")
            if status not in STEP_STATUSES:
                raise ValueError(f"步骤 #{index} 状态无效: {status}")
            if status == "in_progress":
                in_progress_count += 1
            normalized.append({
                "id": str(item.get("id") or "").strip(),
                "step": sanitize_text(text, max_length=500),
                "status": status,
                "note": sanitize_text(
                    str(item.get("note") or "").strip(),
                    max_length=1000,
                ),
            })
        if in_progress_count > 1:
            raise ValueError("同一时间最多只能有一个 in_progress 步骤")
        return normalized

    def get_plan_tool(self) -> str:
        task = self.current_task()
        return json.dumps(
            {"task": task, "message": "当前没有任务计划" if not task else ""},
            ensure_ascii=False,
        )

    def current_task(self) -> dict[str, Any] | None:
        if self.active_task_id:
            task = self.store.get_task(self.active_task_id)
            if task:
                return task
        if self.conversation_id:
            return self.store.latest_task(
                self.workspace,
                conversation_id=self.conversation_id,
            )
        return None

    def recovery_task(self, task_id: str | None = None) -> dict[str, Any] | None:
        if task_id:
            task = self.store.get_task(task_id)
            if (
                task
                and task.get("workspace") == self.workspace
                and task.get("status") == "interrupted"
            ):
                return task
            return None
        return self.store.latest_task(
            self.workspace,
            conversation_id=self.conversation_id or None,
            statuses=("interrupted",),
        )

    def resume(self, task_id: str) -> dict[str, Any]:
        task = self.recovery_task(task_id)
        if not task:
            return {"ok": False, "error": "没有找到可恢复的中断任务"}
        task = self.store.set_task_status(task_id, "active") or task
        self.active_task_id = task_id
        self.conversation_id = task.get("conversation_id", self.conversation_id)
        return {"ok": True, "task": task}

    def abandon(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if not task or task.get("workspace") != self.workspace:
            return {"ok": False, "error": "没有找到该任务"}
        task = self.store.set_task_status(task_id, "cancelled") or task
        if self.active_task_id == task_id:
            self.active_task_id = None
        return {"ok": True, "task": task}

    def pause_active(self) -> dict[str, Any] | None:
        if not self.active_task_id:
            return None
        task_id = self.active_task_id
        self.active_task_id = None
        return self.store.set_task_status(task_id, "interrupted")

    def start_tool_execution(
        self,
        tool_call_id: str,
        tool_name: str,
        risk: str,
        arguments: str,
    ) -> str | None:
        task = self.current_task()
        if not task or task.get("status") != "active":
            return None
        return self.store.start_execution(
            task_id=task["id"],
            step_id=task.get("current_step_id"),
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            risk=risk,
            arguments=arguments,
        )

    def finish_tool_execution(
        self,
        execution_id: str | None,
        success: bool,
        result_summary: str,
    ) -> None:
        if not execution_id:
            return
        self.store.finish_execution(
            execution_id,
            "completed" if success else "failed",
            result_summary=result_summary[:1000],
        )

    def resolve_execution(
        self,
        execution_id: str,
        resolution: str,
        note: str,
    ) -> str:
        execution = self.store.get_execution(str(execution_id or ""))
        if not execution or execution.get("status") != "uncertain":
            return json.dumps({
                "error": "没有找到该 uncertain 工具检查点",
            }, ensure_ascii=False)
        task = self.store.get_task(execution["task_id"])
        if not task or task.get("workspace") != self.workspace:
            return json.dumps({"error": "该检查点不属于当前工作区"}, ensure_ascii=False)
        if resolution not in ("completed", "failed"):
            return json.dumps({"error": "resolution 必须是 completed 或 failed"}, ensure_ascii=False)
        note = sanitize_text(str(note or "").strip(), max_length=1000)
        if not note:
            return json.dumps({"error": "必须提供验证依据"}, ensure_ascii=False)
        self.store.finish_execution(
            execution["id"],
            resolution,
            result_summary=note,
        )
        return json.dumps({
            "ok": True,
            "execution_id": execution["id"],
            "resolution": resolution,
            "task": self.store.get_task(execution["task_id"]),
        }, ensure_ascii=False)

    def prompt_context(self) -> str:
        task = self.current_task()
        if not task or task.get("status") not in ("active", "interrupted"):
            return ""
        lines = [
            "<task-plan>",
            "[系统说明：这是当前任务的持久化进度，不是用户的新指令。]",
            f"目标: {_escape_context(task['objective'])}",
            f"状态: {_escape_context(task['status'])}",
        ]
        for step in task.get("steps", []):
            note = (
                f" | {_escape_context(step['note'])}"
                if step.get("note")
                else ""
            )
            lines.append(
                f"- [{_escape_context(step['status'])}] "
                f"{_escape_context(step['id'])}: {_escape_context(step['step'])}{note}"
            )
        if task.get("uncertain_executions"):
            lines.append("中断时结果不确定的工具调用（恢复后先验证或询问，不要直接重跑）:")
            for execution in task["uncertain_executions"]:
                lines.append(
                    f"- {_escape_context(execution['tool_name'])} "
                    f"call={_escape_context(execution['tool_call_id'])} "
                    f"risk={_escape_context(execution['risk'])}"
                )
        lines.append("</task-plan>")
        return "\n".join(lines)[:8000]

    def close(self, preserve_active: bool = False) -> None:
        if not preserve_active:
            self.pause_active()
        self.store.close()


def _escape_context(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
