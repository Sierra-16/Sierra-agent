/**
 * useComposerState — Hermes pattern: input + clearIn + history.
 * Composer owns the input text; submission consumes it and calls clearIn.
 */
import { useState, useRef, useCallback, useMemo, type MutableRefObject } from "react";

export interface ComposerActions {
  setInput: (v: string) => void;
  clearIn: () => void;
  pushHistory: (text: string) => void;
  setHistoryIdx: (v: null | number) => void;
}

export interface ComposerRefs {
  historyRef: MutableRefObject<string[]>;
  historyDraftRef: MutableRefObject<string>;
  submitRef: MutableRefObject<((value: string) => void) | null>;
}

export interface ComposerState {
  input: string;
  historyIdx: null | number;
}

export interface UseComposerStateResult {
  actions: ComposerActions;
  refs: ComposerRefs;
  state: ComposerState;
}

export function useComposerState(): UseComposerStateResult {
  const [input, setInput] = useState("");
  const [historyIdx, setHistoryIdx] = useState<null | number>(null);

  const historyRef = useRef<string[]>([]);
  const historyDraftRef = useRef("");
  const submitRef = useRef<((value: string) => void) | null>(null);

  const clearIn = useCallback(() => {
    setInput("");
    setHistoryIdx(null);
    historyDraftRef.current = "";
  }, []);

  const pushHistory = useCallback(
    (text: string) => {
      // Dedupe consecutive identical entries
      if (historyRef.current[0] !== text) {
        historyRef.current.unshift(text);
        if (historyRef.current.length > 200) historyRef.current.pop();
      }
    },
    []
  );

  const actions = useMemo(
    () => ({ setInput, clearIn, pushHistory, setHistoryIdx }),
    [clearIn, pushHistory]
  );

  const refs = useMemo(
    () => ({ historyRef, historyDraftRef, submitRef }),
    []
  );

  const state = useMemo(() => ({ input, historyIdx }), [input, historyIdx]);

  return { actions, refs, state };
}
