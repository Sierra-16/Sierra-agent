import React from "react";
import { Box, Text } from "ink";
import type { TaskPlan } from "../gateway.js";
import type { Theme } from "../theme.js";

interface TaskRecoveryPromptProps {
  task: TaskPlan;
  selectedIndex: number;
  cols: number;
  theme: Theme;
}

const OPTIONS = [
  { label: "继续任务", description: "恢复计划，从尚未完成的安全步骤继续" },
  { label: "放弃任务", description: "保留历史记录，但不再继续执行该计划" },
];

export const TaskRecoveryPrompt: React.FC<TaskRecoveryPromptProps> = ({
  task,
  selectedIndex,
  cols,
  theme,
}) => {
  const width = Math.max(30, Math.min(cols - 2, 88));
  const completed = task.steps.filter((step) => step.status === "completed").length;
  const uncertain = task.uncertain_executions?.length || 0;

  return (
    <Box
      flexDirection="column"
      width={width}
      marginLeft={1}
      marginBottom={1}
      paddingX={1}
      borderStyle="single"
      borderColor={uncertain ? theme.color.warn : theme.color.gem}
    >
      <Text bold color={theme.color.gem}>Resume interrupted task</Text>
      <Text color={theme.color.text} wrap="wrap">{task.objective}</Text>
      <Text color={theme.color.muted}>progress {completed}/{task.steps.length}</Text>
      {uncertain > 0 && (
        <Text color={theme.color.warn}>
          {uncertain} tool call{uncertain > 1 ? "s have" : " has"} uncertain results; Sierra will verify before retrying.
        </Text>
      )}
      <Box flexDirection="column" marginTop={1}>
        {OPTIONS.map((option, index) => {
          const selected = index === selectedIndex;
          return (
            <Box key={option.label} flexDirection="column">
              <Text bold={selected} color={selected ? theme.color.leaf : theme.color.muted}>
                {selected ? "› " : "  "}{option.label}
              </Text>
              <Text color={theme.color.muted}>    {option.description}</Text>
            </Box>
          );
        })}
      </Box>
      <Text color={theme.color.muted}>↑/↓ select · Enter confirm</Text>
    </Box>
  );
};
