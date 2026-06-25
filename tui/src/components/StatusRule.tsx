import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";

interface StatusRuleProps {
  cols: number;
  model: string;
  busy: boolean;
  statusText: string;
  contextTokens: number;
  contextWindow: number;
  contextEstimated: boolean;
  cwd: string;
  theme: Theme;
}

function shortModel(model: string): string {
  return model
    .split("/")
    .pop()!
    .replace(/[-_]/g, " ")
    .trim();
}

function truncateStart(value: string, max: number): string {
  if (value.length <= max) return value;
  if (max <= 3) return value.slice(-max);
  return `...${value.slice(value.length - max + 3)}`;
}

function formatTokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}m`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return Math.max(0, value).toLocaleString();
}

export const StatusRule: React.FC<StatusRuleProps> = ({
  cols,
  model,
  busy,
  statusText,
  contextTokens,
  contextWindow,
  contextEstimated,
  cwd,
  theme,
}) => {
  const modelText = shortModel(model);
  const contextPercent = contextWindow > 0
    ? Math.max(0, Math.min(100, Math.round((contextTokens / contextWindow) * 100)))
    : 0;
  const estimateMark = contextEstimated && contextTokens > 0 ? "~" : "";
  const tokensText = contextWindow > 0
    ? `ctx ${estimateMark}${formatTokenCount(contextTokens)}/${formatTokenCount(contextWindow)} · ${contextPercent}%`
    : "ctx --";
  const busyText = busy ? statusText || "working" : "ready";
  const cwdText = truncateStart(cwd || "", Math.max(10, cols - 52));

  return (
    <Box flexDirection="row" width={cols} overflow="hidden" paddingLeft={1}>
      <Text color={theme.color.border}>╶ </Text>
      <Text color={theme.color.gem}>💎 </Text>
      <Text color={theme.color.text}>{modelText}</Text>
      <Text color={theme.color.border}>  ·  </Text>
      <Text color={theme.color.gold}>✦ </Text>
      <Text color={theme.color.text}>{tokensText}</Text>
      <Text color={theme.color.border}>  ·  </Text>
      <Text color={busy ? theme.color.gold : theme.color.leaf}>
        {busy ? "casting" : "ready"}
      </Text>
      {busy && (
        <>
          <Text color={theme.color.border}>: </Text>
          <Text color={theme.color.muted}>{busyText}</Text>
        </>
      )}
      {cwdText && (
        <>
          <Text color={theme.color.border}>  ·  </Text>
          <Text color={theme.color.muted}>{cwdText}</Text>
        </>
      )}
      <Text color={theme.color.border}> ╴</Text>
    </Box>
  );
};
