from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess

from .path_context import resolve_workspace_path
from .registry import registry


POWERSHELL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "要执行的 PowerShell 命令",
        },
        "cwd": {
            "type": "string",
            "description": "命令工作目录；不传时使用 Sierra 当前工作区",
        },
        "timeout": {
            "type": "integer",
            "description": "超时秒数，默认 30，范围 1-120",
        },
    },
    "required": ["command"],
}

MAX_OUTPUT_CHARS = 12000


def powershell(command: str, cwd: str | None = None, timeout: int = 30) -> str:
    if not command.strip():
        return json.dumps({"error": "PowerShell 命令不能为空"}, ensure_ascii=False)

    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        return json.dumps({"error": "未找到 pwsh 或 powershell"}, ensure_ascii=False)

    workdir = resolve_workspace_path(cwd or ".")
    if not os.path.isdir(workdir):
        return json.dumps({"error": f"工作目录不存在: {workdir}"}, ensure_ascii=False)

    timeout_seconds = min(max(int(timeout), 1), 120)
    script = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        "$OutputEncoding = [Console]::OutputEncoding\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        f"{command}\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-InputFormat",
                "Text",
                "-OutputFormat",
                "Text",
                "-EncodedCommand",
                encoded,
            ],
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=creation_flags,
            check=False,
        )
        return json.dumps(
            {
                "cwd": workdir,
                "exit_code": completed.returncode,
                "stdout": _truncate(completed.stdout),
                "stderr": _truncate(completed.stderr),
                "timed_out": False,
            },
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired as exc:
        return json.dumps(
            {
                "cwd": workdir,
                "error": f"PowerShell 命令执行超过 {timeout_seconds} 秒",
                "stdout": _truncate(_decode_timeout_output(exc.stdout)),
                "stderr": _truncate(_decode_timeout_output(exc.stderr)),
                "timed_out": True,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + f"\n... output truncated ({len(value)} chars total)"


registry.register(
    name="powershell",
    description=(
        "在当前工作区执行非交互 PowerShell 命令。用于没有专用工具的本地操作，"
        "例如删除、移动或重命名文件，运行脚本、Git 和系统命令；"
        "返回退出码、stdout 和 stderr。"
        "该工具属于高风险操作，每次执行都需要用户确认。"
    ),
    parameters=POWERSHELL_SCHEMA,
    handler=powershell,
)
