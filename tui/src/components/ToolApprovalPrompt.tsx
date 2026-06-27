import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";
import type { ToolApprovalRequest } from "../hooks/useMainApp.js";

interface ToolApprovalPromptProps {
  request: ToolApprovalRequest;
  theme: Theme;
  cols: number;
}

export const ToolApprovalPrompt: React.FC<ToolApprovalPromptProps> = ({
  request,
  theme,
  cols,
}) => {
  const width = Math.min(cols - 4, 88);
  const inner = Math.max(36, width - 2);
  const risk = riskMeta(request.risk, theme);
  const group = toolGroup(request.name);
  const title = `${risk.icon} Tool approval · ${risk.label}`;
  const toolName = clip(request.name, inner - 2);
  const reason = clip(request.reason, inner - 2);
  const description = clip(`${group} · ${risk.description}`, inner - 2);
  const args = (request.arguments || "{}").split("\n").slice(0, 8);
  const actionHintWidth = 27;

  return (
    <Box flexDirection="column" paddingLeft={1} marginBottom={1}>
      <Text color={risk.color}>
        {"╭" + "─".repeat(inner) + "╮"}
      </Text>
      <Text color={risk.color}>
        {"│ "}
        <Text bold color={risk.color}>{title}</Text>
        {" ".repeat(Math.max(0, inner - title.length - 1))}
        {"│"}
      </Text>
      <Text color={risk.color}>
        {"│ "}
        <Text color={theme.color.gem}>{toolName}</Text>
        {" ".repeat(Math.max(0, inner - toolName.length - 1))}
        {"│"}
      </Text>
      <Text color={risk.color}>
        {"│ "}
        <Text color={theme.color.text}>{description}</Text>
        {" ".repeat(Math.max(0, inner - description.length - 1))}
        {"│"}
      </Text>
      <Text color={risk.color}>
        {"│ "}
        <Text color={theme.color.muted}>{reason}</Text>
        {" ".repeat(Math.max(0, inner - reason.length - 1))}
        {"│"}
      </Text>
      {args.map((line, index) => {
        const clipped = clip(line, inner - 2);
        return (
          <Text color={risk.color} key={`${index}-${line}`}>
            {"│ "}
            <Text color={theme.color.text}>{clipped}</Text>
            {" ".repeat(Math.max(0, inner - clipped.length - 1))}
            {"│"}
          </Text>
        );
      })}
      <Text color={risk.color}>
        {"│ "}
        <Text color={theme.color.leaf}>Y</Text>
        <Text color={theme.color.muted}> once   </Text>
        <Text color={theme.color.gem}>A</Text>
        <Text color={theme.color.muted}> session   </Text>
        <Text color={theme.color.error}>N</Text>
        <Text color={theme.color.muted}> deny</Text>
        {" ".repeat(Math.max(0, inner - actionHintWidth - 1))}
        {"│"}
      </Text>
      <Text color={risk.color}>
        {"╰" + "─".repeat(inner) + "╯"}
      </Text>
    </Box>
  );
};

function clip(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return value.slice(0, Math.max(0, maxLength - 3)) + "...";
}

function riskMeta(risk: string, theme: Theme) {
  if (risk === "high") {
    return {
      icon: "!",
      label: "high risk",
      color: theme.color.error,
      description: "可能修改文件、执行命令、删除数据或影响外部服务",
    };
  }
  if (risk === "medium") {
    return {
      icon: "◆",
      label: "medium risk",
      color: theme.color.warn,
      description: "会修改 Sierra 状态，或访问能力不完全明确",
    };
  }
  return {
    icon: "·",
    label: "low risk",
    color: theme.color.leaf,
    description: "只读或本地低风险操作",
  };
}

function toolGroup(name: string): string {
  if (name.startsWith("mcp__")) return "MCP 外部工具";
  if (name.includes("memory")) return "记忆工具";
  if (name.startsWith("skill_")) return "Skill 工具";
  if (name.startsWith("cron_") || name.includes("plan") || name.includes("task")) return "系统工具";
  if (name.includes("file") || name.includes("directory") || name === "search_files") return "文件工具";
  if (name.includes("web") || name.includes("browser")) return "网页工具";
  if (name === "powershell") return "Shell 工具";
  return "工具";
}
