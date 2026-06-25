/**
 * Markdown — renders markdown text with basic syntax highlighting.
 * Handles: **bold**, *italic*, `code`, ```code blocks```.
 */
import React from "react";
import { Text } from "ink";
import { Theme } from "../theme.js";

interface MarkdownProps {
  children: string;
  theme: Theme;
}

export const Markdown: React.FC<MarkdownProps> = ({ children, theme }) => {
  const lines = children.split("\n");
  let inCodeBlock = false;

  return (
    <>
      {lines.map((line, i) => {
        // Code block fences
        if (line.startsWith("```")) {
          inCodeBlock = !inCodeBlock;
          return (
            <Text key={i} color={theme.color.border}>
              {line}
            </Text>
          );
        }

        if (inCodeBlock) {
          return (
            <Text key={i} color={theme.color.muted}>
              {"  " + line}
            </Text>
          );
        }

        // Inline formatting
        return <InlineMarkdown key={i} text={line} theme={theme} />;
      })}
    </>
  );
};

const InlineMarkdown: React.FC<{ text: string; theme: Theme }> = ({
  text,
  theme,
}) => {
  // Split on **bold**, *italic*, `code`
  const parts = text.split(
    /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/
  );

  return (
    <Text>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <Text key={i} bold color={theme.color.assistantMsg}>{part.slice(2, -2)}</Text>;
        }
        if (part.startsWith("*") && part.endsWith("*")) {
          return <Text key={i} italic color={theme.color.assistantMsg}>{part.slice(1, -1)}</Text>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return <Text key={i} color={theme.color.accent}>{part.slice(1, -1)}</Text>;
        }
        if (part.startsWith("[")) {
          const m = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
          if (m) {
            return <Text key={i} color={theme.color.accent}>{m[1]!} ({m[2]})</Text>;
          }
        }
        return <Text key={i} color={theme.color.assistantMsg}>{part}</Text>;
      })}
    </Text>
  );
};
