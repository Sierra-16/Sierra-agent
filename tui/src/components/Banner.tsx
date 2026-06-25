import React from "react";
import { Box, Text } from "ink";
import { Theme, SIERRA_LOGO } from "../theme.js";
import { SierraSprite } from "./SierraSprite.js";

interface BannerProps {
  cols: number;
  model: string;
  cwd: string;
  lastQuery: string;
  theme: Theme;
}

const VERSION = "v0.1.0";
const WIDE_HERO_MIN = 86;

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  if (max <= 3) return value.slice(0, max);
  return `${value.slice(0, max - 3)}...`;
}

function shortModel(model: string): string {
  return model
    .split("/")
    .pop()!
    .replace(/[-_]/g, " ")
    .trim();
}

const Line: React.FC<{
  theme: Theme;
  children: React.ReactNode;
}> = ({ theme, children }) => (
  <Box flexDirection="row">
    <Text color={theme.color.border}>│ </Text>
    <Box flexGrow={1}>{children}</Box>
    <Text color={theme.color.border}> │</Text>
  </Box>
);

export const Banner: React.FC<BannerProps> = ({
  cols,
  model,
  cwd,
  lastQuery,
  theme,
}) => {
  const isWide = cols >= WIDE_HERO_MIN;
  const cwdLabel = truncate(cwd || process.cwd(), Math.max(16, cols - 14));
  const lastLabel = truncate(lastQuery, Math.max(16, cols - 14));
  const ruleW = Math.max(0, cols - 2);

  return (
    <Box flexDirection="column" width={cols}>
      <Text> </Text>
      {SIERRA_LOGO.map((line, index) => (
        <Text color={theme.color.logo[index] || theme.color.primary} key={line}>
          {line}
        </Text>
      ))}

      <Text> </Text>
      <Box
        flexDirection={isWide ? "row" : "column"}
        paddingLeft={2}
        paddingRight={2}
      >
        <SierraSprite name="idle" fallbackName="think-idle" />
        <Box
          flexDirection="column"
          flexShrink={1}
          marginLeft={isWide ? 4 : 0}
          marginTop={isWide ? 1 : 1}
        >
          <Text>
            <Text color={theme.color.leaf}>🧝 </Text>
            <Text bold color={theme.color.primary}>
              Sierra AI Agent
            </Text>
            <Text color={theme.color.muted}> {VERSION}</Text>
          </Text>
          <Text>
            <Text color={theme.color.leaf}>🍃 </Text>
            <Text color={theme.color.text}>Ready</Text>
          </Text>
        </Box>
      </Box>

      <Text> </Text>
      <Text color={theme.color.border}>
        {"╭" + "─".repeat(ruleW) + "╮"}
      </Text>

      <Line theme={theme}>
        <Text>
          <Text color={theme.color.label}>Model </Text>
          <Text color={theme.color.text}>{shortModel(model)}</Text>
        </Text>
      </Line>

      <Line theme={theme}>
        <Text>
          <Text color={theme.color.label}>CWD   </Text>
          <Text color={theme.color.text}>{cwdLabel}</Text>
        </Text>
      </Line>

      {lastQuery && (
        <Line theme={theme}>
          <Text>
            <Text color={theme.color.label}>Last  </Text>
            <Text color={theme.color.text}>{lastLabel}</Text>
          </Text>
        </Line>
      )}

      <Line theme={theme}>
        <Text>
          <Text color={theme.color.label}>Help  </Text>
          <Text color={theme.color.accent}>/help</Text>
          <Text color={theme.color.muted}> 查看命令    Ctrl+C 退出</Text>
        </Text>
      </Line>

      <Text color={theme.color.border}>
        {"╰" + "─".repeat(ruleW) + "╯"}
      </Text>
    </Box>
  );
};
