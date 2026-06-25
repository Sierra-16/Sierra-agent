import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";
import type { Message } from "../hooks/useMainApp.js";
import { Markdown } from "./Markdown.js";

interface MessageLineProps {
  msg: Message;
  cols: number;
  theme: Theme;
  showSeparator?: boolean;
}

function roleMeta(msg: Message, theme: Theme) {
  if (msg.role === "user") {
    return { icon: "👤", label: "YOU", color: theme.color.userMsg };
  }
  if (msg.role === "assistant") {
    return { icon: "🧝", label: "SIERRA", color: theme.color.assistantMsg };
  }
  if (msg.role === "system") {
    return { icon: "✨", label: "SYS", color: theme.color.systemMsg };
  }
  return { icon: "!", label: "ERR", color: theme.color.error };
}

export const MessageLine: React.FC<MessageLineProps> = ({
  msg,
  cols,
  theme,
  showSeparator,
}) => {
  const meta = roleMeta(msg, theme);
  const rule = "-".repeat(Math.min(cols - 2, 80));

  return (
    <Box flexDirection="column">
      {showSeparator && (
        <Box marginTop={1}>
          <Text color={theme.color.border}>{rule}</Text>
        </Box>
      )}
      <Box flexDirection="row">
        <Text color={meta.color}>
          {meta.icon}{" "}
        </Text>
        <Text bold color={meta.color}>
          {meta.label.padEnd(6)}
        </Text>
        <Text color={theme.color.border}>│ </Text>
        <Box flexDirection="column" flexShrink={1}>
          {msg.role === "assistant" ? (
            <Markdown theme={theme}>{msg.text}</Markdown>
          ) : (
            <Text
              color={
                msg.role === "system"
                  ? theme.color.muted
                  : msg.role === "error"
                  ? theme.color.error
                  : theme.color.userMsg
              }
            >
              {msg.text}
            </Text>
          )}
        </Box>
      </Box>
    </Box>
  );
};
