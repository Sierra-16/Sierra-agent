import React, { useEffect, useMemo, useState } from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";

interface ThinkingProps {
  theme: Theme;
  label?: string;
}

type ActivityMode = "think" | "tool" | "run";

interface ActivityState {
  mode: ActivityMode;
  text: string;
}

const THINK_FRAMES = ["·  ", " · ", "  ·", " · "];
const TOOL_FRAMES = ["▸  ", "▸▸ ", " ▸▸", "  ▸"];
const RUN_FRAMES = [">  ", ">> ", " >>", "  >"];

function parseActivity(label: string): ActivityState {
  const trimmed = label.trim() || "thinking";
  const normalized = trimmed.toLowerCase();

  if (normalized.startsWith("tool:")) {
    const toolName = trimmed.slice(trimmed.indexOf(":") + 1).trim();
    return { mode: "tool", text: toolName ? `tool ${toolName}` : "tool" };
  }

  if (normalized.includes("tool")) {
    return { mode: "tool", text: trimmed };
  }

  if (normalized.includes("run") || normalized.includes("exec")) {
    return { mode: "run", text: trimmed };
  }

  return { mode: "think", text: trimmed };
}

function framesFor(mode: ActivityMode): string[] {
  if (mode === "tool") return TOOL_FRAMES;
  if (mode === "run") return RUN_FRAMES;
  return THINK_FRAMES;
}

function intervalFor(mode: ActivityMode): number {
  if (mode === "tool") return 110;
  if (mode === "run") return 90;
  return 160;
}

function accentFor(mode: ActivityMode): string {
  if (mode === "tool") return "#facc15";
  if (mode === "run") return "#a3e635";
  return "#84cc16";
}

function iconFor(mode: ActivityMode): string {
  if (mode === "tool") return "✨";
  if (mode === "run") return "➜";
  return "🍃";
}

export const Thinking: React.FC<ThinkingProps> = ({
  theme,
  label = "thinking",
}) => {
  const activity = useMemo(() => parseActivity(label), [label]);
  const [tick, setTick] = useState(0);
  const frames = framesFor(activity.mode);
  const pulse = frames[tick % frames.length];
  const interval = intervalFor(activity.mode);
  const accent = accentFor(activity.mode);
  const icon = iconFor(activity.mode);

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), interval);
    return () => clearInterval(id);
  }, [interval]);

  return (
    <Box flexDirection="row" alignItems="center">
      <Text color={accent}>{icon} </Text>
      <Text color={theme.color.border}>[</Text>
      <Text color={theme.color.primary}>{"<"}</Text>
      <Text bold color={theme.color.gem}>
        ◆
      </Text>
      <Text color={theme.color.primary}>{">"}</Text>
      <Text color={theme.color.border}>]</Text>
      <Text color={theme.color.muted}> {activity.text}</Text>
      <Text color={accent}> {pulse}</Text>
    </Box>
  );
};
