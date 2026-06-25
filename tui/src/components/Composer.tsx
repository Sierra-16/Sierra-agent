import React from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { Theme } from "../theme.js";

export interface CommandDefinition {
  cmd: string;
  desc: string;
  requiresArg?: boolean;
}

export const COMMANDS: CommandDefinition[] = [
  { cmd: "/help", desc: "查看命令" },
  { cmd: "/quit", desc: "退出 Sierra" },
  { cmd: "/new", desc: "新对话" },
  { cmd: "/list", desc: "对话列表" },
  { cmd: "/sessions", desc: "历史会话库" },
  { cmd: "/session-search", desc: "搜索历史会话", requiresArg: true },
  { cmd: "/session-load", desc: "加载历史会话", requiresArg: true },
  { cmd: "/model", desc: "切换模型" },
  { cmd: "/mcp", desc: "查看 MCP 状态" },
  { cmd: "/skills", desc: "查看技能包" },
  { cmd: "/skills-reload", desc: "重新加载技能" },
  { cmd: "/skills-stats", desc: "查看技能使用统计" },
  { cmd: "/reset", desc: "重置当前对话" },
  { cmd: "/compress", desc: "压缩上下文" },
  { cmd: "/task", desc: "查看任务计划" },
  { cmd: "/task-cancel", desc: "放弃当前任务" },
  { cmd: "/companion", desc: "查看陪伴状态" },
  { cmd: "/memory", desc: "查看记忆状态" },
  { cmd: "/memory-search", desc: "语义搜索记忆", requiresArg: true },
  { cmd: "/memory-forget", desc: "删除指定记忆", requiresArg: true },
  { cmd: "/memory-clear", desc: "清空向量记忆" },
  { cmd: "/audit", desc: "查看工具审计" },
];

const HINT_W = 42;

interface ComposerProps {
  cols: number;
  input: string;
  busy: boolean;
  theme: Theme;
  hints: { cmd: string; desc: string }[];
  hintIdx: number;
  onChange: (v: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
}

export const Composer: React.FC<ComposerProps> = ({
  input,
  busy,
  theme,
  hints,
  hintIdx,
  onChange,
  onSubmit,
  placeholder,
}) => {
  const safeIdx = Math.min(hintIdx, Math.max(0, hints.length - 1));

  return (
    <Box flexDirection="column" paddingLeft={1} paddingRight={1}>
      {hints.length > 0 && (
        <Box flexDirection="column" marginBottom={1}>
          <Text color={theme.color.border}>
            {"╭" + "─".repeat(HINT_W - 2) + "╮"}
          </Text>
          {hints.map((hint, index) => {
            const selected = index === safeIdx;
            const content = `${hint.cmd.padEnd(18)}${hint.desc}`;
            const pad = Math.max(0, HINT_W - content.length - 3);

            return (
              <Text color={theme.color.border} key={hint.cmd}>
                {"│ "}
                <Text
                  bold={selected}
                  color={selected ? "#111827" : theme.color.accent}
                  backgroundColor={selected ? theme.color.gold : undefined}
                >
                  {content}
                  {" ".repeat(pad)}
                </Text>
                <Text color={theme.color.border}>│</Text>
              </Text>
            );
          })}
          <Text color={theme.color.border}>
            {"╰" + "─".repeat(HINT_W - 2) + "╯"}
          </Text>
        </Box>
      )}

      <Box flexDirection="row">
        <Text color={theme.color.leaf}>🍃 </Text>
        <Text bold color={theme.color.prompt}>
          {theme.brand.prompt}{" "}
        </Text>
        <TextInput
          value={input}
          onChange={onChange}
          onSubmit={onSubmit}
          focus={!busy}
          placeholder={placeholder || (busy ? "Sierra 正在处理..." : theme.brand.welcome)}
        />
      </Box>
    </Box>
  );
};
