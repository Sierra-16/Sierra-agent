from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Iterable

import yaml

from .loader import Skill


PLATFORM_ALIASES = {
    "darwin": "macos",
    "linux": "linux",
    "mac": "macos",
    "macos": "macos",
    "osx": "macos",
    "win32": "windows",
    "windows": "windows",
}


@dataclass(frozen=True)
class SkillReadiness:
    offered: bool
    status: str
    reason: str = ""
    missing_commands: tuple[str, ...] = ()
    missing_environment_variables: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "offered": self.offered,
            "readiness_status": self.status,
            "readiness_reason": self.reason or None,
            "missing_required_commands": list(self.missing_commands),
            "missing_required_environment_variables": list(
                self.missing_environment_variables
            ),
        }


class SkillPromptIndex:
    """Render a Hermes-style compact skill index and evaluate offer-time rules."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config if isinstance(config, dict) else {}
        self.disabled = {
            str(name).strip()
            for name in config.get("disabled", [])
            if str(name).strip()
        }
        self.compact_categories = {
            str(category).strip()
            for category in config.get("compact_categories", [])
            if str(category).strip()
        }
        self.active_environments = {
            str(environment).strip().lower()
            for environment in config.get("active_environments", [])
            if str(environment).strip()
        }
        self.description_max_chars = max(
            80,
            min(1000, int(config.get("description_max_chars", 280) or 280)),
        )
        self.max_prompt_chars = max(
            2500,
            int(config.get("max_prompt_chars", 9000) or 9000),
        )
        self.platform = _normalize_platform(
            str(config.get("platform") or sys.platform)
        )
        self._cache_key: tuple[Any, ...] | None = None
        self._cache_value = ""

    def clear_cache(self) -> None:
        self._cache_key = None
        self._cache_value = ""

    def readiness(
        self,
        skill: Skill,
        available_tools: Iterable[str] | None = None,
    ) -> SkillReadiness:
        if skill.name in self.disabled:
            return SkillReadiness(False, "disabled", "disabled in config.json")

        supported_platforms = {
            _normalize_platform(platform)
            for platform in skill.platforms
            if str(platform).strip()
        }
        if supported_platforms and self.platform not in supported_platforms:
            return SkillReadiness(
                False,
                "unsupported",
                f"requires platform: {', '.join(sorted(supported_platforms))}",
            )

        required_environments = {
            str(value).strip().lower()
            for value in _skill_environments(skill)
            if str(value).strip()
        }
        if (
            required_environments
            and self.active_environments
            and required_environments.isdisjoint(self.active_environments)
        ):
            return SkillReadiness(
                False,
                "environment_mismatch",
                f"requires environment: {', '.join(sorted(required_environments))}",
            )

        tools = set(available_tools or [])
        conditions = _skill_conditions(skill)
        required_tools = _string_list(conditions.get("requires_tools"))
        missing_tools = sorted(tool for tool in required_tools if tool not in tools)
        if missing_tools:
            return SkillReadiness(
                False,
                "condition_unmet",
                f"missing tools: {', '.join(missing_tools)}",
            )
        fallback_for = _string_list(conditions.get("fallback_for_tools"))
        available_primary = sorted(tool for tool in fallback_for if tool in tools)
        if available_primary:
            return SkillReadiness(
                False,
                "fallback_not_needed",
                f"primary tools available: {', '.join(available_primary)}",
            )

        required_commands = _prerequisite_values(
            skill.prerequisites,
            "commands",
            "required_commands",
        )
        required_env = _prerequisite_values(
            skill.prerequisites,
            "env",
            "environment_variables",
            "required_environment_variables",
        )
        missing_commands = tuple(
            sorted(command for command in required_commands if shutil.which(command) is None)
        )
        missing_environment = tuple(
            sorted(name for name in required_env if not os.environ.get(name))
        )
        if missing_commands or missing_environment:
            return SkillReadiness(
                True,
                "setup_needed",
                "skill prerequisites are not fully configured",
                missing_commands=missing_commands,
                missing_environment_variables=missing_environment,
            )
        return SkillReadiness(True, "available")

    def offered_skills(
        self,
        skills: Iterable[Skill],
        available_tools: Iterable[str] | None = None,
    ) -> list[Skill]:
        tools = set(available_tools or [])
        return [skill for skill in skills if self.readiness(skill, tools).offered]

    def summaries(
        self,
        skills: Iterable[Skill],
        available_tools: Iterable[str] | None = None,
        include_unavailable: bool = False,
    ) -> list[dict[str, Any]]:
        tools = set(available_tools or [])
        result = []
        for skill in skills:
            readiness = self.readiness(skill, tools)
            if not include_unavailable and not readiness.offered:
                continue
            summary = skill.summary()
            summary.update(readiness.as_dict())
            result.append(summary)
        return result

    def build(
        self,
        skills: Iterable[Skill],
        available_tools: Iterable[str] | None = None,
    ) -> str:
        skill_list = list(skills)
        tools = set(available_tools or [])
        cache_key = (
            tuple(
                (
                    skill.name,
                    skill.description,
                    skill.category,
                    tuple(skill.platforms),
                    repr(skill.prerequisites),
                    repr(_skill_conditions(skill)),
                )
                for skill in skill_list
            ),
            tuple(sorted(tools)),
            tuple(sorted(self.disabled)),
            tuple(sorted(self.compact_categories)),
            tuple(sorted(self.active_environments)),
            self.platform,
            self.description_max_chars,
            self.max_prompt_chars,
        )
        if cache_key == self._cache_key:
            return self._cache_value

        categories: dict[str, list[Skill]] = {}
        for skill in skill_list:
            if self.readiness(skill, tools).offered:
                categories.setdefault(skill.category, []).append(skill)
        if not categories:
            result = ""
        else:
            auto_compact: set[str] = set()

            def render(auto_compact_categories: set[str]) -> str:
                lines = []
                for category in sorted(categories):
                    category_skills = sorted(categories[category], key=lambda item: item.name)
                    if (
                        _category_is_compact(category, self.compact_categories)
                        or category in auto_compact_categories
                    ):
                        names = ", ".join(skill.name for skill in category_skills)
                        lines.append(f"  [category: {category}] [names only]: {names}")
                        continue
                    description = _category_description(category_skills)
                    lines.append(
                        f"  [category: {category}]" + (f" {description}" if description else "")
                    )
                    for skill in category_skills:
                        skill_description = _single_line(skill.description)
                        if len(skill_description) > self.description_max_chars:
                            skill_description = skill_description[: self.description_max_chars - 3] + "..."
                        lines.append(f"    - {skill.name}: {skill_description}")

                compacted = bool(self.compact_categories or auto_compact_categories)
                compact_note = ""
                if compacted:
                    compact_note = (
                        "\nCategories marked [names only] remain loadable; their descriptions are "
                        "omitted to reduce context usage."
                    )
                return (
                    "# Skills (mandatory)\n"
                    "Before replying or calling any non-Skill tool, scan the compact index below. "
                    "If a skill matches or is even partially relevant, you MUST call "
                    "skill_view(name='<exact-skill-name>') first and follow its instructions. "
                    "Category labels are navigation headings, never Skill names. Only identifiers "
                    "listed after '-' or inside a [names only] list are valid Skill names. "
                    "Do not call terminal, PowerShell, file, web, or MCP tools before loading a "
                    "relevant Skill. "
                    "Never skip a matching Skill because the task seems easy or because a general "
                    "tool could handle it; the Skill defines Sierra's preferred workflow and quality checks. "
                    "The index contains metadata only; full instructions and linked resources use "
                    "progressive disclosure. Only proceed without loading a skill when none are relevant.\n"
                    "<available_skills>\n"
                    + "\n".join(lines)
                    + "\n</available_skills>"
                    + compact_note
                )

            result = render(auto_compact)
            if len(result) > self.max_prompt_chars:
                category_lengths = []
                for category, category_skills in categories.items():
                    if _category_is_compact(category, self.compact_categories):
                        continue
                    described = render(auto_compact)
                    auto_compact.add(category)
                    compacted = render(auto_compact)
                    auto_compact.remove(category)
                    category_lengths.append((len(described) - len(compacted), category))
                for _, category in sorted(category_lengths, reverse=True):
                    if len(result) <= self.max_prompt_chars:
                        break
                    auto_compact.add(category)
                    result = render(auto_compact)

        self._cache_key = cache_key
        self._cache_value = result
        return result


def _normalize_platform(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return PLATFORM_ALIASES.get(normalized, normalized)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _prerequisite_values(prerequisites: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        if key in prerequisites:
            return _string_list(prerequisites.get(key))
    return []


def _skill_conditions(skill: Skill) -> dict[str, Any]:
    frontmatter = skill.frontmatter if isinstance(skill.frontmatter, dict) else {}
    metadata = frontmatter.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    sierra = metadata.get("sierra", {})
    sierra = sierra if isinstance(sierra, dict) else {}
    conditions = sierra.get("conditions", frontmatter.get("conditions", {}))
    return conditions if isinstance(conditions, dict) else {}


def _skill_environments(skill: Skill) -> list[str]:
    frontmatter = skill.frontmatter if isinstance(skill.frontmatter, dict) else {}
    metadata = frontmatter.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    sierra = metadata.get("sierra", {})
    sierra = sierra if isinstance(sierra, dict) else {}
    return _string_list(
        sierra.get("environments", frontmatter.get("environments", []))
    )


def _category_is_compact(category: str, compact_categories: set[str]) -> bool:
    top_level = category.split("/", 1)[0]
    return category in compact_categories or top_level in compact_categories


def _category_description(skills: list[Skill]) -> str:
    if not skills:
        return ""
    category = skills[0].category
    skills_root = os.path.dirname(os.path.dirname(skills[0].root_dir))
    path = os.path.join(skills_root, category, "DESCRIPTION.md")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as file:
            text = file.read()
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                frontmatter = yaml.safe_load(parts[1]) or {}
                if isinstance(frontmatter, dict) and frontmatter.get("description"):
                    return _single_line(str(frontmatter["description"]))
        for line in text.splitlines():
            candidate = line.strip().lstrip("#").strip()
            if candidate:
                return candidate
    except (OSError, UnicodeError, yaml.YAMLError):
        return ""
    return ""


def _single_line(value: str) -> str:
    return " ".join(str(value).split())
