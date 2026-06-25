import React from "react";
import { Box, Text } from "ink";
import type { TaskPlan } from "../gateway.js";
import type { Theme } from "../theme.js";

interface TaskProgressProps {
  task: TaskPlan | null;
  cols: number;
  theme: Theme;
}

export const TaskProgress: React.FC<TaskProgressProps> = ({ task, cols, theme }) => {
  if (!task || !["active", "interrupted"].includes(task.status)) return null;

  const completed = task.steps.filter((step) => step.status === "completed").length;
  const current = task.steps.find((step) => step.status === "in_progress")
    || task.steps.find((step) => step.status === "pending");
  const width = Math.max(20, cols - 12);
  const objective = clip(task.objective, width);
  const currentText = current ? clip(current.step, Math.max(12, width - 12)) : "waiting for next step";
  const uncertain = task.uncertain_executions?.length || 0;

  return (
    <Box flexDirection="column" paddingLeft={1} marginTop={1}>
      <Box>
        <Text color={theme.color.gem}>◆ plan </Text>
        <Text color={theme.color.text}>{objective}</Text>
        <Text color={theme.color.border}> · </Text>
        <Text color={theme.color.leaf}>{completed}/{task.steps.length}</Text>
      </Box>
      <Box paddingLeft={2}>
        <Text color={task.status === "interrupted" ? theme.color.warn : theme.color.gold}>
          {task.status === "interrupted" ? "Ⅱ interrupted" : "› " + currentText}
        </Text>
        {uncertain > 0 && (
          <Text color={theme.color.warn}> · {uncertain} uncertain tool call{uncertain > 1 ? "s" : ""}</Text>
        )}
      </Box>
    </Box>
  );
};

function clip(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return value.slice(0, Math.max(0, maxLength - 3)) + "...";
}
