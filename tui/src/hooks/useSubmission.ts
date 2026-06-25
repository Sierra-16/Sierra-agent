/**
 * useSubmission — Hermes pattern: dispatchSubmission → send / slash.
 * TextInput calls submit(), which calls dispatchSubmission().
 */
import { useCallback, type MutableRefObject } from "react";
import type { Gateway } from "../gateway.js";
import type { ComposerActions, ComposerRefs } from "./useComposerState.js";
import type { Message } from "./useMainApp.js";
import { COMMANDS } from "../components/Composer.js";

interface UseSubmissionOptions {
  composerActions: ComposerActions;
  composerRefs: ComposerRefs;
  gw: Gateway;
  appendMessage: (msg: Message) => void;
  setBusy: (v: boolean) => void;
  setStatusText: (v: string) => void;
  onChatStart: () => void;
  busy: boolean;
  handleCommand: (cmd: string) => void;
  hintIdx: number;
}

export function useSubmission(opts: UseSubmissionOptions) {
  const {
    composerActions,
    composerRefs,
    gw,
    appendMessage,
    setBusy,
    onChatStart,
    busy,
    handleCommand,
    hintIdx,
  } = opts;

  /** Send text to the backend as a chat message. */
  const send = useCallback(
    (text: string) => {
      onChatStart();
      appendMessage({ role: "user", text });
      setBusy(true);
      composerActions.clearIn();
      gw.send({ cmd: "chat", text });
    },
    [appendMessage, setBusy, onChatStart, composerActions, gw]
  );

  /** Main dispatch: slash commands → handleCommand, normal text → send. */
  const dispatchSubmission = useCallback(
    (full: string) => {
      const text = full.trim();
      if (!text) return;

      if (text.startsWith("/")) {
        composerActions.pushHistory(full);
        composerActions.clearIn();
        handleCommand(text);
        return;
      }

      if (busy) return;

      composerActions.pushHistory(full);
      send(full);
    },
    [busy, composerActions, send, handleCommand]
  );

  /** Called by TextInput's onSubmit. Handles hint autocomplete then dispatches. */
  const submit = useCallback(
    (value: string) => {
      const text = value.trim();
      if (!text) return;

      // Autocomplete partial slash commands
      if (text.startsWith("/") && !text.includes(" ")) {
        const matches = COMMANDS.filter((c) => c.cmd.startsWith(text));
        if (matches.length > 0) {
          const selectedIdx = Math.min(hintIdx, matches.length - 1);
          const selected = matches[selectedIdx];

          // First Enter confirms the highlighted candidate by filling it.
          if (selected.cmd !== text) {
            composerActions.setInput(
              selected.cmd + (selected.requiresArg ? " " : "")
            );
            return;
          }

          // Argument-taking commands stay in the composer until completed.
          if (selected.requiresArg) {
            composerActions.setInput(`${selected.cmd} `);
            return;
          }

          // The command was already filled; the next Enter executes it.
          dispatchSubmission(text);
          return;
        }
      }

      dispatchSubmission(value);
    },
    [composerActions, dispatchSubmission, hintIdx]
  );

  // Update the submitRef so useComposerState always exposes the latest submit
  composerRefs.submitRef.current = submit;

  return { dispatchSubmission, send, submit };
}
