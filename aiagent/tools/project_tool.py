from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from .path_context import resolve_workspace_path
from .registry import registry

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback.
    tomllib = None


PROJECT_INSPECT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Project directory. Relative paths resolve under the user workspace.",
        },
        "max_depth": {
            "type": "integer",
            "minimum": 1,
            "maximum": 12,
            "description": "Maximum directory depth to scan. Defaults to 6.",
        },
        "max_files": {
            "type": "integer",
            "minimum": 100,
            "maximum": 50000,
            "description": "Maximum files to inspect before truncating the scan. Defaults to 20000.",
        },
        "include_hidden": {
            "type": "boolean",
            "description": "Include hidden directories. Defaults to false.",
        },
        "include_git": {
            "type": "boolean",
            "description": "Include read-only git summary when the project is a repository. Defaults to true.",
        },
    },
    "required": [],
}


DEFAULT_MAX_DEPTH = 6
DEFAULT_MAX_FILES = 20_000
MAX_KEY_FILES = 120
MAX_DIRECTORY_SUMMARIES = 40
MAX_TOP_LEVEL_FILES = 80
MAX_FRAMEWORKS = 30

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
    ".turbo",
    ".next",
    ".parcel-cache",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
    "htmlcov",
    ".idea",
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

KEY_FILE_NAMES = {
    "README",
    "README.md",
    "README.rst",
    ".hermes.md",
    "HERMES.md",
    "AGENTS.md",
    "CLAUDE.md",
    "SIERRA.md",
    ".cursorrules",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "requirements-dev.txt",
    "Pipfile",
    "poetry.lock",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "next.config.mjs",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
    ".gitignore",
    ".gitattributes",
    "config.example.json",
}

CONTEXT_FILE_PRIORITY = (
    ".hermes.md",
    "HERMES.md",
    "SIERRA.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".sierra/context.md",
)

SUBDIRECTORY_CONTEXT_NAMES = {
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
}

ENTRYPOINT_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "run_server.py",
    "cli.py",
    "manage.py",
    "index.js",
    "index.ts",
    "main.js",
    "main.ts",
    "main.tsx",
    "App.tsx",
}

EXTENSION_LANGUAGES = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".json": "JSON",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".less": "CSS",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".xml": "XML",
    ".sql": "SQL",
    ".ps1": "PowerShell",
    ".bat": "Batch",
    ".cmd": "Batch",
    ".sh": "Shell",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C/C++",
    ".h": "C/C++",
    ".cpp": "C/C++",
    ".hpp": "C/C++",
}


def project_inspect(
    path: str = ".",
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_files: int = DEFAULT_MAX_FILES,
    include_hidden: bool = False,
    include_git: bool = True,
) -> str:
    root = Path(resolve_workspace_path(path))
    if root.is_file():
        root = root.parent
    if not root.exists():
        return _json({"ok": False, "error": f"Project path not found: {root}", "requested_path": path})
    if not root.is_dir():
        return _json({"ok": False, "error": f"Project path is not a directory: {root}", "requested_path": path})

    max_depth = _clamp_int(max_depth, DEFAULT_MAX_DEPTH, 1, 12)
    max_files = _clamp_int(max_files, DEFAULT_MAX_FILES, 100, 50_000)

    scan = _scan_project(root, max_depth=max_depth, max_files=max_files, include_hidden=include_hidden)
    manifests = _read_manifest_summaries(root, scan["key_files"])
    frameworks = _detect_frameworks(scan, manifests)
    commands = _infer_commands(root, scan, manifests, frameworks)
    git = _git_summary(root) if include_git else {"enabled": False}
    context_files = _discover_context_files(root, max_depth=max_depth)

    return _json({
        "ok": True,
        "project_root": str(root),
        "requested_path": path,
        "scan": scan["scan"],
        "git": git,
        "languages": scan["languages"],
        "frameworks": frameworks[:MAX_FRAMEWORKS],
        "package_managers": _detect_package_managers(scan["key_files"]),
        "context_files": context_files,
        "entrypoints": scan["entrypoints"],
        "commands": commands,
        "key_files": scan["key_files"][:MAX_KEY_FILES],
        "top_level": _top_level(root, scan["skipped_dirs"]),
        "directories": scan["directories"][:MAX_DIRECTORY_SUMMARIES],
        "manifests": manifests,
        "follow_up_tools": [
            {
                "tool": "read_file",
                "when": "Read specific project instructions, entrypoints, or config examples.",
            },
            {
                "tool": "search_files",
                "when": "Find symbols, error strings, or file names before reading files.",
            },
            {
                "tool": "git_inspect",
                "when": "Inspect status, diffs, staged changes, and recent commits.",
            },
        ],
        "warnings": scan["warnings"],
    })


def _scan_project(root: Path, max_depth: int, max_files: int, include_hidden: bool) -> dict[str, Any]:
    file_count = 0
    dir_count = 0
    total_bytes = 0
    truncated = False
    skipped_dirs: list[str] = []
    warnings: list[str] = []
    key_files: list[dict[str, Any]] = []
    entrypoints: list[dict[str, Any]] = []
    language_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"language": "", "files": 0, "bytes": 0, "extensions": set()}
    )
    directory_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"path": "", "files": 0, "directories": 0, "bytes": 0}
    )

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_dir = _relative_path(root, current_path)
        depth = 0 if rel_dir == "." else len(Path(rel_dir).parts)
        dir_count += 1

        kept_dirs: list[str] = []
        for dirname in sorted(dirs, key=str.lower):
            child_rel = _join_rel(rel_dir, dirname)
            if _should_skip_dir(dirname, include_hidden):
                skipped_dirs.append(child_rel)
                continue
            if depth >= max_depth:
                skipped_dirs.append(child_rel)
                continue
            kept_dirs.append(dirname)
            bucket = _directory_bucket(child_rel)
            directory_stats[bucket]["path"] = bucket
            directory_stats[bucket]["directories"] += 1
        dirs[:] = kept_dirs

        for filename in sorted(files, key=str.lower):
            if file_count >= max_files:
                truncated = True
                dirs[:] = []
                break

            file_path = current_path / filename
            if file_path.is_symlink():
                continue
            rel_path = _join_rel(rel_dir, filename)
            try:
                size = file_path.stat().st_size
            except OSError:
                size = 0

            file_count += 1
            total_bytes += size

            bucket = _directory_bucket(rel_path)
            directory_stats[bucket]["path"] = bucket
            directory_stats[bucket]["files"] += 1
            directory_stats[bucket]["bytes"] += size

            ext = file_path.suffix.lower()
            language = EXTENSION_LANGUAGES.get(ext)
            if language:
                stat = language_stats[language]
                stat["language"] = language
                stat["files"] += 1
                stat["bytes"] += size
                stat["extensions"].add(ext)

            if _is_key_file(rel_path, filename):
                key_files.append(_file_summary(rel_path, size, kind=_key_file_kind(filename)))
            if _is_entrypoint(rel_path, filename):
                entrypoints.append(_file_summary(rel_path, size, kind="entrypoint"))

    if truncated:
        warnings.append(f"Scan stopped after {max_files} files; increase max_files for a fuller map.")

    languages = []
    for stat in sorted(language_stats.values(), key=lambda item: (-item["bytes"], item["language"])):
        languages.append({
            "language": stat["language"],
            "files": stat["files"],
            "bytes": stat["bytes"],
            "extensions": sorted(stat["extensions"]),
        })

    directories = sorted(
        directory_stats.values(),
        key=lambda item: (item["path"] == ".", -item["files"] - item["directories"], item["path"]),
    )

    return {
        "scan": {
            "files": file_count,
            "directories": dir_count,
            "bytes": total_bytes,
            "max_depth": max_depth,
            "max_files": max_files,
            "truncated": truncated,
            "skipped_dir_count": len(skipped_dirs),
        },
        "languages": languages[:20],
        "key_files": _dedupe_file_summaries(key_files),
        "entrypoints": _dedupe_file_summaries(entrypoints),
        "directories": directories,
        "skipped_dirs": skipped_dirs[:200],
        "warnings": warnings,
    }


def _read_manifest_summaries(root: Path, key_files: list[dict[str, Any]]) -> dict[str, Any]:
    manifests: dict[str, Any] = {
        "python": [],
        "node": [],
    }
    for item in key_files:
        rel_path = item["path"]
        name = Path(rel_path).name
        if item.get("sensitive"):
            continue
        full_path = root / rel_path
        if name == "requirements.txt" or name == "requirements-dev.txt":
            deps = _read_requirements(full_path)
            manifests["python"].append({
                "path": rel_path,
                "kind": "requirements",
                "dependencies": deps[:80],
                "dependency_count": len(deps),
            })
        elif name == "pyproject.toml":
            manifests["python"].append(_read_pyproject(full_path, rel_path))
        elif name == "package.json":
            manifests["node"].append(_read_package_json(full_path, rel_path))
    return manifests


def _detect_frameworks(scan: dict[str, Any], manifests: dict[str, Any]) -> list[dict[str, str]]:
    deps = _all_dependencies(manifests)
    frameworks: list[dict[str, str]] = []

    if _language_files(scan, "Python") or manifests["python"]:
        frameworks.append({"name": "python", "reason": "Python files or Python manifests detected"})
    if manifests["node"]:
        frameworks.append({"name": "node", "reason": "package.json detected"})
    if "react" in deps:
        frameworks.append({"name": "react", "reason": "react dependency detected"})
    if "vite" in deps:
        frameworks.append({"name": "vite", "reason": "vite dependency detected"})
    if "next" in deps:
        frameworks.append({"name": "next.js", "reason": "next dependency detected"})
    if "vue" in deps:
        frameworks.append({"name": "vue", "reason": "vue dependency detected"})
    if "svelte" in deps:
        frameworks.append({"name": "svelte", "reason": "svelte dependency detected"})
    if "typescript" in deps or _language_files(scan, "TypeScript"):
        frameworks.append({"name": "typescript", "reason": "TypeScript files or dependency detected"})
    if "playwright" in deps:
        frameworks.append({"name": "playwright", "reason": "playwright dependency detected"})
    if "fastapi" in deps:
        frameworks.append({"name": "fastapi", "reason": "fastapi dependency detected"})
    if "flask" in deps:
        frameworks.append({"name": "flask", "reason": "flask dependency detected"})
    if "django" in deps:
        frameworks.append({"name": "django", "reason": "django dependency detected"})
    if "pytest" in deps:
        frameworks.append({"name": "pytest", "reason": "pytest dependency detected"})
    if any(item["path"].startswith("tests/") for item in scan["key_files"] + scan["entrypoints"]):
        frameworks.append({"name": "tests", "reason": "tests directory detected"})
    return _dedupe_frameworks(frameworks)


def _infer_commands(
    root: Path,
    scan: dict[str, Any],
    manifests: dict[str, Any],
    frameworks: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    commands: dict[str, list[dict[str, str]]] = {
        "install": [],
        "run": [],
        "test": [],
        "build": [],
        "typecheck": [],
    }

    key_paths = {item["path"] for item in scan["key_files"]}
    entry_paths = {item["path"] for item in scan["entrypoints"]}
    framework_names = {item["name"] for item in frameworks}

    if "requirements.txt" in key_paths:
        commands["install"].append(_command("python -m pip install -r requirements.txt", ".", "requirements.txt"))
    if "pyproject.toml" in key_paths:
        commands["install"].append(_command("python -m pip install -e .", ".", "pyproject.toml"))
    if "tests" in framework_names:
        if "pytest" in framework_names:
            commands["test"].append(_command("python -m pytest", ".", "pytest dependency"))
        commands["test"].append(_command("python -m unittest discover -s tests", ".", "tests directory"))
    if "main.py" in entry_paths:
        commands["run"].append(_command("python main.py", ".", "main.py"))
    if "run_server.py" in entry_paths:
        commands["run"].append(_command("python run_server.py", ".", "run_server.py"))

    for package in manifests["node"]:
        cwd = _parent_dir(package["path"])
        scripts = package.get("scripts") or {}
        package_dir_paths = {path for path in key_paths if _parent_dir(path) == cwd}
        if "package-lock.json" in {Path(path).name for path in package_dir_paths}:
            commands["install"].append(_command("npm ci", cwd, package["path"]))
        elif "pnpm-lock.yaml" in {Path(path).name for path in package_dir_paths}:
            commands["install"].append(_command("pnpm install", cwd, package["path"]))
        elif "yarn.lock" in {Path(path).name for path in package_dir_paths}:
            commands["install"].append(_command("yarn install", cwd, package["path"]))
        else:
            commands["install"].append(_command("npm install", cwd, package["path"]))

        for script_name, category in (
            ("dev", "run"),
            ("start", "run"),
            ("test", "test"),
            ("build", "build"),
            ("typecheck", "typecheck"),
            ("lint", "typecheck"),
        ):
            if script_name in scripts:
                runner = _node_runner(package_dir_paths)
                commands[category].append(_command(f"{runner} run {script_name}", cwd, package["path"]))

    return {name: _dedupe_commands(items) for name, items in commands.items()}


def _git_summary(root: Path) -> dict[str, Any]:
    git = shutil.which("git")
    if not git:
        return {"enabled": True, "is_repo": False, "error": "git executable not found"}
    repo = _run_git(git, root, ["rev-parse", "--show-toplevel"])
    if repo["returncode"] != 0:
        return {"enabled": True, "is_repo": False}
    branch = _run_git(git, root, ["branch", "--show-current"])
    head = _run_git(git, root, ["rev-parse", "--short", "HEAD"])
    status = _run_git(git, root, ["status", "--short", "--branch"])
    parsed = _parse_git_status(status["stdout"])
    return {
        "enabled": True,
        "is_repo": True,
        "repo_root": repo["stdout"].strip(),
        "branch": branch["stdout"].strip() or None,
        "head": head["stdout"].strip() or None,
        "dirty": bool(parsed["entries"]),
        "summary": parsed["summary"],
        "entries": parsed["entries"][:80],
    }


def _discover_context_files(root: Path, max_depth: int) -> dict[str, Any]:
    startup_candidates: list[dict[str, Any]] = []
    for priority, rel_path in enumerate(CONTEXT_FILE_PRIORITY, start=1):
        full_path = root / rel_path
        if full_path.is_file():
            startup_candidates.append(_context_file_summary(root, full_path, priority, scope="startup"))

    cursor_rules = root / ".cursor" / "rules"
    if cursor_rules.is_dir():
        for rule_path in sorted(cursor_rules.glob("*.mdc"), key=lambda item: item.name.lower())[:40]:
            startup_candidates.append(_context_file_summary(root, rule_path, 100, scope="startup"))

    subdirectory_hints: list[dict[str, Any]] = []
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        rel_dir = _relative_path(root, current_path)
        depth = 0 if rel_dir == "." else len(Path(rel_dir).parts)
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [
                dirname
                for dirname in sorted(dirs, key=str.lower)
                if dirname not in EXCLUDED_DIRS and dirname != ".git"
            ]

        if rel_dir == ".":
            continue
        for filename in sorted(files, key=str.lower):
            if filename in SUBDIRECTORY_CONTEXT_NAMES:
                subdirectory_hints.append(
                    _context_file_summary(root, current_path / filename, 200, scope="subdirectory")
                )
                if len(subdirectory_hints) >= 80:
                    break
        if len(subdirectory_hints) >= 80:
            break

    selected = startup_candidates[0] if startup_candidates else None
    return {
        "style": "hermes-inspired progressive disclosure",
        "selected_startup_file": selected,
        "startup_candidates": startup_candidates,
        "subdirectory_hints": subdirectory_hints,
        "note": (
            "This tool reports context file locations only. Use read_file for a specific "
            "file when it becomes relevant, keeping the prompt small."
        ),
    }


def _context_file_summary(root: Path, path: Path, priority: int, scope: str) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    rel_path = _relative_path(root, path)
    return {
        "path": rel_path,
        "scope": scope,
        "priority": priority,
        "kind": _context_file_kind(rel_path),
        "size": size,
        "sensitive": _is_sensitive_path(rel_path),
    }


def _context_file_kind(rel_path: str) -> str:
    name = Path(rel_path).name
    if name in {".hermes.md", "HERMES.md"}:
        return "hermes-project-instructions"
    if name == "SIERRA.md" or rel_path == ".sierra/context.md":
        return "sierra-project-instructions"
    if name == "AGENTS.md":
        return "agent-project-instructions"
    if name == "CLAUDE.md":
        return "claude-project-instructions"
    if name == ".cursorrules" or rel_path.startswith(".cursor/rules/"):
        return "cursor-rules"
    return "context"


def _top_level(root: Path, skipped_dirs: list[str]) -> dict[str, Any]:
    skipped_set = set(skipped_dirs)
    directories = []
    files = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return {"directories": [], "files": []}

    for entry in entries:
        rel_path = entry.name
        if entry.is_dir():
            directories.append({
                "path": rel_path,
                "skipped": rel_path in skipped_set or _should_skip_dir(entry.name, include_hidden=False),
            })
        elif entry.is_file() and len(files) < MAX_TOP_LEVEL_FILES:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            files.append(_file_summary(rel_path, size, kind=_key_file_kind(entry.name)))
    return {"directories": directories, "files": files}


def _read_requirements(path: Path) -> list[str]:
    deps: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            name = stripped.split(";", 1)[0]
            for marker in ("==", ">=", "<=", "~=", "!=", ">", "<"):
                name = name.split(marker, 1)[0]
            name = name.strip().lower()
            if name:
                deps.append(name)
    except OSError:
        pass
    return sorted(set(deps))


def _read_pyproject(path: Path, rel_path: str) -> dict[str, Any]:
    result: dict[str, Any] = {"path": rel_path, "kind": "pyproject", "dependencies": [], "dependency_count": 0}
    if tomllib is None:
        return result
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        result["error"] = str(exc)
        return result
    project = data.get("project") if isinstance(data, dict) else {}
    deps = []
    if isinstance(project, dict):
        result["name"] = project.get("name")
        deps.extend(_normalize_dependency_names(project.get("dependencies") or []))
        optional = project.get("optional-dependencies") or {}
        if isinstance(optional, dict):
            for values in optional.values():
                deps.extend(_normalize_dependency_names(values or []))
    result["dependencies"] = sorted(set(deps))[:120]
    result["dependency_count"] = len(set(deps))
    return result


def _read_package_json(path: Path, rel_path: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": rel_path,
        "kind": "package",
        "dependencies": [],
        "dependency_count": 0,
        "scripts": {},
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        result["error"] = str(exc)
        return result

    dependencies: set[str] = set()
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = data.get(section) or {}
        if isinstance(values, dict):
            dependencies.update(str(key).lower() for key in values)
    scripts = data.get("scripts") or {}
    result.update({
        "name": data.get("name"),
        "dependencies": sorted(dependencies)[:160],
        "dependency_count": len(dependencies),
        "scripts": {
            str(key): str(value)
            for key, value in sorted(scripts.items())[:40]
        } if isinstance(scripts, dict) else {},
    })
    return result


def _run_git(git: str, root: Path, args: list[str]) -> dict[str, Any]:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [git, "-C", str(root), *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=creation_flags,
            check=False,
        )
        return {"returncode": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or ""}
    except Exception as exc:
        return {"returncode": 1, "stdout": "", "stderr": str(exc)}


def _parse_git_status(output: str) -> dict[str, Any]:
    summary = {"modified": 0, "added": 0, "deleted": 0, "renamed": 0, "untracked": 0, "conflicted": 0}
    entries = []
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
        if "U" in code:
            summary["conflicted"] += 1
    return {"summary": summary, "entries": entries}


def _is_key_file(rel_path: str, filename: str) -> bool:
    if filename in KEY_FILE_NAMES:
        return True
    if filename in SENSITIVE_NAMES:
        return True
    if rel_path.startswith("tests/") and (filename.startswith("test_") or filename.endswith("_test.py")):
        return True
    return False


def _is_entrypoint(rel_path: str, filename: str) -> bool:
    if filename in ENTRYPOINT_NAMES:
        return True
    return rel_path in {
        "src/main.tsx",
        "src/main.ts",
        "src/index.tsx",
        "src/index.ts",
        "app/main.py",
    }


def _file_summary(rel_path: str, size: int, kind: str) -> dict[str, Any]:
    return {
        "path": rel_path,
        "kind": kind,
        "size": size,
        "sensitive": _is_sensitive_path(rel_path),
    }


def _key_file_kind(filename: str) -> str:
    if filename in SENSITIVE_NAMES:
        return "sensitive"
    lowered = filename.lower()
    if lowered.startswith("readme"):
        return "readme"
    if lowered in {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        return "node-manifest"
    if lowered in {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "requirements-dev.txt"}:
        return "python-manifest"
    if lowered in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
        return "container"
    if lowered in {"makefile"}:
        return "task-runner"
    if lowered.startswith("config.example"):
        return "example-config"
    return "project-file"


def _is_sensitive_path(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    return name in SENSITIVE_NAMES or "secret" in name or "credential" in name


def _should_skip_dir(dirname: str, include_hidden: bool) -> bool:
    if dirname in EXCLUDED_DIRS:
        return True
    return not include_hidden and dirname.startswith(".")


def _directory_bucket(rel_path: str) -> str:
    if rel_path == ".":
        return "."
    first = rel_path.split("/", 1)[0]
    return first or "."


def _relative_path(root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return str(path)
    text = rel.as_posix()
    return text or "."


def _join_rel(base: str, name: str) -> str:
    return name if base == "." else f"{base}/{name}"


def _dedupe_file_summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in sorted(items, key=lambda value: (value["path"].count("/"), value["path"].lower())):
        path = item["path"]
        if path in seen:
            continue
        deduped.append(item)
        seen.add(path)
    return deduped


def _all_dependencies(manifests: dict[str, Any]) -> set[str]:
    deps: set[str] = set()
    for group in ("python", "node"):
        for manifest in manifests.get(group, []):
            for dep in manifest.get("dependencies") or []:
                deps.add(str(dep).lower())
    return deps


def _normalize_dependency_names(values: list[Any]) -> list[str]:
    deps = []
    for raw in values:
        name = str(raw).split(";", 1)[0]
        for marker in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            name = name.split(marker, 1)[0]
        name = name.strip().lower()
        if name:
            deps.append(name)
    return deps


def _language_files(scan: dict[str, Any], language: str) -> int:
    for item in scan["languages"]:
        if item["language"] == language:
            return int(item["files"])
    return 0


def _dedupe_frameworks(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    result = []
    for item in items:
        name = item["name"]
        if name in seen:
            continue
        seen.add(name)
        result.append(item)
    return result


def _detect_package_managers(key_files: list[dict[str, Any]]) -> list[str]:
    paths = {item["path"] for item in key_files}
    managers = []
    if "requirements.txt" in paths or "pyproject.toml" in paths:
        managers.append("pip")
    if "uv.lock" in paths:
        managers.append("uv")
    if "poetry.lock" in paths:
        managers.append("poetry")
    if any(Path(path).name == "package-lock.json" for path in paths):
        managers.append("npm")
    if any(Path(path).name == "pnpm-lock.yaml" for path in paths):
        managers.append("pnpm")
    if any(Path(path).name == "yarn.lock" for path in paths):
        managers.append("yarn")
    return managers


def _parent_dir(path: str) -> str:
    parent = Path(path).parent.as_posix()
    return "." if parent == "." else parent


def _node_runner(package_dir_paths: set[str]) -> str:
    names = {Path(path).name for path in package_dir_paths}
    if "pnpm-lock.yaml" in names:
        return "pnpm"
    if "yarn.lock" in names:
        return "yarn"
    return "npm"


def _command(command: str, cwd: str, source: str) -> dict[str, str]:
    return {"command": command, "cwd": cwd, "source": source}


def _dedupe_commands(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    deduped = []
    for item in items:
        key = (item["cwd"], item["command"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(max(number, minimum), maximum)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


registry.register(
    name="project_inspect",
    description=(
        "Build a compact project map: repository summary, language and framework "
        "signals, important files, entrypoints, inferred commands, and top-level "
        "directory structure. Use this before working in an unfamiliar codebase."
    ),
    parameters=PROJECT_INSPECT_SCHEMA,
    handler=project_inspect,
    toolset="project",
    max_result_size_chars=130_000,
)
