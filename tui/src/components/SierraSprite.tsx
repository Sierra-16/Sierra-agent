import React from "react";
import { Box, Text } from "ink";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { SIERRA_DIR } from "../config.js";

interface SpriteRun {
  text: string;
  fg?: string;
  bg?: string;
}

interface SpriteFrame {
  name: string;
  width: number;
  height: number;
  lines: SpriteRun[][];
}

interface SpritePayload {
  frames: SpriteFrame[];
}

interface SierraSpriteProps {
  name: string;
  fallbackName?: string;
}

const SPRITE_DIR = join(SIERRA_DIR, "tui", "assets", "sierra");
const SPRITE_FILES = ["terminal-frames.json", "thinking-terminal-frames.json"];

export const SIERRA_THINKING_SEQUENCE = [
  "think-idle",
  "think-dot-1",
  "think-dot-2",
  "think-dot-3",
  "think-question",
  "think-question-spark",
  "think-idea",
  "think-sparkle",
] as const;

export const SIERRA_TOOL_SEQUENCE = [
  "think-question",
  "think-question-spark",
  "think-idea",
] as const;

export const SIERRA_DASH_SEQUENCE = ["think-dot-3", "think-idle"] as const;

function loadFrames(): Map<string, SpriteFrame> {
  const loaded = new Map<string, SpriteFrame>();

  for (const fileName of SPRITE_FILES) {
    const path = join(SPRITE_DIR, fileName);
    if (!existsSync(path)) {
      continue;
    }

    const payload = JSON.parse(readFileSync(path, "utf8")) as SpritePayload;
    for (const frame of payload.frames) {
      loaded.set(frame.name, frame);
    }
  }

  return loaded;
}

const frames = loadFrames();

export const SierraSprite: React.FC<SierraSpriteProps> = ({
  name,
  fallbackName = "think-idle",
}) => {
  const frame = frames.get(name) ?? frames.get(fallbackName);
  if (!frame) {
    return null;
  }

  return (
    <Box flexDirection="column" flexShrink={0}>
      {frame.lines.map((line, lineIndex) => (
        <Text key={`${frame.name}-${lineIndex}`}>
          {line.map((run, runIndex) => (
            <Text
              key={`${lineIndex}-${runIndex}`}
              color={run.fg}
              backgroundColor={run.bg}
            >
              {run.text}
            </Text>
          ))}
        </Text>
      ))}
    </Box>
  );
};
