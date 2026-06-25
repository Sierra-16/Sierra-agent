/**
 * AppLayout — uses ink: ScrollBox (stickyScroll), AlternateScreen.
 */
import React from "react";
import { Box, Static, Text } from "ink";
import { Theme } from "../theme.js";
import type { MainApp } from "../hooks/useMainApp.js";
import { Banner } from "./Banner.js";
import { StatusRule } from "./StatusRule.js";
import { Transcript } from "./Transcript.js";
import { Composer } from "./Composer.js";
import { HelpHint } from "./HelpHint.js";
import { Thinking } from "./Thinking.js";
import { ModelPicker } from "./ModelPicker.js";
import { StreamingResponse } from "./StreamingResponse.js";
import { ToolActivity } from "./ToolActivity.js";
import { ToolApprovalPrompt } from "./ToolApprovalPrompt.js";
import { UserInputPrompt } from "./UserInputPrompt.js";
import { TaskProgress } from "./TaskProgress.js";
import { TaskRecoveryPrompt } from "./TaskRecoveryPrompt.js";

interface AppLayoutProps {
  app: MainApp;
  theme: Theme;
  hints: { cmd: string; desc: string }[];
  hintIdx: number;
  onSubmit: (value: string) => void;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  app,
  theme,
  hints,
  hintIdx,
  onSubmit,
}) => {
  const showHelp = app.composer.state.input === "?";
  const welcomeItems = app.started ? ["welcome"] : [];

  return (
    <>
      <Static items={welcomeItems}>
        {(id) => (
          <Banner
            key={id}
            cols={app.cols}
            model={app.model}
            cwd={app.cwd}
            lastQuery={app.lastQuery}
            theme={theme}
          />
        )}
      </Static>
      <Box flexDirection="column">
      <Box flexDirection="column" flexGrow={1}>
        {/* ── Transcript area — ScrollBox with stickyScroll ── */}
        <Box flexDirection="column" flexGrow={1} flexShrink={1} overflow="hidden">
          <Transcript
            messages={app.messages}
            cols={app.cols}
            theme={theme}
          />
          <ToolActivity
            events={app.toolEvents}
            cols={app.cols}
            theme={theme}
          />
          <StreamingResponse
            text={app.streamingText}
            cols={app.cols}
            theme={theme}
          />
          <TaskProgress
            task={app.taskPlan}
            cols={app.cols}
            theme={theme}
          />
          {!app.started && (
            <Text color={theme.color.muted}>Starting Sierra...</Text>
          )}
        </Box>

        {/* ── Composer area (fixed at bottom) ── */}
        <Box flexDirection="column" flexShrink={0}>
          {app.pendingTaskRecovery && (
            <TaskRecoveryPrompt
              task={app.pendingTaskRecovery}
              selectedIndex={app.taskRecoverySelectedIndex}
              theme={theme}
              cols={app.cols}
            />
          )}
          {app.pendingUserInput && (
            <UserInputPrompt
              request={app.pendingUserInput}
              selectedIndex={app.userInputSelectedIndex}
              theme={theme}
              cols={app.cols}
            />
          )}
          {app.pendingToolApproval && (
            <ToolApprovalPrompt
              request={app.pendingToolApproval}
              theme={theme}
              cols={app.cols}
            />
          )}
          {app.busy && !app.pendingUserInput && !app.pendingTaskRecovery && (
            <Box paddingLeft={1}>
              <Thinking theme={theme} label={app.statusText || "thinking"} />
            </Box>
          )}
          {showHelp && <HelpHint theme={theme} cols={app.cols} />}
          {app.modelPicker.open && (
            <ModelPicker
              models={app.modelPicker.models}
              selectedIndex={app.modelPicker.selectedIndex}
              loading={app.modelPicker.loading}
              theme={theme}
              cols={app.cols}
            />
          )}
          {app.started && (
            <StatusRule
              cols={app.cols}
              model={app.model}
              busy={app.busy}
              statusText={app.statusText}
              contextTokens={app.usage.context}
              contextWindow={app.usage.context_window}
              contextEstimated={app.usage.context_estimated}
              cwd={app.cwd}
              theme={theme}
            />
          )}
          <Composer
            cols={app.cols}
            input={app.composer.state.input}
            busy={(app.busy && !app.pendingUserInput) || !!app.pendingTaskRecovery}
            theme={theme}
            hints={hints}
            hintIdx={hintIdx}
            onChange={app.composer.actions.setInput}
            onSubmit={onSubmit}
            placeholder={
              app.pendingUserInput
                ? app.pendingUserInput.allowFreeText
                  ? "输入其他需求，或直接确认所选项"
                  : "确认所选项"
                : undefined
            }
          />
        </Box>
      </Box>
      </Box>
    </>
  );
};
