from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandDef:
    name: str
    description: str
    category: str
    aliases: tuple[str, ...] = ()
    args_hint: str = ""
    requires_argument: bool = False
    discoverable: bool = True

    @property
    def slash(self) -> str:
        return f"/{self.name}"

    @property
    def value(self) -> str:
        return f"{self.slash} " if self.requires_argument or self.args_hint else self.slash

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.slash,
            "value": self.value,
            "description": self.description,
            "detail": self.description,
            "category": self.category,
            "aliases": [f"/{alias}" for alias in self.aliases],
            "args_hint": self.args_hint,
            "requires_argument": self.requires_argument,
        }


COMMAND_REGISTRY: tuple[CommandDef, ...] = (
    CommandDef("help", "查看可用命令", "信息", aliases=("?",)),
    CommandDef("new", "开启一个新对话", "会话"),
    CommandDef("reset", "重置当前对话", "会话"),
    CommandDef("sessions", "查看历史会话", "会话", aliases=("list",)),
    CommandDef("session-search", "搜索历史会话", "会话", args_hint="<关键词>", requires_argument=True),
    CommandDef("session-load", "按 ID 切换会话", "会话", args_hint="<id>", requires_argument=True),
    CommandDef("undo", "撤回最近一轮对话", "会话", args_hint="[n]"),
    CommandDef("retry", "重试上一轮请求", "会话"),
    CommandDef("model", "查看或切换模型", "配置", aliases=("models",), args_hint="[key]"),
    CommandDef("compress", "手动压缩当前会话历史", "会话"),
    CommandDef("memory", "查看记忆状态", "记忆"),
    CommandDef("memory-search", "搜索长期记忆", "记忆", args_hint="<问题>", requires_argument=True),
    CommandDef("memory-forget", "删除指定向量记忆", "记忆", args_hint="<id>", requires_argument=True),
    CommandDef("memory-clear", "清空当前工作区向量记忆", "记忆"),
    CommandDef("task", "查看任务计划与进度", "任务"),
    CommandDef("task-cancel", "放弃当前任务计划", "任务", aliases=("task-abandon",)),
    CommandDef("task-resume", "恢复指定任务计划", "任务", args_hint="<id>", requires_argument=True, discoverable=False),
    CommandDef("jobs", "查看后台任务队列", "任务"),
    CommandDef("cron", "查看定时提醒", "任务"),
    CommandDef("cron-add", "创建定时提醒", "任务", args_hint="<分钟> <内容>", requires_argument=True),
    CommandDef("cron-remove", "删除定时提醒", "任务", args_hint="[id]"),
    CommandDef("mcp", "查看 MCP 连接状态", "能力"),
    CommandDef("plugins", "查看插件状态", "能力"),
    CommandDef("skills", "查看可用技能", "能力"),
    CommandDef("skills-reload", "重新加载技能", "能力"),
    CommandDef("skills-stats", "查看技能使用统计", "能力"),
    CommandDef(
        "reload-config",
        "重新读取 config.json",
        "配置",
        aliases=("config-reload", "reload_config", "config_reload"),
    ),
    CommandDef("debug-context", "查看上下文结构", "信息", aliases=("debug_context",)),
    CommandDef("audit", "查看工具审计日志", "信息"),
    CommandDef("quit", "退出 Sierra", "会话", aliases=("exit",)),
    CommandDef("set-model", "切换模型", "配置", args_hint="<key>", requires_argument=True, discoverable=False),
)


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lstrip("/").replace("_", "-").lower()


_COMMANDS_BY_NAME = {command.name: command for command in COMMAND_REGISTRY}
_ALIASES: dict[str, str] = {}
for _command in COMMAND_REGISTRY:
    for _alias in _command.aliases:
        _ALIASES[_normalize_key(_alias)] = _command.name


def normalize_command_name(value: str) -> str:
    key = _normalize_key(value)
    return _ALIASES.get(key, key)


def resolve_command(value: str) -> CommandDef | None:
    return _COMMANDS_BY_NAME.get(normalize_command_name(value))


def command_catalog(*, include_hidden: bool = False) -> list[dict[str, Any]]:
    return [
        command.as_dict()
        for command in COMMAND_REGISTRY
        if include_hidden or command.discoverable
    ]


def complete_commands(query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    query = _normalize_key(query)
    if query.startswith("/"):
        query = query[1:]
    limit = max(1, min(int(limit or 20), 80))

    matches: list[tuple[int, CommandDef]] = []
    for command in COMMAND_REGISTRY:
        if not command.discoverable:
            continue
        names = [command.name, *command.aliases]
        if not query:
            score = 0
        elif any(name.startswith(query) for name in names):
            score = 0
        elif any(query in name for name in names):
            score = 1
        elif query in command.description.lower():
            score = 2
        else:
            continue
        matches.append((score, command))

    matches.sort(key=lambda item: (item[0], item[1].category, item[1].name))
    return [command.as_dict() for _score, command in matches[:limit]]


def command_help_text() -> str:
    groups: dict[str, list[CommandDef]] = {}
    for command in COMMAND_REGISTRY:
        if not command.discoverable:
            continue
        groups.setdefault(command.category, []).append(command)

    lines = ["Web 可用命令"]
    for category, commands in groups.items():
        lines.append("")
        lines.append(category)
        for command in commands:
            usage = command.slash
            if command.args_hint:
                usage = f"{usage} {command.args_hint}"
            aliases = f"（别名: {', '.join('/' + alias for alias in command.aliases)}）" if command.aliases else ""
            lines.append(f"- {usage}: {command.description}{aliases}")
    return "\n".join(lines)
