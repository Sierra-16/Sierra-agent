import React from "react";
import { Box } from "ink";
import { Theme } from "../theme.js";
import type { Message } from "../hooks/useMainApp.js";
import { MessageLine } from "./MessageLine.js";

interface TranscriptProps {
  messages: Message[];
  cols: number;
  theme: Theme;
}

export const Transcript: React.FC<TranscriptProps> = ({
  messages,
  cols,
  theme,
}) => {
  if (messages.length === 0) return null;

  const shown = messages.slice(-80);
  const firstUserIdx = shown.findIndex((m) => m.role === "user");

  return (
    <Box flexDirection="column" paddingLeft={1} paddingRight={1}>
      {shown.map((msg, index) => (
        <MessageLine
          key={index}
          msg={msg}
          cols={cols}
          theme={theme}
          showSeparator={
            msg.role === "user" && index > 0 && index > firstUserIdx
          }
        />
      ))}
    </Box>
  );
};
