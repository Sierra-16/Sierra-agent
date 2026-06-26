/**
 * useInputHandlers — ink version with wheel support.
 * Ctrl+C/D, hint navigation, Escape clear.
 * Scroll handled by ScrollBox internally via mouse wheel.
 */
import { useInput } from "ink";
import type { Key } from "ink";
import { type MutableRefObject, useRef } from "react";
import type { Gateway } from "../gateway.js";
import type { TaskPlan } from "../gateway.js";
import type { ComposerActions, ComposerRefs, ComposerState } from "./useComposerState.js";
import { COMMANDS } from "../components/Composer.js";
import type {
  ToolApprovalDecision,
  ToolApprovalRequest,
  UserInputRequest,
} from "./useMainApp.js";

interface UseInputHandlersOptions {
  composerActions: ComposerActions;
  composerRefs: ComposerRefs;
  composerState: ComposerState;
  busy: boolean;
  gw: Gateway;
  appendMessage: (msg: { role: string; text: string }) => void;
  hintIdx: number;
  setHintIdx: (v: number | ((prev: number) => number)) => void;
  modelPickerOpen: boolean;
  closeModelPicker: () => void;
  moveModelSelection: (delta: number) => void;
  confirmModelSelection: () => void;
  pendingToolApproval: ToolApprovalRequest | null;
  confirmToolApproval: (decision: ToolApprovalDecision) => void;
  pendingUserInput: UserInputRequest | null;
  moveUserInputSelection: (delta: number) => void;
  cancelUserInput: () => void;
  pendingTaskRecovery: TaskPlan | null;
  moveTaskRecoverySelection: (delta: number) => void;
  confirmTaskRecovery: () => void;
}

export function useInputHandlers(opts: UseInputHandlersOptions) {
  const {
    composerActions,
    composerState,
    busy,
    gw,
    appendMessage,
    hintIdx,
    setHintIdx,
    modelPickerOpen,
    closeModelPicker,
    moveModelSelection,
    confirmModelSelection,
    pendingToolApproval,
    confirmToolApproval,
    pendingUserInput,
    moveUserInputSelection,
    cancelUserInput,
    pendingTaskRecovery,
    moveTaskRecoverySelection,
    confirmTaskRecovery,
  } = opts;

  const hintIdxRef = useRef(hintIdx);
  hintIdxRef.current = hintIdx;

  useInput((ch: string, key: Key) => {
    if (pendingTaskRecovery) {
      if ((key.ctrl && ch === "c") || (key.ctrl && ch === "d")) {
        gw?.stop();
        return;
      }
      if (key.downArrow) {
        moveTaskRecoverySelection(1);
        return;
      }
      if (key.upArrow) {
        moveTaskRecoverySelection(-1);
        return;
      }
      if (key.return) {
        confirmTaskRecovery();
        return;
      }
      return;
    }

    if (pendingUserInput) {
      if (key.downArrow) {
        moveUserInputSelection(1);
        return;
      }
      if (key.upArrow) {
        moveUserInputSelection(-1);
        return;
      }
      if (key.escape) {
        cancelUserInput();
        return;
      }
    }

    if (pendingToolApproval) {
      const lower = ch.toLowerCase();
      if (lower === "y") {
        confirmToolApproval("once");
        return;
      }
      if (lower === "a") {
        confirmToolApproval("session");
        return;
      }
      if (lower === "n" || key.escape) {
        confirmToolApproval("deny");
        return;
      }
    }

    if (modelPickerOpen) {
      if (key.downArrow) {
        moveModelSelection(1);
        return;
      }
      if (key.upArrow) {
        moveModelSelection(-1);
        return;
      }
      if (key.return) {
        confirmModelSelection();
        return;
      }
      if (key.escape) {
        closeModelPicker();
        return;
      }
    }

    // Ctrl+C
    if (key.ctrl && ch === "c") {
      if (busy) {
        appendMessage({ role: "system", text: "已中断当前处理，正在恢复 Sierra..." });
        gw?.interrupt();
        return;
      }
      if (composerState.input) {
        composerActions.clearIn();
        return;
      }
      gw?.stop();
      return;
    }

    // Ctrl+D
    if (key.ctrl && ch === "d") {
      gw?.stop();
      return;
    }

    // Hint navigation (up/down arrows)
    const hints =
      composerState.input.startsWith("/") &&
      !composerState.input.includes(" ")
        ? COMMANDS.filter((c) => c.cmd.startsWith(composerState.input))
        : [];

    if (hints.length > 0) {
      if (key.downArrow) {
        setHintIdx((prev: number) => (prev + 1) % hints.length);
        return;
      }
      if (key.upArrow) {
        setHintIdx(
          (prev: number) => (prev - 1 + hints.length) % hints.length
        );
        return;
      }
    }

    // Escape: clear input
    if (key.escape) {
      composerActions.clearIn();
      return;
    }

    // Wheel events are handled by ScrollBox internally
    // All other keys (chars, Enter, backspace, arrows) handled by TextInput
  });
}
