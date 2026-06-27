import React, { useEffect, useState } from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";
import type { ToolTrace } from "../hooks/useMainApp.js";

interface ToolActivityProps {
  events: ToolTrace[];
  theme: Theme;
  cols: number;
}

export const ToolActivity: React.FC<ToolActivityProps> = ({
  events,
  theme,
  cols,
}) => {
  const [tick, setTick] = useState(0);
  const pulse = ["✦", "✧", "◆", "◇"][tick % 4];

  useEffect(() => {
    if (!events.some((event) => event.status === "running")) return;
    const id = setInterval(() => setTick((next) => next + 1), 140);
    return () => clearInterval(id);
  }, [events]);

  if (events.length === 0) return null;

  const visible = events.slice(-6);

  return (
    <Box flexDirection="column" marginTop={1} marginBottom={events.some((event) => event.status === "running") ? 0 : 1}>
      {visible.map((event) => {
        const running = event.status === "running";
        const failed = event.status === "failed";
        const icon = running ? pulse : failed ? "×" : "✓";
        const state = running ? "running" : failed ? "failed" : "done";
        const stateColor = running ? theme.color.gold : failed ? theme.color.error : theme.color.leaf;
        const group = toolGroup(event.name);
        const label = clip(event.text || "", Math.max(18, cols - event.name.length - group.length - 34));
        const showSummary = failed && label;

        return (
          <Box key={event.id} flexDirection="row" paddingLeft={1}>
            <Text color={theme.color.border}>│ </Text>
            <Text color={stateColor}>{icon} </Text>
            <Text color={theme.color.gem}>{group} </Text>
            <Text color={theme.color.text}>{event.name}</Text>
            <Text color={theme.color.border}> · </Text>
            <Text color={stateColor}>{state}</Text>
            {showSummary && (
              <>
                <Text color={theme.color.border}> · </Text>
                <Text color={theme.color.muted}>{label}</Text>
              </>
            )}
          </Box>
        );
      })}
    </Box>
  );
};

function toolGroup(name: string): string {
  if (name.startsWith("mcp__")) return "mcp";
  if (name.includes("memory")) return "memory";
  if (name.startsWith("skill_")) return "skill";
  if (name.startsWith("cron_") || name.includes("plan") || name.includes("task")) return "system";
  if (name.includes("file") || name.includes("directory") || name === "search_files") return "file";
  if (name.includes("web") || name.includes("browser")) return "web";
  if (name === "powershell") return "shell";
  return "tool";
}

function clip(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return value.slice(0, Math.max(0, maxLength - 3)) + "...";
}
