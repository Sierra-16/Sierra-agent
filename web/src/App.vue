<template>
  <div class="app-shell">
    <SidebarShell
      :active-session-id="activeSessionId"
      :active-view="activeView"
      :error="error"
      :loading="loading"
      :nav-items="mainNav"
      :payload="payload"
      :recent-sessions="recentSessions"
      @new-chat="startLocalChat"
      @open-session="openSession"
      @refresh="loadDashboard"
      @open-settings="settingsOpen = true"
      @select-view="activeView = $event"
    />

    <section class="main-shell">
      <main v-if="payload" class="content-stage">
        <ChatWorkspace
          :active-model-label="activeModelLabel"
          :activity-events="activityEvents"
          :error="error"
          :loading="loading"
          :messages="chatMessages"
          :sending="sending"
          :usage-percent="usagePercent"
          :workspace="payload?.identity.workspace"
          @approve-tool="respondToolApproval"
          @refresh="loadDashboard"
          @respond-user-input="respondUserInput"
          @send="sendChat"
        />
      </main>

      <main v-else class="loading-state">
        <Sparkles :size="30" />
        <p>{{ error || "正在唤醒 Sierra..." }}</p>
      </main>
    </section>

    <SettingsDrawer
      :active-model-label="activeModelLabel"
      :open="settingsOpen"
      :payload="payload"
      :usage-percent="usagePercent"
      @close="settingsOpen = false"
      @run-command="runCommandFromPanel"
    />
  </div>
</template>

<script setup lang="ts">
import { MessageCircle, Sparkles } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import ChatWorkspace from "./components/ChatWorkspace.vue";
import SettingsDrawer from "./components/SettingsDrawer.vue";
import SidebarShell from "./components/SidebarShell.vue";
import type {
  ChatActivityEvent,
  ChatActivityStatus,
  ChatMessage,
  DashboardPayload,
  NavItem,
  SessionSummary,
  ViewId
} from "./types";

type CommandPayload = {
  command?: string;
  text?: string;
  key?: string;
  id?: string;
  query?: string;
  prompt?: string;
  count?: number;
  limit?: number;
  interval_minutes?: number;
  confirmed?: boolean;
};

const payload = ref<DashboardPayload | null>(null);
const loading = ref(false);
const sending = ref(false);
const loadingConversation = ref(false);
const error = ref("");
const autoRefresh = ref(true);
const activeView = ref<ViewId>("chat");
const activeSessionId = ref("");
const settingsOpen = ref(false);
const chatMessages = ref<ChatMessage[]>([]);
const activityEvents = ref<ChatActivityEvent[]>([]);
const bootstrappedConversation = ref(false);
let timer: number | undefined;

const mainNav: NavItem[] = [
  { id: "chat", label: "会话", subtitle: "Chat", icon: MessageCircle }
];

const usagePercent = computed(() => Number(payload.value?.usage.percent || 0));

const activeModelLabel = computed(() => {
  const active = payload.value?.identity.models?.find((model: any) => model.active);
  return active ? `${active.key} · ${active.name}` : payload.value?.identity.model || "loading";
});

const recentSessions = computed<SessionSummary[]>(() => {
  return Array.isArray(payload.value?.conversation.recent) ? payload.value.conversation.recent : [];
});

function newId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function appendSystem(text: string) {
  const clean = String(text || "").trim();
  if (!clean) {
    return;
  }
  chatMessages.value.push({ id: newId(), role: "system", text: clean });
}

function mapMessages(messages: any[]): ChatMessage[] {
  return messages
    .filter((message) => message && ["user", "assistant", "system"].includes(message.role))
    .map((message) => {
      const role: ChatMessage["role"] =
        message.role === "user" ? "user" : message.role === "system" ? "system" : "assistant";
      return {
        id: newId(),
        role,
        text: String(message.text || "")
      };
    })
    .filter((message) => message.text.trim());
}

function openSession(sessionId: string) {
  loadConversation(sessionId);
}

async function startLocalChat() {
  activeView.value = "chat";
  activeSessionId.value = "";
  sending.value = false;
  activityEvents.value = [];
  try {
    await runCommandPayload({ command: "new", text: "/new" }, { appendUser: false, appendResult: false });
  } catch {
    try {
      await fetch("/api/conversations/new", { method: "POST" });
    } catch {
      // Keep the page usable while the backend is still warming up.
    }
  }
  chatMessages.value = [
    {
      id: newId(),
      role: "assistant",
      text: "新会话开好了。别磨蹭啦，今天要让 Sierra 做什么？"
    }
  ];
}

async function loadConversation(sessionId: string) {
  if (!sessionId || loadingConversation.value) {
    return;
  }
  loadingConversation.value = true;
  activeView.value = "chat";
  sending.value = false;
  activityEvents.value = [];
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(sessionId)}`);
    if (!response.ok) {
      throw new Error(`Conversation API ${response.status}`);
    }
    const data = await response.json();
    activeSessionId.value = sessionId;
    chatMessages.value = Array.isArray(data.messages) ? mapMessages(data.messages) : [];
    await loadDashboard({ bootstrap: false });
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loadingConversation.value = false;
  }
}

async function sendChat(message: string, options: { appendUser?: boolean } = {}) {
  const text = message.trim();
  if (!text || sending.value) {
    return;
  }

  if (text.startsWith("/") && options.appendUser !== false) {
    await runCommandText(text);
    return;
  }

  if (options.appendUser !== false) {
    chatMessages.value.push({ id: newId(), role: "user", text });
  }
  sending.value = true;
  activityEvents.value = [
    {
      id: "thinking",
      type: "thinking",
      label: "思考中",
      detail: "Sierra 正在整理上下文和下一步。",
      status: "active"
    }
  ];

  const assistantId = newId();
  let hasAssistantMessage = false;
  let doneAnswer = "";

  const ensureAssistantMessage = () => {
    if (!hasAssistantMessage) {
      chatMessages.value.push({ id: assistantId, role: "assistant", text: "" });
      hasAssistantMessage = true;
    }
    return chatMessages.value.find((item) => item.id === assistantId);
  };

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    });
    if (!response.ok) {
      throw new Error(`Chat API ${response.status}`);
    }
    if (!response.body) {
      throw new Error("Chat API did not return a stream");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        processChatStreamLine(line, ensureAssistantMessage, (value) => {
          doneAnswer = value;
        });
      }
    }

    if (buffer.trim()) {
      processChatStreamLine(buffer, ensureAssistantMessage, (value) => {
        doneAnswer = value;
      });
    }

    if (!hasAssistantMessage && doneAnswer) {
      chatMessages.value.push({ id: assistantId, role: "assistant", text: doneAnswer });
      hasAssistantMessage = true;
    }
    if (!hasAssistantMessage) {
      chatMessages.value.push({
        id: assistantId,
        role: "assistant",
        text: "我这边没拿到回复。别看我，肯定是哪条链路没接好。"
      });
    }
    await loadDashboard({ bootstrap: false });
  } catch (err) {
    chatMessages.value.push({
      id: newId(),
      role: "assistant",
      text: `网页聊天失败: ${err instanceof Error ? err.message : String(err)}`
    });
    upsertActivity("error", {
      type: "error",
      label: "处理失败",
      detail: err instanceof Error ? err.message : String(err),
      status: "error"
    });
  } finally {
    sending.value = false;
    markAllActivityDone();
    window.setTimeout(() => {
      if (!sending.value) {
        activityEvents.value = [];
      }
    }, 1400);
  }
}

async function runCommandText(text: string) {
  const command = text.trim().split(/\s+/)[0] || "/help";
  await runCommandPayload({ command, text }, { appendUser: true, appendResult: true });
}

async function runCommandFromPanel(command: string | Record<string, any>) {
  await runCommandPayload(command, { appendUser: false, appendResult: true });
}

async function runCommandPayload(
  command: string | Record<string, any>,
  options: { appendUser: boolean; appendResult: boolean; confirmed?: boolean }
) {
  if (sending.value) {
    return;
  }
  const rawBody = typeof command === "string"
    ? { command: command.trim().split(/\s+/)[0] || "/help", text: command }
    : { ...command };
  const body: CommandPayload = {
    ...rawBody,
    command: String(rawBody.command || rawBody.text || "/help").trim().split(/\s+/)[0] || "/help"
  };
  if (options.confirmed) {
    body.confirmed = true;
  }
  if (options.appendUser) {
    chatMessages.value.push({ id: newId(), role: "user", text: body.text || body.command || "/help" });
  }
  sending.value = true;
  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Command API ${response.status}`);
    }
    if (data.requires_confirmation) {
      const confirmed = window.confirm(String(data.text || "确认执行这个操作？"));
      if (confirmed) {
        sending.value = false;
        await runCommandPayload({ ...body, confirmed: true }, { appendUser: false, appendResult: options.appendResult, confirmed: true });
      } else if (options.appendResult) {
        appendSystem("已取消操作。");
      }
      return;
    }
    await handleCommandResult(data, options);
  } catch (err) {
    appendSystem(`命令执行失败: ${err instanceof Error ? err.message : String(err)}`);
  } finally {
    sending.value = false;
    await loadDashboard({ bootstrap: false });
  }
}

async function handleCommandResult(data: any, options: { appendResult: boolean }) {
  if (Array.isArray(data.messages)) {
    chatMessages.value = mapMessages(data.messages);
  }
  if (data.type === "new") {
    chatMessages.value = [
      {
        id: newId(),
        role: "assistant",
        text: "新会话开好了。哼，说吧。"
      }
    ];
    activeSessionId.value = "";
    return;
  }
  if (data.type === "session_loaded") {
    activeSessionId.value = String(data.id || "");
  }
  if (data.type === "retry_ready" && data.query) {
    if (options.appendResult && data.text) {
      appendSystem(data.text);
    }
    sending.value = false;
    await sendChat(String(data.query));
    return;
  }
  if (options.appendResult && data.text) {
    appendSystem(String(data.text));
  }
}

function processChatStreamLine(
  line: string,
  ensureAssistantMessage: () => ChatMessage | undefined,
  setDoneAnswer: (value: string) => void
) {
  if (!line.trim()) {
    return;
  }
  const event = JSON.parse(line);
  if (event.type === "assistant_delta") {
    const assistant = ensureAssistantMessage();
    if (assistant) {
      assistant.text += String(event.text || "");
    }
    markActivity("thinking", { status: "done", detail: "Sierra 开始回复。" });
    return;
  }
  if (event.type === "done") {
    setDoneAnswer(String(event.answer || ""));
    markAllActivityDone();
    return;
  }
  handleActivityEvent(event);
}

function upsertActivity(
  id: string,
  patch: Omit<ChatActivityEvent, "id"> & { status?: ChatActivityStatus }
) {
  const existing = activityEvents.value.find((event) => event.id === id);
  if (existing) {
    Object.assign(existing, patch);
    return;
  }
  activityEvents.value.push({
    id,
    ...patch,
    status: patch.status || "active"
  });
}

function markActivity(id: string, patch: Partial<ChatActivityEvent>) {
  const existing = activityEvents.value.find((event) => event.id === id);
  if (existing) {
    Object.assign(existing, patch);
  }
}

function markAllActivityDone() {
  for (const event of activityEvents.value) {
    if (event.status === "active" && event.type !== "approval" && event.type !== "user-input") {
      event.status = "done";
    }
  }
}

function handleActivityEvent(event: any) {
  const type = String(event?.type || "");
  if (!type) {
    return;
  }

  if (type === "thinking") {
    upsertActivity("thinking", {
      type,
      label: "思考中",
      detail: "Sierra 正在整理上下文和下一步。",
      status: "active"
    });
    return;
  }

  if (type === "tool_start" || type === "tool") {
    const name = String(event.name || "tool");
    upsertActivity(`tool:${name}`, {
      type: "tool",
      label: "调用工具",
      detail: "正在准备参数并执行。",
      status: "active",
      toolName: name,
      progress: 64
    });
    return;
  }

  if (type === "tool_result") {
    const name = String(event.name || "tool");
    upsertActivity(`tool:${name}`, {
      type: "tool",
      label: event.success === false ? "工具失败" : "工具完成",
      detail: event.text ? String(event.text) : "执行完成。",
      status: event.success === false ? "error" : "done",
      toolName: name,
      progress: 100
    });
    return;
  }

  if (type === "tool_approval_waiting") {
    const name = String(event.name || "tool");
    upsertActivity(`approval-waiting:${name}`, {
      type: "approval",
      label: "需要确认",
      detail: "Sierra 需要你的许可才能继续执行这个工具。",
      status: "active",
      toolName: name,
      risk: String(event.risk || "")
    });
    return;
  }

  if (type === "tool_approval_request") {
    const approvalId = String(event.id || "");
    const name = String(event.name || "tool");
    activityEvents.value = activityEvents.value.filter((item) => item.id !== `approval-waiting:${name}`);
    upsertActivity(`approval:${approvalId}`, {
      type: "approval",
      label: "需要确认",
      detail: "请确认是否允许 Sierra 执行这个工具。",
      status: "active",
      toolName: name,
      approvalId,
      risk: String(event.risk || ""),
      reason: String(event.reason || ""),
      arguments: stringifyArguments(event.arguments)
    });
    return;
  }

  if (type === "tool_approval_result") {
    const approvalId = String(event.id || "");
    const approved = Boolean(event.approved);
    upsertActivity(`approval:${approvalId}`, {
      type: "approval",
      label: approved ? "已批准" : "已拒绝",
      detail: approved
        ? `许可范围: ${event.decision === "session" ? "本会话" : "仅本次"}`
        : event.timed_out ? "等待超时，已拒绝。" : "工具调用已拒绝。",
      status: approved ? "done" : "error",
      approvalId,
      decision: String(event.decision || "")
    });
    return;
  }

  if (type === "user_input_waiting") {
    upsertActivity("user-input-waiting", {
      type: "user-input",
      label: "等待补充",
      detail: "Sierra 需要你补充选择或说明。",
      status: "active"
    });
    return;
  }

  if (type === "user_input_request") {
    const inputId = String(event.id || "");
    activityEvents.value = activityEvents.value.filter((item) => item.id !== "user-input-waiting");
    upsertActivity(`user-input:${inputId}`, {
      type: "user-input",
      label: "需要补充信息",
      detail: String(event.question || "请选择下一步。"),
      status: "active",
      inputId,
      question: String(event.question || ""),
      options: Array.isArray(event.options) ? event.options : [],
      allowFreeText: Boolean(event.allow_free_text)
    });
    return;
  }

  if (type === "user_input_result") {
    const inputId = String(event.id || "");
    upsertActivity(`user-input:${inputId}`, {
      type: "user-input",
      label: event.cancelled ? "已跳过补充" : "已收到补充",
      detail: event.cancelled ? "Sierra 将按已有信息继续。" : String(event.label || "选择已提交。"),
      status: event.cancelled ? "error" : "done",
      inputId
    });
    return;
  }

  if (type === "context_compaction_start") {
    upsertActivity("context", {
      type: "context",
      label: "压缩上下文",
      detail: "正在整理较早的对话，让当前请求继续。",
      status: "active"
    });
    return;
  }

  if (type === "context_compaction_done") {
    upsertActivity("context", {
      type: "context",
      label: "上下文已压缩",
      detail: "历史轮次已摘要化，当前请求继续执行。",
      status: "done"
    });
    return;
  }

  if (type === "context_tool_results_trimmed") {
    upsertActivity("context-trim", {
      type: "context",
      label: "工具结果已裁剪",
      detail: `${event.count || 0} 个旧工具结果已压缩。`,
      status: "done"
    });
    return;
  }

  if (type === "context_references") {
    upsertActivity("references", {
      type: "reference",
      label: "已附加引用",
      detail: `${event.count || 0} 个 @ 引用已展开。`,
      status: "done"
    });
    return;
  }

  if (type === "history_recall") {
    upsertActivity("history", {
      type: "history",
      label: "检索历史",
      detail: `找到 ${event.count || 0} 条相关旧对话。`,
      status: "done"
    });
    return;
  }

  if (type === "memory_check") {
    upsertActivity("memory", {
      type: "memory",
      label: "检查记忆",
      detail: "正在判断这一轮是否值得长期保存。",
      status: "active"
    });
    return;
  }

  if (type === "memory_saved") {
    upsertActivity("memory", {
      type: "memory",
      label: "记忆已更新",
      detail: `保存了 ${event.count || 0} 条信息。`,
      status: "done"
    });
    return;
  }

  if (type === "tool_denied_by_web" || type === "user_input_cancelled_by_web") {
    upsertActivity(`web:${type}`, {
      type: "tool",
      label: "Web 未授权",
      detail: "这次请求没有获得继续执行所需的网页交互。",
      status: "error",
      toolName: String(event.name || "")
    });
    return;
  }

  if (type === "error") {
    upsertActivity("error", {
      type: "error",
      label: "处理失败",
      detail: String(event.text || "unknown error"),
      status: "error"
    });
  }
}

function stringifyArguments(value: any) {
  if (value === undefined || value === null || value === "") {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

async function respondToolApproval(id: string, decision: "once" | "session" | "deny") {
  const event = activityEvents.value.find((item) => item.approvalId === id);
  if (event) {
    event.status = "muted";
    event.detail = decision === "deny" ? "正在拒绝工具调用..." : "正在提交许可...";
    event.decision = decision;
  }
  try {
    const response = await fetch("/api/chat/approval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, decision })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `Approval API ${response.status}`);
    }
  } catch (err) {
    if (event) {
      event.status = "error";
      event.detail = err instanceof Error ? err.message : String(err);
    }
  }
}

async function respondUserInput(
  id: string,
  input: { value?: string; label?: string; free_text?: string; cancelled?: boolean }
) {
  const event = activityEvents.value.find((item) => item.inputId === id);
  if (event) {
    event.status = "muted";
    event.detail = input.cancelled ? "正在跳过补充..." : "正在提交补充信息...";
  }
  try {
    const response = await fetch("/api/chat/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, ...input })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `Input API ${response.status}`);
    }
  } catch (err) {
    if (event) {
      event.status = "error";
      event.detail = err instanceof Error ? err.message : String(err);
    }
  }
}

async function loadDashboard(options: { bootstrap?: boolean } = {}) {
  const shouldBootstrap = options.bootstrap !== false;
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/dashboard?ts=${Date.now()}`);
    if (!response.ok) {
      throw new Error(`Dashboard API ${response.status}`);
    }
    payload.value = await response.json();
    if (shouldBootstrap && !bootstrappedConversation.value) {
      bootstrappedConversation.value = true;
      const latest = Array.isArray(payload.value?.conversation.recent)
        ? payload.value.conversation.recent[0]
        : null;
      if (latest?.id) {
        await loadConversation(latest.id);
      }
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

function startTimer() {
  window.clearInterval(timer);
  if (autoRefresh.value) {
    timer = window.setInterval(() => loadDashboard({ bootstrap: false }), 5000);
  }
}

watch(autoRefresh, startTimer);

onMounted(() => {
  loadDashboard();
  startTimer();
});

onUnmounted(() => {
  window.clearInterval(timer);
});
</script>
