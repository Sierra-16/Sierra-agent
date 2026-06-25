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
  const title = `Tool approval · ${request.risk}`;
  const toolName = clip(request.name, inner - 2);
  const reason = clip(request.reason, inner - 2);
  const args = (request.arguments || "{}").split("\n").slice(0, 8);
  const actionHintWidth = 27;

  return (
    <Box flexDirection="column" paddingLeft={1} marginBottom={1}>
      <Text color={theme.color.warn}>
        {"╭" + "─".repeat(inner) + "╮"}
      </Text>
      <Text color={theme.color.warn}>
        {"│ "}
        <Text bold color={theme.color.warn}>{title}</Text>
        {" ".repeat(Math.max(0, inner - title.length - 1))}
        {"│"}
      </Text>
      <Text color={theme.color.warn}>
        {"│ "}
        <Text color={theme.color.gem}>{toolName}</Text>
        {" ".repeat(Math.max(0, inner - toolName.length - 1))}
        {"│"}
      </Text>
      <Text color={theme.color.warn}>
        {"│ "}
        <Text color={theme.color.muted}>{reason}</Text>
        {" ".repeat(Math.max(0, inner - reason.length - 1))}
        {"│"}
      </Text>
      {args.map((line, index) => {
        const clipped = clip(line, inner - 2);
        return (
          <Text color={theme.color.warn} key={`${index}-${line}`}>
            {"│ "}
            <Text color={theme.color.text}>{clipped}</Text>
            {" ".repeat(Math.max(0, inner - clipped.length - 1))}
            {"│"}
          </Text>
        );
      })}
      <Text color={theme.color.warn}>
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
      <Text color={theme.color.warn}>
        {"╰" + "─".repeat(inner) + "╯"}
      </Text>
    </Box>
  );
};

function clip(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return value.slice(0, Math.max(0, maxLength - 3)) + "...";
}
