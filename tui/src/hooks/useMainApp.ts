/**
 * useMainApp — receives pre-started gateway, manages all state.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { Gateway, ServerEvent } from "../gateway.js";
import type { TaskPlan } from "../gateway.js";
import { useComposerState } from "./useComposerState.js";
import type { ComposerActions, ComposerRefs, ComposerState } from "./useComposerState.js";
import { useSubmission } from "./useSubmission.js";
import { useInputHandlers } from "./useInputHandlers.js";
import type { ModelOption } from "../components/ModelPicker.js";

export interface Message {
  role: "user" | "assistant" | "system" | "error";
  text: string;
}

export interface ToolTrace {
  id: string;
  name: string;
  status: "running" | "done";
  text?: string;
}

export interface ToolApprovalRequest {
  id: string;
  name: string;
  risk: string;
  reason: string;
  arguments: string;
}

export type ToolApprovalDecision = "once" | "session" | "deny";

export interface UserInputOption {
  label: string;
  description: string;
  value: string;
}

export interface UserInputRequest {
  id: string;
  question: string;
  options: UserInputOption[];
  allowFreeText: boolean;
}

export interface MainApp {
  messages: Message[];
  streamingText: string;
  toolEvents: ToolTrace[];
  pendingToolApproval: ToolApprovalRequest | null;
  pendingUserInput: UserInputRequest | null;
  userInputSelectedIndex: number;
  taskPlan: TaskPlan | null;
  pendingTaskRecovery: TaskPlan | null;
  taskRecoverySelectedIndex: number;
  busy: boolean;
  model: string;
  cwd: string;
  usage: {
    input: number;
    output: number;
    context: number;
    context_window: number;
    context_estimated: boolean;
  };
  started: boolean;
  statusText: string;
  lastQuery: string;
  cols: number;
  composer: { actions: ComposerActions; refs: ComposerRefs; state: ComposerState };
  hintIdx: number;
  setHintIdx: (v: number | ((prev: number) => number)) => void;
  modelPicker: {
    open: boolean;
    loading: boolean;
    models: ModelOption[];
    selectedIndex: number;
  };
  handleCommand: (cmd: string) => void;
  closeModelPicker: () => void;
  moveModelSelection: (delta: number) => void;
  confirmModelSelection: () => void;
  confirmToolApproval: (decision: ToolApprovalDecision) => void;
  moveUserInputSelection: (delta: number) => void;
  submitUserInput: (text: string) => void;
  cancelUserInput: () => void;
  moveTaskRecoverySelection: (delta: number) => void;
  confirmTaskRecovery: () => void;
  stop: () => void;
}

export function useMainApp(gw: Gateway): MainApp {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [toolEvents, setToolEvents] = useState<ToolTrace[]>([]);
  const [pendingToolApproval, setPendingToolApproval] = useState<ToolApprovalRequest | null>(null);
  const [pendingUserInput, setPendingUserInput] = useState<UserInputRequest | null>(null);
  const [userInputSelectedIndex, setUserInputSelectedIndex] = useState(0);
  const [taskPlan, setTaskPlan] = useState<TaskPlan | null>(null);
  const [pendingTaskRecovery, setPendingTaskRecovery] = useState<TaskPlan | null>(null);
  const [taskRecoverySelectedIndex, setTaskRecoverySelectedIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState("");
  const [cwd, setCwd] = useState("");
  const [usage, setUsage] = useState({
    input: 0,
    output: 0,
    context: 0,
    context_window: 0,
    context_estimated: false,
  });
  const [started, setStarted] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [hintIdx, setHintIdx] = useState(0);
  const [cols, setCols] = useState(process.stdout.columns || 80);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [modelPickerLoading, setModelPickerLoading] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModelIndex, setSelectedModelIndex] = useState(0);

  const composer = useComposerState();
  const streamingTextRef = useRef("");
  const pendingToolApprovalRef = useRef<ToolApprovalRequest | null>(null);
  const pendingUserInputRef = useRef<UserInputRequest | null>(null);

  useEffect(() => {
    pendingToolApprovalRef.current = pendingToolApproval;
  }, [pendingToolApproval]);

  useEffect(() => {
    pendingUserInputRef.current = pendingUserInput;
  }, [pendingUserInput]);

  useEffect(() => {
    const onResize = () => setCols(process.stdout.columns || 80);
    process.stdout.on("resize", onResize);
    return () => { process.stdout.removeListener("resize", onResize); };
  }, []);

  const appendMessage = useCallback((msg: { role: string; text: string }) => {
    setMessages((prev) => [...prev, msg as Message]);
  }, []);

  const resetStreamingText = useCallback(() => {
    streamingTextRef.current = "";
    setStreamingText("");
  }, []);

  const resetLiveOutput = useCallback(() => {
    resetStreamingText();
    setToolEvents([]);
  }, [resetStreamingText]);

  const handleCommand = useCallback(
    (cmd: string) => {
      const [command, ...args] = cmd.trim().split(/\s+/);
      const argument = args.join(" ").trim();
      switch (command) {
        case "/quit": case "/exit": gw.stop(); break;
        case "/help":
          appendMessage({
            role: "system",
            text: "命令: /help  /quit  /new  /list  /sessions  /session-search <关键词>  /session-load <id>  /model  /mcp  /skills  /skills-reload  /skills-stats  /reset  /compress  /task  /task-cancel  /companion  /memory  /memory-search <问题>  /memory-forget <ID>  /memory-clear  /audit",
          });
          break;
        case "/new":
          gw.send({ cmd: "new" }); setMessages([]); setLastQuery(""); resetLiveOutput();
          setTaskPlan(null); setPendingTaskRecovery(null);
          setUsage((prev) => ({ ...prev, context: 0, context_estimated: false }));
          break;
        case "/list": gw.send({ cmd: "list" }); break;
        case "/sessions":
          setBusy(true);
          setStatusText("reading sessions");
          gw.send({ cmd: "sessions", limit: 20 });
          break;
        case "/session-search":
          if (!argument) {
            appendMessage({ role: "system", text: "用法: /session-search <关键词>" });
            break;
          }
          setBusy(true);
          setStatusText("searching sessions");
          gw.send({ cmd: "session_search", query: argument, limit: 10 });
          break;
        case "/session-load":
          if (!argument) {
            appendMessage({ role: "system", text: "用法: /session-load <session_id>" });
            break;
          }
          setBusy(true);
          setStatusText("loading session");
          gw.send({ cmd: "session_load", id: argument });
          break;
        case "/reset":
          gw.send({ cmd: "new" }); setMessages([]); setLastQuery(""); resetLiveOutput();
          setTaskPlan(null); setPendingTaskRecovery(null);
          setUsage((prev) => ({ ...prev, context: 0, context_estimated: false }));
          break;
        case "/compress": gw.send({ cmd: "compress" }); break;
        case "/task": gw.send({ cmd: "task" }); break;
        case "/task-cancel": {
          const task = taskPlan;
          if (!task || !["active", "interrupted"].includes(task.status)) {
            appendMessage({ role: "system", text: "当前没有可放弃的任务" });
            break;
          }
          gw.send({ cmd: "task_abandon", id: task.id });
          break;
        }
        case "/memory":
          setBusy(true);
          setStatusText("reading memory");
          gw.send({ cmd: "memory" });
          break;
        case "/companion":
          setBusy(true);
          setStatusText("reading companion state");
          gw.send({ cmd: "companion" });
          break;
        case "/memory-search":
          if (!argument) {
            appendMessage({ role: "system", text: "用法: /memory-search <问题>" });
            break;
          }
          setBusy(true);
          setStatusText("searching memory");
          gw.send({ cmd: "memory_search", query: argument, limit: 5 });
          break;
        case "/memory-forget":
          if (!/^\d+$/.test(argument)) {
            appendMessage({ role: "system", text: "用法: /memory-forget <ID>" });
            break;
          }
          setBusy(true);
          setStatusText("confirm memory deletion");
          gw.send({ cmd: "memory_forget", id: Number(argument) });
          break;
        case "/memory-clear":
          setBusy(true);
          setStatusText("confirm memory clear");
          gw.send({ cmd: "memory_clear" });
          break;
        case "/audit": gw.send({ cmd: "audit" }); break;
        case "/mcp": gw.send({ cmd: "mcp" }); break;
        case "/skills": gw.send({ cmd: "skills" }); break;
        case "/skills-reload":
          setBusy(true);
          setStatusText("reloading skills");
          gw.send({ cmd: "skills_reload" });
          break;
        case "/skills-stats":
          setBusy(true);
          setStatusText("reading skill stats");
          gw.send({ cmd: "skills_stats" });
          break;
        case "/model":
          setModelPickerLoading(true);
          gw.send({ cmd: "models" });
          break;
        default: appendMessage({ role: "system", text: `未知命令: ${cmd}` });
      }
    },
    [appendMessage, gw, resetLiveOutput, taskPlan]
  );

  const closeModelPicker = useCallback(() => {
    setModelPickerOpen(false);
    setModelPickerLoading(false);
  }, []);

  const moveModelSelection = useCallback((delta: number) => {
    setSelectedModelIndex((prev) => {
      if (models.length === 0) return 0;
      return (prev + delta + models.length) % models.length;
    });
  }, [models.length]);

  const confirmModelSelection = useCallback(() => {
    const selected = models[selectedModelIndex];
    if (!selected) return;
    setModelPickerLoading(true);
    gw.send({ cmd: "set_model", key: selected.key });
  }, [gw, models, selectedModelIndex]);

  const confirmToolApproval = useCallback((decision: ToolApprovalDecision) => {
    const pending = pendingToolApprovalRef.current;
    if (!pending) return;
    gw.send({ cmd: "tool_approval", id: pending.id, decision });
    setPendingToolApproval(null);
    setStatusText(
      decision === "session"
        ? "tool allowed for session"
        : decision === "once"
          ? "tool approved"
          : "tool denied"
    );
  }, [gw]);

  const moveUserInputSelection = useCallback((delta: number) => {
    setUserInputSelectedIndex((previous) => {
      const options = pendingUserInputRef.current?.options || [];
      if (options.length === 0) return 0;
      return (previous + delta + options.length) % options.length;
    });
  }, []);

  const sendUserInputResponse = useCallback((response: Record<string, unknown>) => {
    const pending = pendingUserInputRef.current;
    if (!pending) return;
    gw.send({ cmd: "user_input_response", id: pending.id, ...response });
    setPendingUserInput(null);
    composer.actions.clearIn();
    setStatusText(response.cancelled ? "input cancelled" : "input received");
  }, [composer.actions, gw]);

  const submitUserInput = useCallback((text: string) => {
    const pending = pendingUserInputRef.current;
    if (!pending) return;

    const value = text.trim();
    if (value && pending.allowFreeText) {
      sendUserInputResponse({
        value,
        label: value,
        free_text: true,
        cancelled: false,
      });
      return;
    }

    const option = pending.options[userInputSelectedIndex];
    if (option) {
      sendUserInputResponse({
        value: option.value,
        label: option.label,
        free_text: false,
        cancelled: false,
      });
    }
  }, [sendUserInputResponse, userInputSelectedIndex]);

  const cancelUserInput = useCallback(() => {
    sendUserInputResponse({ cancelled: true });
  }, [sendUserInputResponse]);

  const moveTaskRecoverySelection = useCallback((delta: number) => {
    setTaskRecoverySelectedIndex((previous) => (previous + delta + 2) % 2);
  }, []);

  const confirmTaskRecovery = useCallback(() => {
    if (!pendingTaskRecovery) return;
    const command = taskRecoverySelectedIndex === 0 ? "task_resume" : "task_abandon";
    gw.send({ cmd: command, id: pendingTaskRecovery.id });
    setStatusText(taskRecoverySelectedIndex === 0 ? "resuming task" : "closing task");
  }, [gw, pendingTaskRecovery, taskRecoverySelectedIndex]);

  const submission = useSubmission({
    composerActions: composer.actions,
    composerRefs: composer.refs,
    gw,
    appendMessage,
    setBusy,
    setStatusText,
    onChatStart: resetLiveOutput,
    busy,
    handleCommand,
    hintIdx,
  });

  useInputHandlers({
    composerActions: composer.actions,
    composerRefs: composer.refs,
    composerState: composer.state,
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
  } as any);

  // Gateway events
  useEffect(() => {
    gw.on("event", (ev: ServerEvent) => {
      switch (ev.type) {
        case "init":
          setModel(ev.model || "");
          setCwd(ev.cwd || "");
          setStarted(true);
          if (ev.usage) setUsage(ev.usage);
          if (ev.task !== undefined) setTaskPlan(ev.task || null);
          if (ev.companion_hint) {
            appendMessage({ role: "system", text: ev.companion_hint });
          }
          if (ev.recovery_task) {
            setPendingTaskRecovery(ev.recovery_task);
            setTaskRecoverySelectedIndex(0);
            setBusy(true);
          }
          if (ev.recent?.id) gw.send({ cmd: "resume", id: ev.recent.id });
          break;
        case "resumed":
          if (ev.title) setLastQuery(ev.title);
          if (ev.usage) setUsage(ev.usage);
          if (ev.task !== undefined) setTaskPlan(ev.task || null);
          if (ev.companion_hint) {
            appendMessage({ role: "system", text: ev.companion_hint });
          }
          if (ev.recovery_task) {
            setPendingTaskRecovery(ev.recovery_task);
            setTaskRecoverySelectedIndex(0);
            setBusy(true);
          }
          break;
        case "assistant_delta": {
          const delta = ev.text || "";
          if (delta) {
            setStreamingText((prev) => {
              const next = prev + delta;
              streamingTextRef.current = next;
              return next;
            });
          }
          setBusy(true);
          setStatusText("writing");
          break;
        }
        case "done":
          setStatusText("");
          appendMessage({
            role: "assistant",
            text: ev.text || streamingTextRef.current || "",
          });
          resetStreamingText();
          if (ev.usage) setUsage(ev.usage);
          if (ev.task !== undefined) setTaskPlan(ev.task || null);
          setBusy(false);
          break;
        case "error":
          setStatusText("");
          resetStreamingText();
          appendMessage({ role: "error", text: ev.text || "Error" });
          setBusy(false);
          break;
        case "ok":
          if (ev.usage) setUsage(ev.usage);
          if (ev.text) appendMessage({ role: "system", text: ev.text });
          break;
        case "thinking": setStatusText("thinking"); break;
        case "memory_check":
          setStatusText("remembering");
          break;
        case "memory_saved":
          setStatusText(`remembered ${ev.count || 1}`);
          break;
        case "companion_check":
          setStatusText("updating companion state");
          break;
        case "companion_updated":
          setStatusText("companion state updated");
          break;
        case "companion_resume":
          setStatusText("continuing companion thread");
          break;
        case "history_recall":
          setStatusText(`recalled ${ev.count || 1} history`);
          break;
        case "plan_updated":
          setTaskPlan(ev.task || null);
          setStatusText("plan updated");
          break;
        case "task_status":
          setTaskPlan(ev.task || null);
          appendMessage({ role: "system", text: ev.text || "当前没有任务计划。" });
          break;
        case "task_recovery_result":
          setPendingTaskRecovery(null);
          setTaskPlan(ev.task || null);
          setBusy(false);
          setStatusText("");
          appendMessage({
            role: ev.success === false ? "error" : "system",
            text: ev.text || (ev.action === "resume" ? "已恢复任务" : "已放弃任务"),
          });
          break;
        case "context_compaction_start":
          setStatusText("compacting context");
          break;
        case "context_compaction_done":
          setStatusText("context compacted");
          break;
        case "context_compaction_failed":
          setStatusText("context unchanged");
          break;
        case "context_compaction_skipped":
          setStatusText("context kept");
          break;
        case "tool_start": {
          const name = ev.name || "tool";
          setBusy(true);
          setStatusText(`tool: ${name}`);
          setToolEvents((prev) => [
            ...prev.slice(-5),
            {
              id: `${Date.now()}-${prev.length}-${name}`,
              name,
              status: "running",
            },
          ]);
          break;
        }
        case "tool_result": {
          const name = ev.name || "tool";
          const text = ev.text || "";
          setStatusText(`tool: ${name} done`);
          setToolEvents((prev) => {
            const next = [...prev];
            let idx = -1;
            for (let i = next.length - 1; i >= 0; i -= 1) {
              if (next[i].name === name && next[i].status === "running") {
                idx = i;
                break;
              }
            }
            const doneEvent = {
              id: `${Date.now()}-${prev.length}-${name}`,
              name,
              status: "done" as const,
              text,
            };
            if (idx === -1) return [...next.slice(-5), doneEvent];
            next[idx] = { ...next[idx], status: "done", text };
            return next.slice(-6);
          });
          break;
        }
        case "tool_approval_waiting":
          setStatusText(`confirm ${ev.name || "tool"}`);
          break;
        case "tool_approval_request":
          setPendingToolApproval({
            id: ev.id || "",
            name: ev.name || "tool",
            risk: ev.risk || "medium",
            reason: ev.reason || "",
            arguments: ev.arguments || "{}",
          });
          setBusy(true);
          setStatusText(`confirm ${ev.name || "tool"}`);
          break;
        case "tool_approval_result":
          setPendingToolApproval(null);
          setStatusText(
            ev.decision === "session"
              ? "tool allowed for session"
              : ev.approved
                ? "tool approved"
                : "tool denied"
          );
          break;
        case "user_input_waiting":
          setStatusText("awaiting input");
          break;
        case "user_input_request":
          setPendingUserInput({
            id: ev.id || "",
            question: ev.question || "请补充你的需求",
            options: (ev.options || []).map((option) => ({
              label: option.label,
              description: option.description || "",
              value: option.value || option.label,
            })),
            allowFreeText: ev.allow_free_text !== false,
          });
          setUserInputSelectedIndex(0);
          composer.actions.clearIn();
          setBusy(true);
          setStatusText("awaiting input");
          break;
        case "user_input_result":
          setPendingUserInput(null);
          setStatusText(ev.cancelled ? "input cancelled" : "input received");
          break;
        case "tool": setStatusText(`tool: ${ev.name || "?"}`); break;
        case "models": {
          const list = ev.models || [];
          const activeIndex = Math.max(0, list.findIndex((item) => item.active || item.key === ev.active));
          setModels(list);
          setSelectedModelIndex(activeIndex);
          setModelPickerOpen(true);
          setModelPickerLoading(false);
          break;
        }
        case "model_changed":
          setModel(ev.model || "");
          if (ev.usage) setUsage(ev.usage);
          if (ev.task !== undefined) setTaskPlan(ev.task || null);
          setModelPickerOpen(false);
          setModelPickerLoading(false);
          appendMessage({ role: "system", text: `已切换模型: ${ev.model || ev.key || ""}` });
          break;
        case "convs":
          appendMessage({ role: "system", text: "历史对话:\n" + (ev.convs || []).map((c: any, i: number) => `  [${i + 1}] ${c.title}`).join("\n") });
          break;
        case "sessions":
          appendMessage({ role: "system", text: ev.text || "暂无历史会话。" });
          setStatusText("");
          setBusy(false);
          break;
        case "session_search":
          appendMessage({ role: "system", text: ev.text || "没有找到相关历史会话。" });
          setStatusText("");
          setBusy(false);
          break;
        case "session_loaded":
          setStatusText("");
          setBusy(false);
          if (ev.usage) setUsage(ev.usage);
          if (ev.task !== undefined) setTaskPlan(ev.task || null);
          if (ev.success) {
            setMessages([]);
            setLastQuery(ev.title || "");
            resetLiveOutput();
            appendMessage({ role: "system", text: ev.text || "已加载历史会话。" });
          } else {
            appendMessage({ role: "error", text: ev.text || "加载历史会话失败。" });
          }
          break;
        case "memory":
          appendMessage({ role: "system", text: ev.text || "暂无记忆" });
          setBusy(false);
          break;
        case "companion":
          appendMessage({ role: "system", text: ev.text || "暂无陪伴状态。" });
          setStatusText("");
          setBusy(false);
          break;
        case "memory_search":
          appendMessage({ role: "system", text: ev.text || "没有找到相关向量记忆。" });
          setStatusText("");
          setBusy(false);
          break;
        case "memory_action":
          appendMessage({
            role: ev.success ? "system" : "error",
            text: ev.text || "记忆操作失败",
          });
          setStatusText("");
          setBusy(false);
          break;
        case "audit": {
          const records = ev.records || [];
          const lines = records.map((record) => {
            const icon = record.success ? "✓" : record.executed ? "!" : "×";
            const time = record.timestamp?.slice(11, 19) || "--:--:--";
            return `${icon} ${time} ${record.tool || "?"} · ${record.decision || "?"} · ${record.duration_ms || 0}ms`;
          });
          appendMessage({
            role: "system",
            text: lines.length ? "工具审计:\n" + lines.join("\n") : "暂无工具审计记录",
          });
          break;
        }
        case "skills": {
          const grouped = new Map<string, NonNullable<ServerEvent["skills"]>>();
          for (const skill of ev.skills || []) {
            const items = grouped.get(skill.category) || [];
            items.push(skill);
            grouped.set(skill.category, items);
          }
          const lines: string[] = [];
          for (const [category, skills] of grouped) {
            lines.push(`[${category}]`);
            for (const skill of skills) {
              const counts = skill.resource_counts || {};
              const resourceCount = Object.values(counts).reduce((sum, count) => sum + count, 0);
              const suffix = resourceCount ? ` · ${resourceCount} resources` : "";
              const mark = skill.offered === false
                ? "-"
                : skill.readiness_status === "setup_needed" ? "!" : "+";
              const readiness = skill.readiness_reason ? ` · ${skill.readiness_reason}` : "";
              lines.push(`  ${mark} ${skill.name}${suffix}${readiness}\n    ${skill.description}`);
            }
          }
          for (const error of ev.errors || []) lines.push(`! ${error}`);
          appendMessage({
            role: ev.errors?.length ? "error" : "system",
            text: `${ev.reloaded ? "技能已重新加载" : "Skills"} · ${(ev.skills || []).length}\n${lines.join("\n")}`,
          });
          setStatusText("");
          setBusy(false);
          break;
        }
        case "skills_stats":
          appendMessage({ role: "system", text: ev.text || "暂无 Skill 使用记录" });
          setStatusText("");
          setBusy(false);
          break;
        case "mcp": {
          const servers = ev.status?.servers || [];
          const lines = servers.length
            ? servers.map((server) => {
                const mark = server.status === "running" ? "✓" : server.enabled ? "!" : "-";
                const error = server.error ? ` · ${server.error.slice(0, 80)}` : "";
                const transport = server.transport || "stdio";
                return `${mark} ${server.name} · ${transport} · ${server.status} · ${server.tools} tools${error}`;
              })
            : ["No MCP servers configured"];

          appendMessage({ role: "system", text: "MCP:\n" + lines.join("\n") });
          break;
        }
        case "ok": appendMessage({ role: "system", text: ev.text || "完成" }); break;
        case "bye":
          process.stderr.write("\nGoodbye!\n");
          process.exit(0);
      }
    });

    gw.on("exit", () => {
      process.stderr.write("\nGoodbye!\n");
      process.exit(0);
    });

    gw.send({ cmd: "init", cwd: process.cwd() });
  }, [appendMessage]);

  function stop() { gw.stop(); }

  return {
    messages, streamingText, toolEvents, pendingToolApproval, pendingUserInput, userInputSelectedIndex,
    taskPlan, pendingTaskRecovery, taskRecoverySelectedIndex,
    busy, model, cwd, usage, started, statusText, lastQuery, cols,
    composer, hintIdx, setHintIdx,
    modelPicker: {
      open: modelPickerOpen,
      loading: modelPickerLoading,
      models,
      selectedIndex: selectedModelIndex,
    },
    handleCommand, closeModelPicker, moveModelSelection, confirmModelSelection, confirmToolApproval,
    moveUserInputSelection, submitUserInput, cancelUserInput,
    moveTaskRecoverySelection, confirmTaskRecovery, stop,
  };
}
