import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";

export interface ModelOption {
  key: string;
  name: string;
  active?: boolean;
}

interface ModelPickerProps {
  models: ModelOption[];
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

export const ModelPicker: React.FC<ModelPickerProps> = ({
  models,
  selectedIndex,
  loading = false,
  theme,
  cols,
}) => {
  const width = Math.min(Math.max(44, cols - 8), 76);
  const inner = width - 2;

  return (
    <Box flexDirection="column" paddingLeft={1} paddingRight={1}>
      <Text color={theme.color.border}>
        {"╭" + "─".repeat(inner) + "╮"}
      </Text>
      <Text color={theme.color.border}>
        {"│ "}
        <Text color={theme.color.gem}>💎 选择模型</Text>
        <Text color={theme.color.muted}>  ↑/↓ 移动  Enter 确认  Esc 取消</Text>
        {" ".repeat(Math.max(0, inner - 37))}
        {"│"}
      </Text>
      {loading && (
        <Text color={theme.color.border}>
          {"│ "}
          <Text color={theme.color.muted}>正在读取模型配置...</Text>
          {" ".repeat(Math.max(0, inner - 21))}
          {"│"}
        </Text>
      )}
      {!loading && models.length === 0 && (
        <Text color={theme.color.border}>
          {"│ "}
          <Text color={theme.color.error}>config.json 中没有可用模型</Text>
          {" ".repeat(Math.max(0, inner - 29))}
          {"│"}
        </Text>
      )}
      {!loading && models.map((model, index) => {
        const selected = index === selectedIndex;
        const marker = selected ? "❯" : " ";
        const active = model.active ? " active" : "";
        const label = `${marker} ${model.key.padEnd(10)} ${model.name}${active}`;
        const visible = truncate(label, inner - 2);

        return (
          <Text color={theme.color.border} key={model.key}>
            {"│ "}
            <Text
              bold={selected}
              color={selected ? "#111827" : model.active ? theme.color.gold : theme.color.text}
              backgroundColor={selected ? theme.color.leaf : undefined}
            >
              {visible}
              {" ".repeat(Math.max(0, inner - 2 - visible.length))}
            </Text>
            {" │"}
          </Text>
        );
      })}
      <Text color={theme.color.border}>
        {"╰" + "─".repeat(inner) + "╯"}
      </Text>
    </Box>
  );
};
