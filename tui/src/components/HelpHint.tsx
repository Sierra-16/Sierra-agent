import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";

interface HelpHintProps {
  theme: Theme;
  cols: number;
}

export const HelpHint: React.FC<HelpHintProps> = ({ theme, cols }) => {
  const width = Math.min(cols - 4, 58);
  const inner = Math.max(24, width - 2);
  const items = [
    ["/help", "查看帮助"],
    ["/quit", "退出 Sierra"],
    ["/new", "开启新对话"],
    ["/list", "查看历史对话"],
    ["/model", "切换模型"],
    ["/mcp", "查看 MCP 连接"],
    ["/skills", "查看技能包"],
    ["/skills-reload", "重新加载技能"],
    ["/skills-stats", "查看技能使用统计"],
    ["/reset", "重置当前对话"],
    ["/compress", "压缩上下文"],
    ["/task", "查看当前任务计划"],
    ["/task-cancel", "放弃当前任务"],
    ["/debug-context", "查看上下文摘要"],
    ["/jobs", "查看后台维护队列"],
    ["/memory", "查看记忆"],
    ["/memory-search <问题>", "语义搜索历史记忆"],
    ["/memory-forget <ID>", "删除指定向量记忆"],
    ["/memory-clear", "清空当前工作区向量记忆"],
    ["/audit", "查看工具审计"],
    ["Ctrl+C", "处理中断，空闲退出"],
    ["Ctrl+D", "强制退出"],
    ["Esc", "清空输入"],
  ];

  return (
    <Box flexDirection="column" paddingLeft={1}>
      <Text color={theme.color.border}>
        {"╭" + "─".repeat(inner) + "╮"}
      </Text>
      <Text color={theme.color.border}>
        {"│ "}
        <Text color={theme.color.leaf}>🍃 Commands</Text>
        {" ".repeat(Math.max(0, inner - 12))}
        {"│"}
      </Text>
      {items.map(([key, desc]) => {
        const keyWidth = 22;
        const contentLength = Math.max(key.length, keyWidth) + desc.length + 3;
        return (
          <Text color={theme.color.border} key={key}>
            {"│ "}
            <Text color={theme.color.accent}>{key.padEnd(keyWidth)}</Text>
            <Text color={theme.color.muted}>- {desc}</Text>
            {" ".repeat(Math.max(0, inner - contentLength))}
            {"│"}
          </Text>
        );
      })}
      <Text color={theme.color.border}>
        {"╰" + "─".repeat(inner) + "╯"}
      </Text>
    </Box>
  );
};
