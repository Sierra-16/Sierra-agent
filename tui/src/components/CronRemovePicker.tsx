import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";
import type { CronTaskOption } from "../gateway.js";

interface CronRemovePickerProps {
  tasks: CronTaskOption[];
  selectedIndex: number;
  loading?: boolean;
  theme: Theme;
  cols: number;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  if (max <= 3) return value.slice(0, max);
  return `${value.slice(0, max - 3)}...`;
}

function taskLabel(task: CronTaskOption): string {
  return `${task.prompt} · every ${task.interval_minutes} min · ${task.id}`;
}

export const CronRemovePicker: React.FC<CronRemovePickerProps> = ({
  tasks,
  selectedIndex,
  loading = false,
  theme,
  cols,
}) => {
  const width = Math.min(Math.max(50, cols - 8), 88);
  const inner = width - 2;

  return (
    <Box flexDirection="column" paddingLeft={1} paddingRight={1}>
      <Text color={theme.color.border}>{"╭" + "─".repeat(inner) + "╮"}</Text>
      <Text color={theme.color.border}>
        {"│ "}
        <Text color={theme.color.warn}>删除定时提示</Text>
        <Text color={theme.color.muted}>  ↑/↓ 移动  Enter 删除  Esc 取消</Text>
        {" ".repeat(Math.max(0, inner - 41))}
        {"│"}
      </Text>
      {loading && (
        <Text color={theme.color.border}>
          {"│ "}
          <Text color={theme.color.muted}>正在读取定时提示...</Text>
          {" ".repeat(Math.max(0, inner - 21))}
          {"│"}
        </Text>
      )}
      {!loading && tasks.length === 0 && (
        <Text color={theme.color.border}>
          {"│ "}
          <Text color={theme.color.muted}>暂无定时提示</Text>
          {" ".repeat(Math.max(0, inner - 12))}
          {"│"}
        </Text>
      )}
      {!loading && tasks.map((task, index) => {
        const selected = index === selectedIndex;
        const marker = selected ? "❯" : " ";
        const label = `${marker} ${taskLabel(task)}`;
        const visible = truncate(label, inner - 2);

        return (
          <Text color={theme.color.border} key={task.id}>
            {"│ "}
            <Text
              bold={selected}
              color={selected ? "#111827" : theme.color.text}
              backgroundColor={selected ? theme.color.warn : undefined}
            >
              {visible}
              {" ".repeat(Math.max(0, inner - 2 - visible.length))}
            </Text>
            {" │"}
          </Text>
        );
      })}
      <Text color={theme.color.border}>{"╰" + "─".repeat(inner) + "╯"}</Text>
    </Box>
  );
};
