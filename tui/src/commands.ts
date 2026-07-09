export interface CommandDefinition {
  cmd: string;
  desc: string;
  category?: string;
  aliases?: string[];
  argsHint?: string;
  requiresArg?: boolean;
}

export const FALLBACK_COMMANDS: CommandDefinition[] = [
  { cmd: "/help", desc: "查看可用命令", category: "信息", aliases: ["/?"] },
  { cmd: "/new", desc: "开启一个新对话", category: "会话" },
  { cmd: "/reset", desc: "重置当前对话", category: "会话" },
  { cmd: "/sessions", desc: "查看历史会话", category: "会话", aliases: ["/list"] },
  { cmd: "/session-search", desc: "搜索历史会话", category: "会话", argsHint: "<关键词>", requiresArg: true },
  { cmd: "/session-load", desc: "按 ID 切换会话", category: "会话", argsHint: "<id>", requiresArg: true },
  { cmd: "/undo", desc: "撤回最近一轮对话", category: "会话", argsHint: "[n]" },
  { cmd: "/retry", desc: "重试上一轮请求", category: "会话" },
  { cmd: "/model", desc: "查看或切换模型", category: "配置", aliases: ["/models"], argsHint: "[key]" },
  { cmd: "/compress", desc: "手动压缩当前会话历史", category: "会话" },
  { cmd: "/memory", desc: "查看记忆状态", category: "记忆" },
  { cmd: "/memory-search", desc: "搜索长期记忆", category: "记忆", argsHint: "<问题>", requiresArg: true },
  { cmd: "/memory-forget", desc: "删除指定向量记忆", category: "记忆", argsHint: "<id>", requiresArg: true },
  { cmd: "/memory-clear", desc: "清空当前工作区向量记忆", category: "记忆" },
  { cmd: "/task", desc: "查看任务计划与进度", category: "任务" },
  { cmd: "/task-cancel", desc: "放弃当前任务计划", category: "任务", aliases: ["/task-abandon"] },
  { cmd: "/jobs", desc: "查看后台任务队列", category: "任务" },
  { cmd: "/cron", desc: "查看定时提醒", category: "任务" },
  { cmd: "/cron-add", desc: "创建定时提醒", category: "任务", argsHint: "<分钟> <内容>", requiresArg: true },
  { cmd: "/cron-remove", desc: "删除定时提醒", category: "任务", argsHint: "[id]" },
  { cmd: "/mcp", desc: "查看 MCP 连接状态", category: "能力" },
  { cmd: "/plugins", desc: "查看插件状态", category: "能力" },
  { cmd: "/skills", desc: "查看可用技能", category: "能力" },
  { cmd: "/skills-reload", desc: "重新加载技能", category: "能力" },
  { cmd: "/skills-stats", desc: "查看技能使用统计", category: "能力" },
  {
    cmd: "/reload-config",
    desc: "重新读取 config.json",
    category: "配置",
    aliases: ["/config-reload", "/reload_config", "/config_reload"],
  },
  { cmd: "/debug-context", desc: "查看上下文结构", category: "信息", aliases: ["/debug_context"] },
  { cmd: "/audit", desc: "查看工具审计日志", category: "信息" },
  { cmd: "/quit", desc: "退出 Sierra", category: "会话", aliases: ["/exit"] },
];

export function normalizeCommandCatalog(items: unknown): CommandDefinition[] {
  if (!Array.isArray(items)) return FALLBACK_COMMANDS;

  const parsed = items
    .map((item) => normalizeCommandItem(item))
    .filter((item): item is CommandDefinition => item !== null);

  return parsed.length > 0 ? parsed : FALLBACK_COMMANDS;
}

export function filterCommandHints(
  input: string,
  commands: CommandDefinition[],
): CommandDefinition[] {
  if (!input.startsWith("/") || input.includes(" ")) return [];
  const query = slashKey(input);
  return commands.filter((command) => commandMatches(command, query));
}

export function resolveSlashCommand(
  commandText: string,
  commands: CommandDefinition[],
): string {
  const query = slashKey(commandText);
  for (const command of commands) {
    if (slashKey(command.cmd) === query) return command.cmd;
    if ((command.aliases || []).some((alias) => slashKey(alias) === query)) {
      return command.cmd;
    }
  }
  return commandText.startsWith("/") ? commandText : `/${commandText}`;
}

export function formatCommandHelp(commands: CommandDefinition[]): string {
  const groups = new Map<string, CommandDefinition[]>();
  for (const command of commands) {
    const category = command.category || "其他";
    const bucket = groups.get(category) || [];
    bucket.push(command);
    groups.set(category, bucket);
  }

  const lines = ["可用命令"];
  for (const [category, items] of groups) {
    lines.push("");
    lines.push(category);
    for (const item of items) {
      const usage = item.argsHint ? `${item.cmd} ${item.argsHint}` : item.cmd;
      const aliases = item.aliases?.length
        ? `（别名 ${item.aliases.join(", ")}）`
        : "";
      lines.push(`- ${usage}: ${item.desc}${aliases}`);
    }
  }
  return lines.join("\n");
}

function normalizeCommandItem(item: unknown): CommandDefinition | null {
  if (!item || typeof item !== "object") return null;
  const raw = item as Record<string, unknown>;
  const cmd = slash(String(raw.cmd || raw.label || raw.name || "").trim());
  if (!cmd || cmd === "/") return null;

  const aliases = Array.isArray(raw.aliases)
    ? raw.aliases
        .map((alias) => slash(String(alias || "").trim()))
        .filter((alias) => alias && alias !== "/")
    : [];

  return {
    cmd,
    desc: String(raw.desc || raw.description || raw.detail || "").trim(),
    category: String(raw.category || "").trim() || undefined,
    aliases,
    argsHint: String(raw.argsHint || raw.args_hint || "").trim() || undefined,
    requiresArg: Boolean(raw.requiresArg || raw.requires_argument),
  };
}

function commandMatches(command: CommandDefinition, query: string): boolean {
  if (!query) return true;
  if (slashKey(command.cmd).startsWith(query)) return true;
  return (command.aliases || []).some((alias) => slashKey(alias).startsWith(query));
}

function slash(value: string): string {
  if (!value) return "";
  return value.startsWith("/") ? value : `/${value}`;
}

function slashKey(value: string): string {
  return value.trim().replace(/^\/+/, "").replace(/_/g, "-").toLowerCase();
}
