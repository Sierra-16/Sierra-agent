import React from "react";
import { Box, Text } from "ink";
import { Theme } from "../theme.js";
import type { UserInputRequest } from "../hooks/useMainApp.js";

interface UserInputPromptProps {
  request: UserInputRequest;
  selectedIndex: number;
  theme: Theme;
  cols: number;
}

export const UserInputPrompt: React.FC<UserInputPromptProps> = ({
  request,
  selectedIndex,
  theme,
  cols,
}) => {
  const width = Math.max(20, Math.min(cols - 2, 88));
  const contentWidth = Math.max(12, width - 6);

  return (
    <Box
      flexDirection="column"
      width={width}
      marginLeft={1}
      marginBottom={1}
      paddingX={1}
      borderStyle="single"
      borderColor={theme.color.gem}
    >
      <Text bold color={theme.color.gem}>Sierra needs your input</Text>
      <Box marginTop={1} marginBottom={request.options.length ? 1 : 0}>
        <Text color={theme.color.text} wrap="wrap">{request.question}</Text>
      </Box>
      {request.options.map((option, index) => {
        const selected = index === selectedIndex;
        const description = clip(option.description, contentWidth);
        return (
          <Box key={`${option.value}-${index}`} flexDirection="column">
            <Text color={selected ? theme.color.leaf : theme.color.muted} bold={selected}>
              {selected ? "› " : "  "}{option.label}
            </Text>
            {description && (
              <Text color={theme.color.muted}>    {description}</Text>
            )}
          </Box>
        );
      })}
      <Box marginTop={1}>
        <Text color={theme.color.muted}>
          {request.allowFreeText
            ? "选择一个选项，或在下方输入其他需求"
            : "选择一个选项"}
        </Text>
      </Box>
    </Box>
  );
};

function clip(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return value.slice(0, Math.max(0, maxLength - 3)) + "...";
}
