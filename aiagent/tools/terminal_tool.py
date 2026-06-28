from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from .path_context import resolve_workspace_path
from .registry import registry


TERMINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "PowerShell command to execute in the workspace.",
        },
        "background": {
            "type": "boolean",
            "description": "Run command in the background and return a process session id.",
        },
        "timeout": {
            "type": "integer",
            "minimum": 1,
            "maximum": 300,
            "description": "Foreground timeout in seconds. Defaults to 30.",
        },
        "workdir": {
            "type": "string",
            "description": "Working directory. Relative paths resolve under the user workspace.",
        },
    },
    "required": ["command"],
}

PROCESS_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "poll", "log", "wait", "kill"],
            "description": "Process action.",
        },
        "session_id": {
            "type": "string",
            "description": "Background process session id.",
        },
        "offset": {
            "type": "integer",
            "minimum": 0,
            "description": "Log line offset for action=log.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "description": "Maximum log lines to return.",
        },
        "timeout": {
            "type": "integer",
            "minimum": 1,
            "maximum": 300,
            "description": "Seconds to wait for action=wait.",
        },
    },
    "required": ["action"],
}

MAX_OUTPUT_CHARS = 50_000
MAX_BUFFER_LINES = 10_000


@dataclass
class ProcessSession:
    id: str
    command: str
    cwd: str
    started_at: float
    process: subprocess.Popen | None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_BUFFER_LINES))
    lock: threading.Lock = field(default_factory=threading.Lock)
    exited_at: float | None = None
    exit_code: int | None = None
    reader_done: bool = False


class ProcessRegistry:
    def __init__(self):
        self._sessions: dict[str, ProcessSession] = {}
        self._lock = threading.Lock()

    def spawn(self, command: str, cwd: str) -> dict:
        executable = _powershell_executable()
        if not executable:
            return {"error": "pwsh or powershell not found"}
        session_id = "proc-" + uuid.uuid4().hex[:12]
        script = _build_script(command)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
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
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
        except Exception as exc:
            return {"error": str(exc)}

        session = ProcessSession(
            id=session_id,
            command=command,
            cwd=cwd,
            started_at=time.time(),
            process=process,
        )
        with self._lock:
            self._sessions[session_id] = session
        thread = threading.Thread(
            target=self._read_output,
            args=(session,),
            name=f"sierra-process-{session_id}",
            daemon=True,
        )
        thread.start()
        return {
            "session_id": session_id,
            "status": "running",
            "cwd": cwd,
            "pid": process.pid,
        }

    def list(self) -> list[dict]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [self._snapshot(session, include_output=False) for session in sessions]

    def poll(self, session_id: str) -> dict:
        session = self._get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process with id {session_id}"}
        self._refresh_exit(session)
        return self._snapshot(session, include_output=True)

    def log(self, session_id: str, offset: int = 0, limit: int = 200) -> dict:
        session = self._get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process with id {session_id}"}
        offset = max(0, _coerce_int(offset, 0))
        limit = min(max(_coerce_int(limit, 200), 1), 1000)
        with session.lock:
            lines = list(session.lines)
        selected = lines[offset:offset + limit]
        next_offset = offset + len(selected)
        return {
            "status": self._status(session),
            "session_id": session.id,
            "offset": offset,
            "limit": limit,
            "lines": selected,
            "total_lines": len(lines),
            "has_more": next_offset < len(lines),
            "next_offset": next_offset if next_offset < len(lines) else None,
        }

    def wait(self, session_id: str, timeout: int = 30) -> dict:
        session = self._get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process with id {session_id}"}
        timeout = min(max(_coerce_int(timeout, 30), 1), 300)
        process = session.process
        if process is None:
            return self.poll(session_id)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "session_id": session.id,
                "running": True,
                "timeout": timeout,
            }
        self._refresh_exit(session)
        deadline = time.time() + 1.0
        while not session.reader_done and time.time() < deadline:
            time.sleep(0.02)
        return self._snapshot(session, include_output=True)

    def kill(self, session_id: str) -> dict:
        session = self._get(session_id)
        if session is None:
            return {"status": "not_found", "error": f"No process with id {session_id}"}
        process = session.process
        if process is None or process.poll() is not None:
            self._refresh_exit(session)
            return self._snapshot(session, include_output=True)
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "session_id": session.id}
        self._refresh_exit(session)
        return self._snapshot(session, include_output=True)

    def _get(self, session_id: str) -> ProcessSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def _read_output(self, session: ProcessSession) -> None:
        process = session.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                with session.lock:
                    session.lines.append(line.rstrip("\r\n"))
        finally:
            self._refresh_exit(session)
            session.reader_done = True

    def _refresh_exit(self, session: ProcessSession) -> None:
        process = session.process
        if process is None:
            return
        code = process.poll()
        if code is not None and session.exit_code is None:
            session.exit_code = code
            session.exited_at = time.time()

    def _status(self, session: ProcessSession) -> str:
        self._refresh_exit(session)
        return "exited" if session.exit_code is not None else "running"

    def _snapshot(self, session: ProcessSession, *, include_output: bool) -> dict:
        self._refresh_exit(session)
        payload = {
            "session_id": session.id,
            "status": self._status(session),
            "command": session.command,
            "cwd": session.cwd,
            "started_at": session.started_at,
            "exit_code": session.exit_code,
        }
        if session.exited_at is not None:
            payload["exited_at"] = session.exited_at
        if include_output:
            with session.lock:
                output = "\n".join(session.lines)
            payload["output"] = _truncate(output)
            payload["total_lines"] = len(session.lines)
        return payload


process_registry = ProcessRegistry()


def terminal(
    command: str,
    background: bool = False,
    timeout: int = 30,
    workdir: str | None = None,
) -> str:
    command = str(command or "").strip()
    if not command:
        return json.dumps({"error": "command is required"}, ensure_ascii=False)
    cwd = resolve_workspace_path(workdir or ".")
    if not os.path.isdir(cwd):
        return json.dumps({"error": f"workdir does not exist: {cwd}"}, ensure_ascii=False)
    if background:
        return json.dumps(process_registry.spawn(command, cwd), ensure_ascii=False)
    return _run_foreground(command, cwd, timeout)


def process(
    action: str,
    session_id: str = "",
    offset: int = 0,
    limit: int = 200,
    timeout: int = 30,
) -> str:
    action = str(action or "").strip().lower()
    if action == "list":
        return json.dumps({"processes": process_registry.list()}, ensure_ascii=False)
    if not session_id:
        return json.dumps({"error": f"session_id is required for {action}"}, ensure_ascii=False)
    if action == "poll":
        return json.dumps(process_registry.poll(session_id), ensure_ascii=False)
    if action == "log":
        return json.dumps(process_registry.log(session_id, offset, limit), ensure_ascii=False)
    if action == "wait":
        return json.dumps(process_registry.wait(session_id, timeout), ensure_ascii=False)
    if action == "kill":
        return json.dumps(process_registry.kill(session_id), ensure_ascii=False)
    return json.dumps({"error": f"unknown process action: {action}"}, ensure_ascii=False)


def _run_foreground(command: str, cwd: str, timeout: int) -> str:
    executable = _powershell_executable()
    if not executable:
        return json.dumps({"error": "pwsh or powershell not found"}, ensure_ascii=False)
    timeout = min(max(_coerce_int(timeout, 30), 1), 300)
    encoded = base64.b64encode(_build_script(command).encode("utf-16-le")).decode("ascii")
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
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creation_flags,
            check=False,
        )
        return json.dumps(
            {
                "cwd": cwd,
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
                "cwd": cwd,
                "error": f"command exceeded {timeout} seconds",
                "stdout": _truncate(_decode_timeout_output(exc.stdout)),
                "stderr": _truncate(_decode_timeout_output(exc.stderr)),
                "timed_out": True,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _powershell_executable() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _build_script(command: str) -> str:
    return (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
        "$OutputEncoding = [Console]::OutputEncoding\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        f"{command}\n"
    )


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
    name="terminal",
    description=(
        "Run a PowerShell command in the current workspace. Supports foreground commands "
        "and background processes. Prefer dedicated file tools for file edits."
    ),
    parameters=TERMINAL_SCHEMA,
    handler=terminal,
    toolset="terminal",
    max_result_size_chars=100_000,
)

registry.register(
    name="process",
    description="Manage background terminal processes: list, poll, log, wait, or kill.",
    parameters=PROCESS_SCHEMA,
    handler=process,
    toolset="terminal",
    max_result_size_chars=100_000,
)
