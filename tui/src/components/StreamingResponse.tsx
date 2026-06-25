import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";
import { Markdown } from "./Markdown.js";

interface StreamingResponseProps {
  text: string;
  cols: number;
  theme: Theme;
}

export const StreamingResponse: React.FC<StreamingResponseProps> = ({
  text,
  theme,
}) => {
  if (!text) return null;

  return (
    <Box flexDirection="row" paddingLeft={1} paddingRight={1}>
      <Text color={theme.color.assistantMsg}>🧝 </Text>
      <Text bold color={theme.color.assistantMsg}>
        {"SIERRA".padEnd(6)}
      </Text>
      <Text color={theme.color.border}>│ </Text>
      <Box flexDirection="column" flexShrink={1}>
        <Markdown theme={theme}>{text}</Markdown>
        <Text color={theme.color.accent}>▌</Text>
      </Box>
    </Box>
  );
};
