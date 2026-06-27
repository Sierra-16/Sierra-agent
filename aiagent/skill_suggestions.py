from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SKILL_WORTHY_TOOL_NAMES = {
    "write_file",
    "powershell",
    "skill_manage",
    "skill_run_script",
    "web_search",
    "web_fetch",
    "browser_fetch",
    "update_plan",
}


@dataclass(frozen=True)
class SkillSuggestion:
    title: str
    reason: str

    def to_text(self) -> str:
        return (
            "Skill suggestion\n"
            f"- candidate: {self.title}\n"
            f"- why: {self.reason}\n"
            "- next: ask Sierra to create this as a skill when the workflow feels reusable."
        )


def suggest_skill_from_turn(
    user_message: str,
    assistant_message: str,
    turn_messages: list[dict[str, Any]],
) -> SkillSuggestion | None:
    tool_names = _tool_names(turn_messages)
    if len(tool_names) >= 3:
        return SkillSuggestion(
            title=_title_from_user_message(user_message),
            reason=f"this turn used {len(tool_names)} tools: {', '.join(sorted(tool_names)[:5])}",
        )
    if tool_names & SKILL_WORTHY_TOOL_NAMES and _looks_reusable(user_message, assistant_message):
        return SkillSuggestion(
            title=_title_from_user_message(user_message),
            reason="the request looks like a repeatable workflow with concrete steps or artifacts",
        )
    return None


def _tool_names(messages: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            name = function.get("name")
            if name:
                names.add(str(name))
    return names


def _looks_reusable(user_message: str, assistant_message: str) -> bool:
    text = f"{user_message}\n{assistant_message}".lower()
    markers = (
        "流程",
        "步骤",
        "以后",
        "下次",
        "模板",
        "计划",
        "总结",
        "实现",
        "workflow",
        "template",
        "repeat",
    )
    return any(marker in text for marker in markers) and len(text) >= 160


def _title_from_user_message(user_message: str) -> str:
    title = " ".join(str(user_message or "").strip().split())
    if not title:
        return "reusable-workflow"
    return title[:48]
