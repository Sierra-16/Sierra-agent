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
        const icon = running ? pulse : "✓";
        const state = running ? "running" : "done";
        const stateColor = running ? theme.color.gold : theme.color.leaf;

        return (
          <Box key={event.id} flexDirection="row" paddingLeft={1}>
            <Text color={theme.color.border}>│ </Text>
            <Text color={stateColor}>{icon} </Text>
            <Text color={theme.color.gem}>tool </Text>
            <Text color={theme.color.text}>{event.name}</Text>
            <Text color={theme.color.border}> · </Text>
            <Text color={stateColor}>{state}</Text>
          </Box>
        );
      })}
    </Box>
  );
};
