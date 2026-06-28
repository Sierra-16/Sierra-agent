from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from .path_context import resolve_workspace_path
from .registry import registry


EXECUTE_CODE_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "Python code to run in a separate process.",
        },
        "timeout": {
            "type": "integer",
            "minimum": 1,
            "maximum": 300,
            "description": "Timeout in seconds. Defaults to 60.",
        },
        "workdir": {
            "type": "string",
            "description": "Working directory. Relative paths resolve under the user workspace.",
        },
        "keep_script": {
            "type": "boolean",
            "description": "Keep the generated script file for debugging.",
        },
    },
    "required": ["code"],
}

MAX_OUTPUT_CHARS = 100_000


def execute_code(
    code: str,
    timeout: int = 60,
    workdir: str | None = None,
    keep_script: bool = False,
) -> str:
    code = str(code or "")
    if not code.strip():
        return json.dumps({"error": "code is required"}, ensure_ascii=False)

    cwd = resolve_workspace_path(workdir or ".")
    if not os.path.isdir(cwd):
        return json.dumps({"error": f"workdir does not exist: {cwd}"}, ensure_ascii=False)

    timeout = min(max(_coerce_int(timeout, 60), 1), 300)
    script_dir = Path(tempfile.gettempdir()) / "sierra-code-exec"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / f"exec-{uuid.uuid4().hex}.py"
    script_path.write_text(code, encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        result = {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "cwd": cwd,
            "stdout": _truncate(completed.stdout),
            "stderr": _truncate(completed.stderr),
            "timed_out": False,
            "duration_ms": round((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "ok": False,
            "exit_code": None,
            "cwd": cwd,
            "stdout": _truncate(_decode_timeout_output(exc.stdout)),
            "stderr": _truncate(_decode_timeout_output(exc.stderr)),
            "timed_out": True,
            "error": f"code execution exceeded {timeout} seconds",
            "duration_ms": round((time.time() - started) * 1000),
        }
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "cwd": cwd,
            "duration_ms": round((time.time() - started) * 1000),
        }
    finally:
        if not keep_script:
            try:
                script_path.unlink()
            except OSError:
                pass

    if keep_script:
        result["script_path"] = str(script_path)
    return json.dumps(result, ensure_ascii=False)


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


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


registry.register(
    name="execute_code",
    description=(
        "Run Python code in a separate process inside the current workspace. "
        "Use this for data processing, parsing, calculations, and multi-step local inspection."
    ),
    parameters=EXECUTE_CODE_SCHEMA,
    handler=execute_code,
    toolset="code_execution",
    max_result_size_chars=100_000,
)
