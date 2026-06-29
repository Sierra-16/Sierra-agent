from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .path_context import resolve_workspace_path
from .registry import registry


SEARCH_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": (
                "Regex pattern for target=content, or glob pattern for target=files "
                "such as '*.py' or '*config*'."
            ),
        },
        "target": {
            "type": "string",
            "enum": ["content", "files", "grep", "find"],
            "description": (
                "'content' searches inside files. 'files' searches by file name. "
                "Legacy aliases: grep=content, find=files. Omit to keep Sierra's "
                "legacy file-name search behavior."
            ),
        },
        "path": {
            "type": "string",
            "description": "Directory or file to search. Relative paths resolve under the user workspace.",
        },
        "dir_path": {
            "type": "string",
            "description": "Legacy alias for path.",
        },
        "file_glob": {
            "type": "string",
            "description": "When target=content, restrict searched files by glob such as '*.py'.",
        },
        "output_mode": {
            "type": "string",
            "enum": ["content", "files_only", "count"],
            "description": (
                "For target=content: content returns matching lines, files_only returns paths, "
                "count returns per-file match counts."
            ),
        },
        "context": {
            "type": "integer",
            "minimum": 0,
            "maximum": 20,
            "description": "Number of context lines before and after content matches.",
        },
        "offset": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of results to skip. Defaults to 0.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "description": "Maximum number of results to return. Defaults to 100.",
        },
    },
    "required": ["pattern"],
}


DEFAULT_LIMIT = 100
MAX_LIMIT = 500
MAX_LINE_CHARS = 1200
MAX_CONTEXT_LINE_CHARS = 800
RG_TIMEOUT_SECONDS = 20

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".cache",
    ".next",
    ".turbo",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
    "htmlcov",
}

SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".npmrc",
    ".pypirc",
    "config.json",
    "credentials.json",
    "secrets.json",
}

TEXT_EXTENSIONS = {
    ".bat",
    ".c",
    ".cfg",
    ".cmd",
    ".cpp",
    ".css",
    ".csv",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".less",
    ".md",
    ".py",
    ".pyi",
    ".rs",
    ".rst",
    ".sass",
    ".scss",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def search_files(
    pattern: str,
    target: str | None = None,
    path: str | None = None,
    dir_path: str | None = None,
    file_glob: str | None = None,
    output_mode: str = "content",
    context: int = 0,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """Search files by name or content.

    This mirrors Hermes' single search tool shape while preserving Sierra's
    older search_files("*.py") behavior as file-name search.
    """
    requested_path = path if path is not None else (dir_path if dir_path is not None else ".")
    resolved_path = Path(resolve_workspace_path(requested_path))
    if not resolved_path.exists():
        return _json({"error": f"Path not found: {resolved_path}", "path": str(resolved_path)})

    normalized_target = _normalize_target(target)
    offset = max(0, _coerce_int(offset, 0))
    limit = min(max(_coerce_int(limit, DEFAULT_LIMIT), 1), MAX_LIMIT)
    context = min(max(_coerce_int(context, 0), 0), 20)
    output_mode = _normalize_output_mode(output_mode)

    if normalized_target == "content":
        payload = _search_content(
            pattern=pattern,
            root=resolved_path,
            requested_path=requested_path,
            file_glob=file_glob,
            output_mode=output_mode,
            context=context,
            offset=offset,
            limit=limit,
        )
    else:
        payload = _search_file_names(
            pattern=pattern,
            root=resolved_path,
            requested_path=requested_path,
            offset=offset,
            limit=limit,
        )

    return _json(payload)


def _search_file_names(
    pattern: str,
    root: Path,
    requested_path: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    paths, engine, diagnostics = _find_files(pattern, root)
    total = len(paths)
    selected = paths[offset:offset + limit]
    next_offset = offset + len(selected)
    return {
        "pattern": pattern,
        "target": "files",
        "path": str(root),
        "dir_path": str(root),
        "requested_path": requested_path,
        "requested_dir_path": requested_path,
        "engine": engine,
        "matches": [str(path) for path in selected],
        "results": [
            {
                "path": _display_path(path, root),
                "file_path": str(path),
                "size": _safe_size(path),
                "modified_at": _safe_mtime(path),
            }
            for path in selected
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
        "diagnostics": diagnostics,
    }


def _search_content(
    pattern: str,
    root: Path,
    requested_path: str,
    file_glob: str | None,
    output_mode: str,
    context: int,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    if _is_sensitive_path(root):
        return {
            "error": f"Refusing to content-search sensitive file: {root}",
            "target": "content",
            "path": str(root),
        }

    rg_path = shutil.which("rg")
    diagnostics: list[str] = []
    if rg_path:
        matches, rg_diagnostics = _content_search_with_rg(
            rg_path,
            pattern,
            root,
            file_glob=file_glob,
            context=context,
        )
        diagnostics.extend(rg_diagnostics)
        engine = "ripgrep"
    else:
        matches, fallback_diagnostics = _content_search_with_python(
            pattern,
            root,
            file_glob=file_glob,
            context=context,
        )
        diagnostics.extend(fallback_diagnostics)
        engine = "python"

    if output_mode == "files_only":
        unique_paths = []
        seen = set()
        for item in matches:
            file_path = item["file_path"]
            if file_path in seen:
                continue
            unique_paths.append(file_path)
            seen.add(file_path)
        total = len(unique_paths)
        selected = unique_paths[offset:offset + limit]
        next_offset = offset + len(selected)
        return {
            "pattern": pattern,
            "target": "content",
            "output_mode": output_mode,
            "path": str(root),
            "dir_path": str(root),
            "requested_path": requested_path,
            "file_glob": file_glob,
            "engine": engine,
            "matches": selected,
            "results": [{"file_path": path, "path": _display_path(Path(path), root)} for path in selected],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": next_offset < total,
            "next_offset": next_offset if next_offset < total else None,
            "diagnostics": diagnostics,
        }

    if output_mode == "count":
        counts: dict[str, int] = {}
        for item in matches:
            counts[item["file_path"]] = counts.get(item["file_path"], 0) + 1
        rows = [
            {"file_path": path, "path": _display_path(Path(path), root), "count": count}
            for path, count in sorted(counts.items(), key=lambda value: (-value[1], value[0].lower()))
        ]
        total = len(rows)
        selected = rows[offset:offset + limit]
        next_offset = offset + len(selected)
        return {
            "pattern": pattern,
            "target": "content",
            "output_mode": output_mode,
            "path": str(root),
            "dir_path": str(root),
            "requested_path": requested_path,
            "file_glob": file_glob,
            "engine": engine,
            "matches": selected,
            "results": selected,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": next_offset < total,
            "next_offset": next_offset if next_offset < total else None,
            "diagnostics": diagnostics,
        }

    total = len(matches)
    selected = matches[offset:offset + limit]
    next_offset = offset + len(selected)
    return {
        "pattern": pattern,
        "target": "content",
        "output_mode": "content",
        "path": str(root),
        "dir_path": str(root),
        "requested_path": requested_path,
        "file_glob": file_glob,
        "context": context,
        "engine": engine,
        "matches": selected,
        "results": selected,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": next_offset < total,
        "next_offset": next_offset if next_offset < total else None,
        "diagnostics": diagnostics,
    }


def _find_files(pattern: str, root: Path) -> tuple[list[Path], str, list[str]]:
    rg_path = shutil.which("rg")
    if rg_path and root.is_dir():
        args = [rg_path, "--files", "--hidden", "--glob", pattern]
        for dirname in sorted(EXCLUDED_DIRS):
            args.extend(["--glob", f"!**/{dirname}/**"])
        args.append(str(root))
        result = _run(args, cwd=root)
        if result["returncode"] in (0, 1):
            paths = [
                Path(line).resolve()
                for line in result["stdout"].splitlines()
                if line.strip()
            ]
            return sorted(paths, key=lambda path: str(path).lower()), "ripgrep", _stderr_diagnostics(result)
    paths = list(_walk_files(root))
    filtered = [
        path for path in paths
        if fnmatch.fnmatchcase(path.name, pattern) or fnmatch.fnmatchcase(_as_posix_relative(root, path), pattern)
    ]
    return sorted(filtered, key=lambda path: str(path).lower()), "python", []


def _content_search_with_rg(
    rg_path: str,
    pattern: str,
    root: Path,
    file_glob: str | None,
    context: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    args = [
        rg_path,
        "--json",
        "--line-number",
        "--with-filename",
        "--color",
        "never",
        "--hidden",
    ]
    for dirname in sorted(EXCLUDED_DIRS):
        args.extend(["--glob", f"!**/{dirname}/**"])
    for name in sorted(SENSITIVE_NAMES):
        args.extend(["--glob", f"!**/{name}"])
    if file_glob:
        args.extend(["--glob", file_glob])
    args.extend([pattern, str(root)])

    result = _run(args, cwd=root if root.is_dir() else root.parent)
    if result["returncode"] not in (0, 1):
        return [], _stderr_diagnostics(result)

    matches: list[dict[str, Any]] = []
    for line in result["stdout"].splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data") or {}
        path_text = ((data.get("path") or {}).get("text") or "").strip()
        if not path_text:
            continue
        file_path = Path(path_text).resolve()
        if _is_sensitive_path(file_path):
            continue
        line_number = int(data.get("line_number") or 0)
        line_text = ((data.get("lines") or {}).get("text") or "").rstrip("\r\n")
        item = _content_match(root, file_path, line_number, line_text, context=context)
        matches.append(item)
    return matches, _stderr_diagnostics(result)


def _content_search_with_python(
    pattern: str,
    root: Path,
    file_glob: str | None,
    context: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return [], [f"Invalid regex: {exc}"]

    matches: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for path in _walk_files(root):
        if file_glob and not (
            fnmatch.fnmatchcase(path.name, file_glob)
            or fnmatch.fnmatchcase(_as_posix_relative(root, path), file_glob)
        ):
            continue
        if _is_sensitive_path(path) or _looks_binary(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            diagnostics.append(f"{path}: {exc}")
            continue
        for index, line in enumerate(lines, start=1):
            if regex.search(line):
                matches.append(_content_match(root, path, index, line, context=context, lines=lines))
    return matches, diagnostics[:20]


def _content_match(
    root: Path,
    file_path: Path,
    line_number: int,
    line: str,
    context: int,
    lines: list[str] | None = None,
) -> dict[str, Any]:
    item = {
        "path": _display_path(file_path, root),
        "file_path": str(file_path),
        "line_number": line_number,
        "line": _truncate(line, MAX_LINE_CHARS),
    }
    if context > 0:
        if lines is None:
            lines = _read_lines(file_path)
        before_start = max(1, line_number - context)
        after_end = min(len(lines), line_number + context)
        item["before"] = [
            {"line_number": number, "line": _truncate(lines[number - 1], MAX_CONTEXT_LINE_CHARS)}
            for number in range(before_start, line_number)
        ]
        item["after"] = [
            {"line_number": number, "line": _truncate(lines[number - 1], MAX_CONTEXT_LINE_CHARS)}
            for number in range(line_number + 1, after_end + 1)
        ]
    return item


def _walk_files(root: Path):
    if root.is_file():
        yield root.resolve()
        return
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            dirname
            for dirname in sorted(dirs, key=str.lower)
            if dirname not in EXCLUDED_DIRS and not dirname.startswith(".")
        ]
        for filename in sorted(files, key=str.lower):
            yield (Path(current) / filename).resolve()


def _run(args: list[str], cwd: Path) -> dict[str, Any]:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RG_TIMEOUT_SECONDS,
            creationflags=creation_flags,
            check=False,
        )
        return {"returncode": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or ""}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": f"search timed out after {RG_TIMEOUT_SECONDS}s"}
    except Exception as exc:
        return {"returncode": 1, "stdout": "", "stderr": str(exc)}


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _looks_binary(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return False
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\0" in chunk


def _is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    return name in SENSITIVE_NAMES or "secret" in name or "credential" in name


def _display_path(path: Path, root: Path) -> str:
    try:
        base = root if root.is_dir() else root.parent
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path)


def _as_posix_relative(root: Path, path: Path) -> str:
    try:
        base = root if root.is_dir() else root.parent
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _stderr_diagnostics(result: dict[str, Any]) -> list[str]:
    return [
        line.strip()
        for line in str(result.get("stderr") or "").splitlines()
        if line.strip()
    ][:20]


def _normalize_target(target: str | None) -> str:
    raw = str(target or "files").strip().lower()
    if raw == "grep":
        return "content"
    if raw == "find":
        return "files"
    return raw if raw in {"content", "files"} else "files"


def _normalize_output_mode(output_mode: str | None) -> str:
    raw = str(output_mode or "content").strip().lower()
    return raw if raw in {"content", "files_only", "count"} else "content"


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 16)] + "... [truncated]"


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


registry.register(
    name="search_files",
    description=(
        "Search file contents or find files by name. Prefer this over grep/rg/find/ls "
        "in terminal. target=content performs regex search inside files with optional "
        "file_glob, output_mode, and context lines. target=files finds files by glob. "
        "Calling search_files('*.py') keeps Sierra's legacy file-name search behavior."
    ),
    parameters=SEARCH_FILES_SCHEMA,
    handler=search_files,
    toolset="file",
    max_result_size_chars=100_000,
)
