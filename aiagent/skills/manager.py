from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Any, Callable

import yaml

from .loader import ALLOWED_RESOURCE_DIRS, MAX_RESOURCE_BYTES, SkillLoader


MAX_SKILL_BYTES = 256 * 1024


class SkillManager:
    """Perform validated skill package mutations inside the configured skills root."""

    def __init__(self, loader: SkillLoader, reload_callback: Callable[[], dict[str, Any]]):
        self.loader = loader
        self.reload_callback = reload_callback

    def execute(
        self,
        action: str,
        name: str,
        category: str | None = None,
        description: str | None = None,
        content: str | None = None,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        action = str(action or "").strip().lower()
        if action == "create":
            result = self.create(name, category, description, content)
        elif action == "update":
            result = self.update(name, description, content)
        elif action == "write_resource":
            result = self.write_resource(name, file_path, content)
        elif action == "remove_resource":
            result = self.remove_resource(name, file_path)
        elif action == "delete":
            result = self.delete(name)
        else:
            raise ValueError(
                "action must be create, update, write_resource, remove_resource, or delete"
            )
        result["reload"] = self.reload_callback()
        return result

    def create(
        self,
        name: str,
        category: str | None,
        description: str | None,
        content: str | None,
    ) -> dict[str, Any]:
        name = self._validate_name(name)
        category = self._validate_category(category)
        description = str(description or "").strip()
        body = str(content or "").strip()
        if not description:
            raise ValueError("description is required when creating a skill")
        if not body:
            raise ValueError("content is required when creating a skill")
        if self.loader.get(name) is not None:
            raise ValueError(f"Skill already exists: {name}")

        skill_dir = self._new_skill_dir(category, name)
        if os.path.exists(skill_dir):
            raise ValueError(f"Skill directory already exists: {skill_dir}")
        os.makedirs(skill_dir, exist_ok=False)
        try:
            path = os.path.join(skill_dir, "SKILL.md")
            self._write_text(path, self._document(name, description, body), MAX_SKILL_BYTES)
        except Exception:
            shutil.rmtree(skill_dir, ignore_errors=True)
            raise
        return {"ok": True, "action": "create", "name": name, "path": path}

    def update(
        self,
        name: str,
        description: str | None,
        content: str | None,
    ) -> dict[str, Any]:
        skill = self._require_skill(name)
        new_description = skill.description if description is None else str(description).strip()
        new_body = skill.body if content is None else str(content).strip()
        if not new_description:
            raise ValueError("description cannot be empty")
        if not new_body:
            raise ValueError("content cannot be empty")
        document = self._document(
            skill.name,
            new_description,
            new_body,
            extra_frontmatter=skill.frontmatter,
        )
        self._write_text(skill.path, document, MAX_SKILL_BYTES)
        return {"ok": True, "action": "update", "name": skill.name, "path": skill.path}

    def write_resource(
        self,
        name: str,
        file_path: str | None,
        content: str | None,
    ) -> dict[str, Any]:
        skill = self._require_skill(name)
        target, normalized = self._resource_target(skill.root_dir, file_path)
        self._write_text(target, str(content or ""), MAX_RESOURCE_BYTES)
        return {
            "ok": True,
            "action": "write_resource",
            "name": skill.name,
            "file_path": normalized,
            "path": target,
        }

    def remove_resource(self, name: str, file_path: str | None) -> dict[str, Any]:
        skill = self._require_skill(name)
        target, normalized = self._resource_target(skill.root_dir, file_path)
        if not os.path.isfile(target):
            raise FileNotFoundError(f"Skill resource not found: {normalized}")
        os.remove(target)
        self._remove_empty_resource_parents(os.path.dirname(target), skill.root_dir)
        return {
            "ok": True,
            "action": "remove_resource",
            "name": skill.name,
            "file_path": normalized,
        }

    def delete(self, name: str) -> dict[str, Any]:
        skill = self._require_skill(name)
        root = os.path.realpath(self.loader.skills_dir)
        target = os.path.realpath(skill.root_dir)
        if target == root or os.path.commonpath([root, target]) != root:
            raise ValueError("Refusing to delete a path outside the skills directory")
        shutil.rmtree(target)
        return {"ok": True, "action": "delete", "name": skill.name, "path": target}

    def _new_skill_dir(self, category: str, name: str) -> str:
        root = os.path.realpath(self.loader.skills_dir)
        target = os.path.realpath(os.path.join(root, category, name))
        if os.path.commonpath([root, target]) != root or target == root:
            raise ValueError("Skill path escapes the skills directory")
        return target

    def _resource_target(self, skill_dir: str, file_path: str | None) -> tuple[str, str]:
        normalized = str(file_path or "").strip().replace("\\", "/")
        if not normalized:
            raise ValueError("file_path is required")
        if os.path.isabs(normalized) or os.path.splitdrive(normalized)[0]:
            raise ValueError("Absolute resource paths are not allowed")
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        if not parts or parts[0] not in ALLOWED_RESOURCE_DIRS:
            raise ValueError(
                "Resource must be inside references/, templates/, scripts/, or assets/"
            )
        if any(part == ".." for part in parts):
            raise ValueError("Parent path traversal is not allowed")

        root = os.path.realpath(skill_dir)
        target = os.path.realpath(os.path.join(root, *parts))
        if os.path.commonpath([root, target]) != root:
            raise ValueError("Resource path escapes the skill directory")
        return target, "/".join(parts)

    def _require_skill(self, name: str):
        name = self._validate_name(name)
        skill = self.loader.get(name)
        if skill is None:
            raise KeyError(f"Unknown skill: {name}")
        return skill

    @staticmethod
    def _validate_name(name: str) -> str:
        name = str(name or "").strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("name must use lowercase letters, numbers, and hyphens")
        return name

    @staticmethod
    def _validate_category(category: str | None) -> str:
        category = str(category or "").strip()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", category):
            raise ValueError("category must use lowercase letters, numbers, and hyphens")
        return category

    @staticmethod
    def _document(
        name: str,
        description: str,
        body: str,
        extra_frontmatter: dict[str, Any] | None = None,
    ) -> str:
        frontmatter = dict(extra_frontmatter or {})
        frontmatter["name"] = name
        frontmatter["description"] = description
        ordered = {
            "name": frontmatter.pop("name"),
            "description": frontmatter.pop("description"),
            **frontmatter,
        }
        yaml_text = yaml.safe_dump(
            ordered,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip()
        return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"

    @staticmethod
    def _write_text(path: str, content: str, max_bytes: int) -> None:
        encoded = content.encode("utf-8")
        if len(encoded) > max_bytes:
            raise ValueError(f"Content exceeds {max_bytes} bytes")
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".sierra-skill-", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _remove_empty_resource_parents(directory: str, skill_dir: str) -> None:
        resource_roots = {
            os.path.realpath(os.path.join(skill_dir, kind))
            for kind in ALLOWED_RESOURCE_DIRS
        }
        current = os.path.realpath(directory)
        while any(
            current == root or os.path.commonpath([root, current]) == root
            for root in resource_roots
        ):
            try:
                os.rmdir(current)
            except OSError:
                break
            if current in resource_roots:
                break
            current = os.path.dirname(current)
