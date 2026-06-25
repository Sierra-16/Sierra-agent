from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


LOW_RISK_TOOLS = {
    "calculator",
    "get_time",
    "list_directory",
    "search_files",
    "skills_list",
    "skill_view",
    "skill_render_template",
    "skill_reload",
    "skill_usage_stats",
    "request_user_input",
    "update_plan",
    "get_plan",
    "resolve_task_execution",
}

MEDIUM_RISK_TOOLS = {
    "read_file",
    "web_fetch",
    "web_search",
}

HIGH_RISK_TOOLS = {
    "write_file",
    "save_memory",
    "delete_memory",
    "powershell",
    "skill_run_script",
    "skill_manage",
}

DANGEROUS_KEYWORDS = (
    "delete",
    "remove",
    "rm",
    "write",
    "create",
    "update",
    "patch",
    "edit",
    "move",
    "rename",
    "exec",
    "execute",
    "command",
    "shell",
    "run",
    "upload",
    "send",
    "email",
    "payment",
    "pay",
    "token",
    "credential",
    "secret",
)

READ_KEYWORDS = (
    "read",
    "get",
    "fetch",
    "search",
    "list",
    "query",
)

SENSITIVE_PATH_MARKERS = (
    ".env",
    "config.json",
    "id_rsa",
    "credentials",
    "credential",
    "secret",
    "token",
    "key",
)

SENSITIVE_ARG_KEYS = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "credential",
    "content",
)


@dataclass(frozen=True)
class ToolRisk:
    level: str
    reason: str

    @property
    def requires_approval(self) -> bool:
        return self.level in ("medium", "high")


class SafetyGate:
    """Classify tool calls before execution."""

    def assess(self, name: str, arguments: dict[str, Any] | None = None) -> ToolRisk:
        arguments = arguments or {}
        normalized = name.lower()

        if normalized.startswith("mcp__"):
            return self._assess_mcp(normalized)

        if normalized == "powershell":
            return ToolRisk("high", "该工具会执行任意 PowerShell 命令并可能修改系统状态")

        if normalized in HIGH_RISK_TOOLS:
            return ToolRisk("high", "该工具会修改本地状态、文件或长期记忆")

        if normalized == "read_file" and self._reads_sensitive_path(arguments):
            return ToolRisk("high", "该读取目标可能包含密钥、配置或凭证")

        if normalized in MEDIUM_RISK_TOOLS:
            return ToolRisk("medium", "该工具会读取文件、访问网络或暴露外部信息")

        if normalized in LOW_RISK_TOOLS:
            return ToolRisk("low", "只读或本地低风险工具")

        if any(keyword in normalized for keyword in DANGEROUS_KEYWORDS):
            return ToolRisk("high", "工具名包含写入、删除、执行或发送类高风险动作")

        if any(keyword in normalized for keyword in READ_KEYWORDS):
            return ToolRisk("medium", "未知只读类工具，执行前需要确认")

        return ToolRisk("medium", "未知工具，执行前需要确认")

    def _assess_mcp(self, normalized_name: str) -> ToolRisk:
        if any(keyword in normalized_name for keyword in DANGEROUS_KEYWORDS):
            return ToolRisk("high", "外部 MCP 工具可能执行写入、删除、命令或发送操作")

        if any(keyword in normalized_name for keyword in READ_KEYWORDS):
            return ToolRisk("medium", "外部 MCP 工具会读取或查询信息")

        return ToolRisk("medium", "外部 MCP 工具能力未知")

    def _reads_sensitive_path(self, arguments: dict[str, Any]) -> bool:
        path = str(arguments.get("file_path") or arguments.get("path") or "")
        lowered = os.path.basename(path).lower()
        full = path.lower()
        return any(marker in lowered or marker in full for marker in SENSITIVE_PATH_MARKERS)


def sanitize_arguments(arguments: dict[str, Any] | None, max_length: int = 500) -> str:
    """Return a short, redacted JSON string for user confirmation UI."""
    if not isinstance(arguments, dict):
        return "{}"

    redacted = {
        key: _redact_value(key, value)
        for key, value in arguments.items()
    }
    text = json.dumps(redacted, ensure_ascii=False, indent=2)
    if len(text) > max_length:
        return text[:max_length] + "\n..."
    return text


def _redact_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in SENSITIVE_ARG_KEYS):
        value_text = str(value)
        if len(value_text) <= 80 and lowered not in ("content",):
            return "***"
        return f"*** redacted ({len(value_text)} chars) ***"

    if isinstance(value, dict):
        return {nested_key: _redact_value(str(nested_key), nested_value) for nested_key, nested_value in value.items()}

    if isinstance(value, list):
        return [_redact_value(key, item) for item in value[:20]]

    value_text = sanitize_text(str(value))
    if len(value_text) > 300:
        return value_text[:300] + "..."
    return value_text if isinstance(value, str) else value


def sanitize_text(value: str, max_length: int | None = None) -> str:
    patterns = (
        (r"(?i)(bearer\s+)[a-z0-9._~+/=-]+", r"\1***"),
        (
            r"(?i)((?:api[\s_-]*key|token|password|secret)\s*[:=]\s*)[^\s;,\"']+",
            r"\1***",
        ),
        (r"\bsk-[a-zA-Z0-9_-]{8,}\b", "sk-***"),
    )
    sanitized = value
    for pattern, replacement in patterns:
        sanitized = re.sub(pattern, replacement, sanitized)
    if max_length is not None and len(sanitized) > max_length:
        return sanitized[:max_length] + "..."
    return sanitized
