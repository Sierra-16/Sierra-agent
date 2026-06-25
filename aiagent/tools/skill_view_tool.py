from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any

from .registry import registry
from ..skills.loader import (
    MAX_PAGE_CHARS,
    get_skill,
    get_skill_loader,
)
from ..skills.prompt_index import SkillPromptIndex


_workspace: str | None = None
_skill_index: SkillPromptIndex | None = None


def configure_skill_tools(
    workspace: str | None,
    skill_index: SkillPromptIndex | None = None,
) -> None:
    global _workspace, _skill_index
    _workspace = os.path.abspath(workspace) if workspace else None
    _skill_index = skill_index


def skills_list(category: str | None = None, query: str | None = None) -> str:
    loader = get_skill_loader()
    if loader is None:
        return _json_error("Skill registry is not initialized")
    candidates = loader.list(category=category, query=query)
    summaries = (
        _skill_index.summaries(candidates, registry.names())
        if _skill_index is not None
        else [skill.summary() for skill in candidates]
    )
    categories: dict[str, int] = {}
    for summary in summaries:
        skill_category = summary["category"]
        categories[skill_category] = categories.get(skill_category, 0) + 1
    return json.dumps({
        "skills": summaries,
        "count": len(summaries),
        "total": len(loader.skills),
        "categories": categories,
        "validation_errors": loader.errors,
    }, ensure_ascii=False)


def skill_view(
    name: str,
    file_path: str | None = None,
    offset: int = 0,
    max_chars: int = MAX_PAGE_CHARS,
) -> str:
    loader = get_skill_loader()
    if loader is not None:
        try:
            skill = loader.get(name)
            readiness = _readiness(skill)
            if readiness is not None and not readiness.offered:
                return _json_error(
                    f"Skill '{name}' is not available: {readiness.reason or readiness.status}"
                )
            result = loader.read(name, file_path, offset, max_chars)
            if readiness is not None:
                result.update(readiness.as_dict())
        except Exception as exc:
            return _json_error(str(exc))
        # Keep the old field name for compatibility with existing clients.
        result["body"] = result["content"]
        return json.dumps(result, ensure_ascii=False)

    skill = get_skill(name)
    if skill is None:
        return _json_error(f"Unknown skill: {name}")
    if file_path:
        return _json_error("Skill resources require an initialized registry")
    offset = max(0, int(offset or 0))
    max_chars = max(1000, min(MAX_PAGE_CHARS, int(max_chars or MAX_PAGE_CHARS)))
    end = min(len(skill.body), offset + max_chars)
    return json.dumps({
        "name": skill.name,
        "description": skill.description,
        "category": skill.category,
        "source": "SKILL.md",
        "path": skill.path,
        "content": skill.body[offset:end],
        "body": skill.body[offset:end],
        "offset": offset,
        "next_offset": end if end < len(skill.body) else None,
        "total_chars": len(skill.body),
        "truncated": end < len(skill.body),
        "resources": skill.resources,
    }, ensure_ascii=False)


def skill_render_template(
    name: str,
    file_path: str,
    variables: dict[str, Any] | None = None,
) -> str:
    loader = get_skill_loader()
    if loader is None:
        return _json_error("Skill registry is not initialized")
    try:
        readiness = _readiness(loader.get(name))
        if readiness is not None and not readiness.offered:
            return _json_error(
                f"Skill '{name}' is not available: {readiness.reason or readiness.status}"
            )
        result = loader.render_template(name, file_path, variables)
    except Exception as exc:
        return _json_error(str(exc))
    return json.dumps(result, ensure_ascii=False)


def skill_run_script(
    name: str,
    file_path: str,
    args: list[Any] | None = None,
    timeout: int = 60,
) -> str:
    loader = get_skill_loader()
    if loader is None:
        return _json_error("Skill registry is not initialized")
    try:
        readiness = _readiness(loader.get(name))
        if readiness is not None and not readiness.offered:
            return _json_error(
                f"Skill '{name}' is not available: {readiness.reason or readiness.status}"
            )
        if readiness is not None and readiness.status == "setup_needed":
            missing = [
                *(f"command:{item}" for item in readiness.missing_commands),
                *(
                    f"env:{item}"
                    for item in readiness.missing_environment_variables
                ),
            ]
            return _json_error(
                "Skill prerequisites are missing: " + ", ".join(missing)
            )
        _, script_path, normalized = loader.script(name, file_path)
        command = _script_command(script_path, args or [])
        timeout = max(1, min(120, int(timeout or 60)))
        result = subprocess.run(
            command,
            cwd=_workspace or os.getcwd(),
            env=_restricted_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return json.dumps({
            "error": f"Skill script timed out after {timeout} seconds",
            "stdout": _limit_output(exc.stdout),
            "stderr": _limit_output(exc.stderr),
        }, ensure_ascii=False)
    except Exception as exc:
        return _json_error(str(exc))

    return json.dumps({
        "skill": name,
        "script": normalized,
        "returncode": result.returncode,
        "stdout": _limit_output(result.stdout),
        "stderr": _limit_output(result.stderr),
        "ok": result.returncode == 0,
    }, ensure_ascii=False)


def _script_command(script_path: str, args: list[Any]) -> list[str]:
    if not isinstance(args, list):
        raise ValueError("args must be an array")
    if len(args) > 32:
        raise ValueError("A skill script accepts at most 32 arguments")
    normalized_args = []
    for value in args:
        if isinstance(value, (dict, list)):
            raise ValueError("Skill script arguments must be scalar values")
        text = str(value)
        if len(text) > 2000 or "\x00" in text:
            raise ValueError("Skill script argument is invalid or too long")
        normalized_args.append(text)

    extension = os.path.splitext(script_path)[1].lower()
    if extension == ".py":
        return [sys.executable, script_path, *normalized_args]
    if extension == ".ps1":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if not executable:
            raise RuntimeError("PowerShell is not available")
        return [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script_path,
            *normalized_args,
        ]
    if extension == ".js":
        executable = shutil.which("node")
        if not executable:
            raise RuntimeError("Node.js is not available")
        return [executable, script_path, *normalized_args]
    raise ValueError("Unsupported skill script type")


def _restricted_environment() -> dict[str, str]:
    allowed = (
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PYTHONIOENCODING",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["SIERRA_SKILL_RUN"] = "1"
    return environment


def _limit_output(value: Any, max_chars: int = MAX_PAGE_CHARS) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... output truncated ..."


def _json_error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _readiness(skill):
    if skill is None or _skill_index is None:
        return None
    return _skill_index.readiness(skill, registry.names())


registry.register(
    name="skills_list",
    description=(
        "List Sierra skills and metadata without loading their full instructions. "
        "Use category or query to narrow the result, then call skill_view before applying a skill."
    ),
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "Optional exact category filter"},
            "query": {"type": "string", "description": "Optional name, description, or trigger search"},
        },
    },
    handler=skills_list,
)

registry.register(
    name="skill_view",
    description=(
        "Read a skill's SKILL.md or a linked UTF-8 resource. Read all pages when truncated=true. "
        "file_path must be under references/, templates/, scripts/, or assets/."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name"},
            "file_path": {
                "type": "string",
                "description": "Optional resource path relative to the skill directory",
            },
            "offset": {"type": "integer", "minimum": 0, "description": "Character offset"},
            "max_chars": {
                "type": "integer",
                "minimum": 1000,
                "maximum": MAX_PAGE_CHARS,
                "description": "Maximum characters returned",
            },
        },
        "required": ["name"],
    },
    handler=skill_view,
)

registry.register(
    name="skill_render_template",
    description=(
        "Render a text file under a skill's templates/ directory. Replaces {{variable}} placeholders "
        "and reports any unresolved variables. Use write_file separately if the result should be saved."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name"},
            "file_path": {"type": "string", "description": "Path under templates/"},
            "variables": {
                "type": "object",
                "description": "Scalar values keyed by template variable name",
                "additionalProperties": True,
            },
        },
        "required": ["name", "file_path"],
    },
    handler=skill_render_template,
)

registry.register(
    name="skill_run_script",
    description=(
        "Run a packaged .py, .ps1, or .js file under a skill's scripts/ directory. "
        "This is a high-risk action that always requires user approval and is audited."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name"},
            "file_path": {"type": "string", "description": "Path under scripts/"},
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Positional script arguments; no shell parsing is used",
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": 120,
                "description": "Execution timeout in seconds",
            },
        },
        "required": ["name", "file_path"],
    },
    handler=skill_run_script,
)
