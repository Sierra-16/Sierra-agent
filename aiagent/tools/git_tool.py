from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from .path_context import resolve_workspace_path
from .registry import registry


GIT_INSPECT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "repo",
                "status",
                "diff",
                "staged_diff",
                "log",
                "branches",
                "show",
            ],
            "description": "Read-only git action to run.",
        },
        "workdir": {
            "type": "string",
            "description": "Repository directory. Relative paths resolve under the user workspace.",
        },
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 50,
            "description": "Optional path filters for status, diff, staged_diff, and log.",
        },
        "ref": {
            "type": "string",
            "description": "Optional git revision/range for log or show, such as HEAD, HEAD~1, main..HEAD.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "Maximum commits for action=log. Defaults to 10.",
        },
        "max_chars": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 120000,
            "description": "Maximum output characters returned from verbose actions. Defaults to 50000.",
        },
        "stat_only": {
            "type": "boolean",
            "description": "For diff, staged_diff, and show, return only --stat output.",
        },
    },
    "required": ["action"],
}


DEFAULT_MAX_CHARS = 50_000
MAX_PATHS = 50
GIT_TIMEOUT_SECONDS = 20
_CONTROL_CHARS = set("\r\n\0")


def git_inspect(
    action: str,
    workdir: str | None = None,
    paths: list[str] | None = None,
    ref: str | None = None,
    limit: int = 10,
    max_chars: int = DEFAULT_MAX_CHARS,
    stat_only: bool = False,
) -> str:
    """Run read-only git inspection commands with bounded output."""
    git = shutil.which("git")
    if not git:
        return _json({"ok": False, "error": "git executable not found"})

    action = str(action or "").strip().lower()
    if action not in {
        "repo",
        "status",
        "diff",
        "staged_diff",
        "log",
        "branches",
        "show",
    }:
        return _json({"ok": False, "error": f"Unsupported git action: {action}"})

    cwd = resolve_workspace_path(workdir or ".")
    if not os.path.isdir(cwd):
        return _json({"ok": False, "error": f"Directory not found: {cwd}", "workdir": cwd})

    path_error, safe_paths = _normalize_paths(paths)
    if path_error:
        return _json({"ok": False, "error": path_error, "workdir": cwd})

    ref_error, safe_ref = _normalize_ref(ref)
    if ref_error:
        return _json({"ok": False, "error": ref_error, "workdir": cwd})

    max_chars = _clamp_int(max_chars, DEFAULT_MAX_CHARS, 1000, 120_000)
    limit = _clamp_int(limit, 10, 1, 50)

    repo_info = _repo_info(git, cwd)
    if not repo_info.get("ok"):
        return _json(repo_info)

    if action == "repo":
        return _json(repo_info)
    if action == "status":
        return _run_status(git, cwd, repo_info, safe_paths, max_chars)
    if action == "diff":
        return _run_diff(git, cwd, repo_info, safe_paths, max_chars, staged=False, stat_only=stat_only)
    if action == "staged_diff":
        return _run_diff(git, cwd, repo_info, safe_paths, max_chars, staged=True, stat_only=stat_only)
    if action == "log":
        return _run_log(git, cwd, repo_info, safe_ref, safe_paths, limit, max_chars)
    if action == "branches":
        return _run_branches(git, cwd, repo_info, max_chars)
    if action == "show":
        return _run_show(git, cwd, repo_info, safe_ref, max_chars, stat_only=stat_only)

    return _json({"ok": False, "error": f"Unhandled git action: {action}", "workdir": cwd})


def _repo_info(git: str, cwd: str) -> dict[str, Any]:
    root = _git(git, cwd, ["rev-parse", "--show-toplevel"])
    if root["returncode"] != 0:
        return {
            "ok": False,
            "error": "Not inside a git repository",
            "workdir": cwd,
            "stderr": root["stderr"][:2000],
        }

    branch = _git(git, cwd, ["branch", "--show-current"])
    head = _git(git, cwd, ["rev-parse", "--short", "HEAD"])
    upstream = _git(git, cwd, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    status = _git(git, cwd, ["status", "--porcelain"])
    remote = _git(git, cwd, ["remote", "-v"])

    return {
        "ok": True,
        "workdir": cwd,
        "repo_root": root["stdout"].strip(),
        "branch": branch["stdout"].strip() or None,
        "head": head["stdout"].strip() or None,
        "upstream": upstream["stdout"].strip() if upstream["returncode"] == 0 else None,
        "dirty": bool(status["stdout"].strip()),
        "remote": _unique_remote_lines(remote["stdout"]),
    }


def _run_status(
    git: str,
    cwd: str,
    repo_info: dict[str, Any],
    paths: list[str],
    max_chars: int,
) -> str:
    args = ["status", "--short", "--branch", "--untracked-files=all"]
    args.extend(_pathspec_args(paths))
    result = _git(git, cwd, args)
    text, truncated = _truncate(result["stdout"], max_chars)
    parsed = _parse_short_status(result["stdout"])
    return _json({
        "ok": result["returncode"] == 0,
        "action": "status",
        "repo": _compact_repo(repo_info),
        "path_count": len(paths),
        "summary": parsed["summary"],
        "entries": parsed["entries"][:200],
        "output": text,
        "truncated": truncated,
        "stderr": result["stderr"][:4000],
    })


def _run_diff(
    git: str,
    cwd: str,
    repo_info: dict[str, Any],
    paths: list[str],
    max_chars: int,
    staged: bool,
    stat_only: bool,
) -> str:
    stat_args = ["diff", "--stat"]
    patch_args = ["diff", "--patch", "--find-renames"]
    if staged:
        stat_args.append("--staged")
        patch_args.append("--staged")
    stat_args.extend(_pathspec_args(paths))
    patch_args.extend(_pathspec_args(paths))

    stat = _git(git, cwd, stat_args)
    patch = stat if stat_only else _git(git, cwd, patch_args)
    text, truncated = _truncate(patch["stdout"], max_chars)
    return _json({
        "ok": patch["returncode"] == 0,
        "action": "staged_diff" if staged else "diff",
        "repo": _compact_repo(repo_info),
        "path_count": len(paths),
        "stat": stat["stdout"].strip(),
        "output": text,
        "truncated": truncated,
        "stat_only": bool(stat_only),
        "stderr": (stat["stderr"] + patch["stderr"])[:4000],
    })


def _run_log(
    git: str,
    cwd: str,
    repo_info: dict[str, Any],
    ref: str | None,
    paths: list[str],
    limit: int,
    max_chars: int,
) -> str:
    args = [
        "log",
        f"--max-count={limit}",
        "--date=iso-strict",
        "--pretty=format:%h%x09%H%x09%ad%x09%an%x09%s",
        "--stat",
    ]
    if ref:
        args.append(ref)
    args.extend(_pathspec_args(paths))
    result = _git(git, cwd, args)
    text, truncated = _truncate(result["stdout"], max_chars)
    commits = _parse_log_rows(result["stdout"])
    return _json({
        "ok": result["returncode"] == 0,
        "action": "log",
        "repo": _compact_repo(repo_info),
        "ref": ref,
        "limit": limit,
        "path_count": len(paths),
        "commits": commits,
        "output": text,
        "truncated": truncated,
        "stderr": result["stderr"][:4000],
    })


def _run_branches(git: str, cwd: str, repo_info: dict[str, Any], max_chars: int) -> str:
    result = _git(git, cwd, [
        "branch",
        "--all",
        "--verbose",
        "--no-abbrev",
        "--sort=-committerdate",
    ])
    text, truncated = _truncate(result["stdout"], max_chars)
    return _json({
        "ok": result["returncode"] == 0,
        "action": "branches",
        "repo": _compact_repo(repo_info),
        "output": text,
        "truncated": truncated,
        "stderr": result["stderr"][:4000],
    })


def _run_show(
    git: str,
    cwd: str,
    repo_info: dict[str, Any],
    ref: str | None,
    max_chars: int,
    stat_only: bool,
) -> str:
    safe_ref = ref or "HEAD"
    args = [
        "show",
        "--date=iso-strict",
        "--find-renames",
        "--stat" if stat_only else "--patch",
        safe_ref,
    ]
    result = _git(git, cwd, args)
    text, truncated = _truncate(result["stdout"], max_chars)
    return _json({
        "ok": result["returncode"] == 0,
        "action": "show",
        "repo": _compact_repo(repo_info),
        "ref": safe_ref,
        "output": text,
        "truncated": truncated,
        "stat_only": bool(stat_only),
        "stderr": result["stderr"][:4000],
    })


def _git(git: str, cwd: str, args: list[str]) -> dict[str, Any]:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [git, "-C", cwd, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            creationflags=creation_flags,
            check=False,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": 124,
            "stdout": "",
            "stderr": f"git timed out after {GIT_TIMEOUT_SECONDS}s",
        }
    except Exception as exc:
        return {"returncode": 1, "stdout": "", "stderr": str(exc)}


def _pathspec_args(paths: list[str]) -> list[str]:
    if not paths:
        return []
    return ["--", *paths]


def _normalize_paths(paths: list[str] | None) -> tuple[str | None, list[str]]:
    if not paths:
        return None, []
    if not isinstance(paths, list):
        return "paths must be an array", []
    if len(paths) > MAX_PATHS:
        return f"paths may contain at most {MAX_PATHS} items", []

    normalized: list[str] = []
    for raw in paths:
        path = str(raw or "").strip().replace("\\", "/")
        if not path:
            continue
        if any(char in path for char in _CONTROL_CHARS):
            return "paths must not contain control characters", []
        if os.path.isabs(path) or path.startswith("../") or path == "..":
            return "paths must be relative to the repository", []
        normalized.append(path)
    return None, normalized


def _normalize_ref(ref: str | None) -> tuple[str | None, str | None]:
    if ref is None:
        return None, None
    safe_ref = str(ref).strip()
    if not safe_ref:
        return None, None
    if len(safe_ref) > 200:
        return "ref is too long", None
    if safe_ref.startswith("-"):
        return "ref must not start with '-'", None
    if any(char in safe_ref for char in _CONTROL_CHARS):
        return "ref must not contain control characters", None
    return None, safe_ref


def _parse_short_status(output: str) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    summary = {
        "modified": 0,
        "added": 0,
        "deleted": 0,
        "renamed": 0,
        "copied": 0,
        "untracked": 0,
        "conflicted": 0,
    }

    for line in output.splitlines():
        if not line or line.startswith("##"):
            continue
        code = line[:2]
        path = line[3:] if len(line) > 3 else ""
        entries.append({"code": code, "path": path})
        if code == "??":
            summary["untracked"] += 1
        if "M" in code:
            summary["modified"] += 1
        if "A" in code:
            summary["added"] += 1
        if "D" in code:
            summary["deleted"] += 1
        if "R" in code:
            summary["renamed"] += 1
        if "C" in code:
            summary["copied"] += 1
        if "U" in code:
            summary["conflicted"] += 1

    return {"summary": summary, "entries": entries}


def _parse_log_rows(output: str) -> list[dict[str, str]]:
    commits: list[dict[str, str]] = []
    for line in output.splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5 and _looks_like_hash(parts[0]):
            commits.append({
                "short_hash": parts[0],
                "hash": parts[1],
                "date": parts[2],
                "author": parts[3],
                "subject": parts[4],
            })
    return commits


def _looks_like_hash(value: str) -> bool:
    return bool(value) and all(char in "0123456789abcdefABCDEF" for char in value)


def _unique_remote_lines(output: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for line in output.splitlines():
        line = line.strip()
        if line and line not in seen:
            lines.append(line)
            seen.add(line)
    return lines[:20]


def _compact_repo(repo_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "repo_root": repo_info.get("repo_root"),
        "branch": repo_info.get("branch"),
        "head": repo_info.get("head"),
        "upstream": repo_info.get("upstream"),
        "dirty": repo_info.get("dirty"),
    }


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    marker = "\n... [truncated]"
    return text[: max(0, max_chars - len(marker))] + marker, True


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


registry.register(
    name="git_inspect",
    description=(
        "Inspect a git repository with bounded read-only actions: repo, status, "
        "diff, staged_diff, log, branches, and show. Prefer this over terminal "
        "for git status/diff/log because it avoids shell execution and trims output."
    ),
    parameters=GIT_INSPECT_SCHEMA,
    handler=git_inspect,
    toolset="git",
    emoji="🌿",
    max_result_size_chars=130_000,
)
