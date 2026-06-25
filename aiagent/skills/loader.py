from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


ALLOWED_RESOURCE_DIRS = ("references", "templates", "scripts", "assets")
TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".j2",
    ".jinja",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
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
SCRIPT_EXTENSIONS = {".py", ".ps1", ".js"}
MAX_RESOURCE_BYTES = 512 * 1024
MAX_PAGE_CHARS = 12_000


class Skill:
    __slots__ = (
        "name",
        "description",
        "triggers",
        "category",
        "body",
        "path",
        "root_dir",
        "frontmatter",
        "platforms",
        "prerequisites",
        "resources",
    )

    def __init__(
        self,
        name: str,
        description: str,
        triggers: list[str],
        category: str,
        body: str,
        path: str,
        frontmatter: dict[str, Any] | None = None,
        platforms: list[str] | None = None,
        prerequisites: dict[str, Any] | None = None,
        resources: list[dict[str, Any]] | None = None,
    ):
        self.name = name
        self.description = description
        self.triggers = triggers
        self.category = category
        self.body = body
        self.path = path
        self.root_dir = os.path.dirname(path)
        self.frontmatter = frontmatter or {}
        self.platforms = platforms or []
        self.prerequisites = prerequisites or {}
        self.resources = resources or []

    def summary(self) -> dict[str, Any]:
        counts = {kind: 0 for kind in ALLOWED_RESOURCE_DIRS}
        for resource in self.resources:
            counts[resource["kind"]] += 1
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "triggers": self.triggers,
            "platforms": self.platforms,
            "prerequisites": self.prerequisites,
            "resource_counts": counts,
        }


class SkillLoader:
    """Discover, validate, and safely expose Sierra skill packages."""

    def __init__(self, skills_dir: str = "skills"):
        if not os.path.isabs(skills_dir):
            project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            skills_dir = os.path.join(project_dir, skills_dir)
        self.skills_dir = os.path.abspath(skills_dir)
        self.errors: list[str] = []
        self.skills: list[Skill] = []
        self._by_name: dict[str, Skill] = {}

    def load(self) -> list[Skill]:
        return self.reload()

    def reload(self) -> list[Skill]:
        skills: list[Skill] = []
        errors: list[str] = []
        if not os.path.isdir(self.skills_dir):
            self.skills = []
            self._by_name = {}
            self.errors = []
            return self.skills

        seen_names: set[str] = set()
        for root, dirs, files in os.walk(self.skills_dir, followlinks=False):
            dirs[:] = sorted(
                directory
                for directory in dirs
                if not directory.startswith(".") and not os.path.islink(os.path.join(root, directory))
            )
            if "SKILL.md" not in files:
                continue
            path = os.path.join(root, "SKILL.md")
            # A skill package owns its descendants; resources are indexed separately.
            dirs[:] = []
            try:
                skill = self._parse(path)
            except Exception as exc:
                errors.append(f"{path}: {exc}")
                continue
            if skill.name in seen_names:
                errors.append(f"{path}: duplicate skill name '{skill.name}'")
                continue
            seen_names.add(skill.name)
            skills.append(skill)

        skills.sort(key=lambda skill: (skill.category, skill.name))
        self.skills = skills
        self._by_name = {skill.name: skill for skill in skills}
        self.errors = errors
        return self.skills

    def get(self, name: str) -> Skill | None:
        return self._by_name.get(str(name).strip())

    def list(self, category: str | None = None, query: str | None = None) -> list[Skill]:
        category = str(category or "").strip().lower()
        query = str(query or "").strip().lower()
        result = []
        for skill in self.skills:
            if category and skill.category.lower() != category:
                continue
            haystack = " ".join(
                [skill.name, skill.description, skill.category, *skill.triggers]
            ).lower()
            if query and query not in haystack:
                continue
            result.append(skill)
        return result

    def read(
        self,
        name: str,
        file_path: str | None = None,
        offset: int = 0,
        max_chars: int = MAX_PAGE_CHARS,
    ) -> dict[str, Any]:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Unknown skill: {name}")

        if file_path:
            path, normalized = self.resolve_resource(skill, file_path)
            if not _is_text_file(path):
                raise ValueError(f"Resource is not readable text: {normalized}")
            if os.path.getsize(path) > MAX_RESOURCE_BYTES:
                raise ValueError(f"Resource exceeds {MAX_RESOURCE_BYTES} bytes: {normalized}")
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
            source = normalized
        else:
            content = skill.body
            source = "SKILL.md"

        offset = max(0, int(offset or 0))
        max_chars = max(1000, min(MAX_PAGE_CHARS, int(max_chars or MAX_PAGE_CHARS)))
        end = min(len(content), offset + max_chars)
        return {
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "source": source,
            "path": skill.path if source == "SKILL.md" else path,
            "content": content[offset:end],
            "offset": offset,
            "next_offset": end if end < len(content) else None,
            "total_chars": len(content),
            "truncated": end < len(content),
            "resources": skill.resources if source == "SKILL.md" else None,
        }

    def resolve_resource(self, skill: Skill, file_path: str) -> tuple[str, str]:
        normalized = str(file_path or "").strip().replace("\\", "/")
        if not normalized:
            raise ValueError("file_path cannot be empty")
        if os.path.isabs(normalized) or os.path.splitdrive(normalized)[0]:
            raise ValueError("Absolute resource paths are not allowed")

        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if not parts or parts[0] not in ALLOWED_RESOURCE_DIRS:
            allowed = ", ".join(ALLOWED_RESOURCE_DIRS)
            raise ValueError(f"Resource must be inside one of: {allowed}")
        if any(part == ".." for part in parts):
            raise ValueError("Parent path traversal is not allowed")

        root = os.path.realpath(skill.root_dir)
        resolved = os.path.realpath(os.path.join(root, *parts))
        try:
            inside_root = os.path.commonpath([root, resolved]) == root
        except ValueError:
            inside_root = False
        if not inside_root:
            raise ValueError("Resource path escapes the skill directory")
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"Skill resource not found: {'/'.join(parts)}")
        return resolved, "/".join(parts)

    def render_template(
        self,
        name: str,
        file_path: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Unknown skill: {name}")
        path, normalized = self.resolve_resource(skill, file_path)
        if not normalized.startswith("templates/"):
            raise ValueError("Only resources in templates/ can be rendered")
        if not _is_text_file(path):
            raise ValueError("Template must be a UTF-8 text file")
        if os.path.getsize(path) > MAX_RESOURCE_BYTES:
            raise ValueError(f"Template exceeds {MAX_RESOURCE_BYTES} bytes")

        with open(path, "r", encoding="utf-8") as file:
            template = file.read()
        values = variables or {}
        if not isinstance(values, dict):
            raise ValueError("variables must be an object")
        invalid = [key for key in values if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", str(key))]
        if invalid:
            raise ValueError(f"Invalid template variable names: {', '.join(map(str, invalid))}")

        pattern = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*}}")
        used: set[str] = set()

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in values:
                return match.group(0)
            used.add(key)
            value = values[key]
            if isinstance(value, (dict, list)):
                raise ValueError(f"Template variable '{key}' must be a scalar")
            return str(value)

        rendered = pattern.sub(replace, template)
        unresolved = sorted(set(pattern.findall(rendered)))
        return {
            "name": skill.name,
            "template": normalized,
            "content": rendered,
            "used_variables": sorted(used),
            "unresolved_variables": unresolved,
        }

    def script(self, name: str, file_path: str) -> tuple[Skill, str, str]:
        skill = self.get(name)
        if skill is None:
            raise KeyError(f"Unknown skill: {name}")
        path, normalized = self.resolve_resource(skill, file_path)
        if not normalized.startswith("scripts/"):
            raise ValueError("Only resources in scripts/ can be executed")
        if Path(path).suffix.lower() not in SCRIPT_EXTENSIONS:
            raise ValueError("Supported skill scripts are .py, .ps1, and .js")
        return skill, path, normalized

    def _parse(self, filepath: str) -> Skill:
        with open(filepath, "r", encoding="utf-8") as file:
            text = file.read()
        frontmatter, body = self._parse_frontmatter(text)
        if not frontmatter:
            raise ValueError("missing YAML frontmatter")

        relative = os.path.relpath(filepath, self.skills_dir)
        parts = relative.replace("\\", "/").split("/")
        category = parts[0] if len(parts) >= 2 else "uncategorized"
        name = str(frontmatter.get("name", "")).strip()
        description = str(frontmatter.get("description", "")).strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("name must use lowercase letters, numbers, and hyphens")
        if os.path.basename(os.path.dirname(filepath)) != name:
            raise ValueError("skill directory name must match frontmatter name")
        if not description:
            raise ValueError("description cannot be empty")
        if not body.strip():
            raise ValueError("SKILL.md body cannot be empty")

        metadata = frontmatter.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        sierra = metadata.get("sierra", {})
        sierra = sierra if isinstance(sierra, dict) else {}
        hermes = metadata.get("hermes", {})
        hermes = hermes if isinstance(hermes, dict) else {}
        triggers = _string_list(sierra.get("triggers", frontmatter.get("triggers", [])))
        platforms = _string_list(
            sierra.get("platforms", hermes.get("platforms", frontmatter.get("platforms", [])))
        )
        prerequisites = sierra.get(
            "prerequisites",
            hermes.get("prerequisites", frontmatter.get("prerequisites", {})),
        )
        prerequisites = prerequisites if isinstance(prerequisites, dict) else {}
        absolute_path = os.path.abspath(filepath)
        resources = self._scan_resources(os.path.dirname(absolute_path))
        return Skill(
            name=name,
            description=description,
            triggers=triggers,
            category=category,
            body=body.strip(),
            path=absolute_path,
            frontmatter=frontmatter,
            platforms=platforms,
            prerequisites=prerequisites,
            resources=resources,
        )

    def _scan_resources(self, root_dir: str) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        real_root = os.path.realpath(root_dir)
        for kind in ALLOWED_RESOURCE_DIRS:
            resource_root = os.path.join(root_dir, kind)
            if not os.path.isdir(resource_root) or os.path.islink(resource_root):
                continue
            for root, dirs, files in os.walk(resource_root, followlinks=False):
                dirs[:] = sorted(
                    directory
                    for directory in dirs
                    if not directory.startswith(".") and not os.path.islink(os.path.join(root, directory))
                )
                for filename in sorted(files):
                    if filename.startswith("."):
                        continue
                    path = os.path.join(root, filename)
                    if os.path.islink(path):
                        continue
                    resolved = os.path.realpath(path)
                    if os.path.commonpath([real_root, resolved]) != real_root:
                        continue
                    relative = os.path.relpath(path, root_dir).replace("\\", "/")
                    extension = Path(path).suffix.lower()
                    resources.append({
                        "file_path": relative,
                        "kind": kind,
                        "size": os.path.getsize(path),
                        "readable": extension in TEXT_EXTENSIONS,
                        "executable": kind == "scripts" and extension in SCRIPT_EXTENSIONS,
                    })
        return resources

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        frontmatter = yaml.safe_load(match.group(1)) or {}
        if not isinstance(frontmatter, dict):
            raise ValueError("frontmatter must be a YAML object")
        return frontmatter, match.group(2)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _is_text_file(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


_active_loader: SkillLoader | None = None
_skills_by_name: dict[str, Skill] = {}


def set_skill_loader(loader: SkillLoader | None) -> None:
    global _active_loader
    _active_loader = loader
    set_skills(loader.skills if loader is not None else [])


def get_skill_loader() -> SkillLoader | None:
    return _active_loader


def set_skills(skills: list[Skill]) -> None:
    _skills_by_name.clear()
    for skill in skills:
        _skills_by_name[skill.name] = skill


def get_skill(name: str) -> Skill | None:
    return _skills_by_name.get(str(name).strip())
