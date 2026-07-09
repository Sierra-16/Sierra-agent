import React from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import { Theme } from "../theme.js";
import type { CommandDefinition } from "../commands.js";
export type { CommandDefinition } from "../commands.js";

const COMMAND_COLUMN_WIDTH = 18;

interface ComposerProps {
  cols: number;
  input: string;
  busy: boolean;
  theme: Theme;
  hints: CommandDefinition[];
  hintIdx: number;
  onChange: (v: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
}

export const Composer: React.FC<ComposerProps> = ({
  cols,
  input,
  busy,
  theme,
  hints,
  hintIdx,
  onChange,
  onSubmit,
  placeholder,
}) => {
  const safeIdx = Math.min(hintIdx, Math.max(0, hints.length - 1));
  const hintRows = hints.map((hint) => {
    const command = padDisplay(hint.cmd, COMMAND_COLUMN_WIDTH);
    return `${command}${hint.desc}`;
  });
  const maxRowWidth = hintRows.reduce(
    (max, row) => Math.max(max, displayWidth(row)),
    0,
  );
  const hintWidth = Math.min(
    Math.max(42, maxRowWidth + 4),
    Math.max(30, cols - 2),
  );
  const innerWidth = hintWidth - 2;

  return (
    <Box flexDirection="column" paddingLeft={1} paddingRight={1}>
      {hints.length > 0 && (
        <Box flexDirection="column" marginBottom={1}>
          <Text color={theme.color.border}>
            {"╭" + "─".repeat(innerWidth) + "╮"}
          </Text>
          {hints.map((hint, index) => {
            const selected = index === safeIdx;
            const content = clipDisplay(hintRows[index], innerWidth - 2);
            const pad = Math.max(0, innerWidth - displayWidth(content) - 1);

            return (
              <Text color={theme.color.border} key={hint.cmd}>
                {"│ "}
                <Text
                  bold={selected}
                  color={selected ? "#111827" : theme.color.accent}
                  backgroundColor={selected ? theme.color.gold : undefined}
                >
                  {content}
                  {" ".repeat(pad)}
                </Text>
                <Text color={theme.color.border}>│</Text>
              </Text>
            );
          })}
          <Text color={theme.color.border}>
            {"╰" + "─".repeat(innerWidth) + "╯"}
          </Text>
        </Box>
      )}

      <Box flexDirection="row">
        <Text color={theme.color.leaf}>🍃 </Text>
        <Text bold color={theme.color.prompt}>
          {theme.brand.prompt}{" "}
        </Text>
        <TextInput
          value={input}
          onChange={onChange}
          onSubmit={onSubmit}
          focus={!busy}
          placeholder={placeholder || (busy ? "Sierra 正在处理..." : theme.brand.welcome)}
        />
      </Box>
    </Box>
  );
};

function padDisplay(value: string, targetWidth: number): string {
  const width = displayWidth(value);
  return value + " ".repeat(Math.max(0, targetWidth - width));
}

function clipDisplay(value: string, maxWidth: number): string {
  if (displayWidth(value) <= maxWidth) return value;
  const suffix = "...";
  const limit = Math.max(0, maxWidth - displayWidth(suffix));
  let out = "";
  let width = 0;
  for (const char of value) {
    const charWidth = charDisplayWidth(char);
    if (width + charWidth > limit) break;
    out += char;
    width += charWidth;
  }
  return out + suffix;
}

function displayWidth(value: string): number {
  let width = 0;
  for (const char of value) width += charDisplayWidth(char);
  return width;
}

function charDisplayWidth(char: string): number {
  const code = char.codePointAt(0) || 0;
  if (code === 0) return 0;
  if (code < 32 || (code >= 0x7f && code < 0xa0)) return 0;
  if (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe10 && code <= 0xfe19) ||
    (code >= 0xfe30 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6) ||
    (code >= 0x1f300 && code <= 0x1faff)
  ) {
    return 2;
  }
  return 1;
}
