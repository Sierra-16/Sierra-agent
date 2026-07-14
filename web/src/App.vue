<template>
  <div ref="appShellRef" class="app-shell">
    <SidebarShell
      :active-session-id="activeSessionId"
      :active-view="activeView"
      :error="error"
      :loading="loading"
      :nav-items="mainNav"
      :payload="payload"
      :recent-sessions="recentSessions"
      @delete-session="deleteSession"
      @new-chat="startLocalChat"
      @open-session="openSession"
      @rename-session="renameSession"
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
          :plan-mode="planMode"
          :plan-mode-loading="planModeLoading"
          :sending="sending"
          :usage-percent="usagePercent"
          :workspace="payload?.identity.workspace"
          @approve-tool="respondToolApproval"
          @cancel-chat="cancelChat"
          @refresh="loadDashboard"
          @respond-user-input="respondUserInput"
          @send="sendChat"
          @toggle-plan-mode="togglePlanMode"
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
      @refresh="loadDashboard"
    />
  </div>
</template>

<script setup lang="ts">
import { MessageCircle, Sparkles } from "lucide-vue-next";
import { gsap } from "gsap";
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
const planModeLoading = ref(false);
const loadingConversation = ref(false);
const error = ref("");
const autoRefresh = ref(true);
const activeView = ref<ViewId>("chat");
const activeSessionId = ref("");
const settingsOpen = ref(false);
const chatMessages = ref<ChatMessage[]>([]);
const activityEvents = ref<ChatActivityEvent[]>([]);
const bootstrappedConversation = ref(false);
const appShellRef = ref<HTMLElement | null>(null);
let timer: number | undefined;
let activeChatAbortController: AbortController | null = null;
let shellMotion: ReturnType<typeof gsap.matchMedia> | undefined;
let toolRunCounter = 0;
let conversationLoadSeq = 0;
let chatRunSeq = 0;
let conversationActivationPromise: Promise<void> | null = null;
const activeToolRuns = new Map<string, string>();

const mainNav: NavItem[] = [
  { id: "chat", label: "会话", subtitle: "Chat", icon: MessageCircle }
];

const usagePercent = computed(() => Number(payload.value?.usage.percent || 0));
const planMode = computed(() => Boolean(payload.value?.mode?.plan_mode?.enabled));

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

function resetActivityRunTracking() {
  toolRunCounter = 0;
  activeToolRuns.clear();
}

function beginToolRun(name: string) {
  toolRunCounter += 1;
  const id = `tool:${name}:${toolRunCounter}`;
  activeToolRuns.set(name, id);
  return id;
}

function resolveToolRun(name: string) {
  const activeId = activeToolRuns.get(name);
  if (activeId) {
    activeToolRuns.delete(name);
    return activeId;
  }
  const latestActive = [...activityEvents.value]
    .reverse()
    .find((event) => event.type === "tool" && event.toolName === name && event.status === "active");
  if (latestActive) {
    return latestActive.id;
  }
  return beginToolRun(name);
}

function appendSystem(text: string) {
  const clean = String(text || "").trim();
  if (clean) {
    chatMessages.value.push({ id: newId(), role: "system", text: clean });
  }
}

function applyUsageSnapshot(usage: any) {
  if (!usage || !payload.value) {
    return;
  }
  payload.value = {
    ...payload.value,
    usage: {
      ...payload.value.usage,
      ...usage
    }
  };
}

function applyModeSnapshot(mode: any) {
  if (!mode || !payload.value) {
    return;
  }
  payload.value = {
    ...payload.value,
    mode: {
      ...payload.value.mode,
      ...mode
    }
  };
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

async function activateConversation(sessionId: string, requestId: number) {
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(sessionId)}/activate`, {
      method: "POST"
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Conversation activate API ${response.status}`);
    }
    if (requestId !== conversationLoadSeq) {
      return;
    }
    applyUsageSnapshot(data.usage);
    await loadDashboard({ bootstrap: false });
  } catch (err) {
    if (requestId === conversationLoadSeq) {
      error.value = err instanceof Error ? err.message : String(err);
    }
  } finally {
    if (requestId === conversationLoadSeq) {
      loadingConversation.value = false;
      conversationActivationPromise = null;
    }
  }
}

async function startLocalChat() {
  conversationLoadSeq += 1;
  chatRunSeq += 1;
  activeChatAbortController?.abort();
  if (sending.value) {
    void fetch("/api/chat/cancel", { method: "POST" });
  }
  conversationActivationPromise = null;
  activeView.value = "chat";
  activeSessionId.value = "";
  sending.value = false;
  loadingConversation.value = false;
  activityEvents.value = [];
  try {
    await runCommandPayload({ command: "new", text: "/new" }, { appendUser: false, appendResult: false });
  } catch {
    try {
      await fetch("/api/conversations/new", { method: "POST" });
    } catch {
      // 页面仍可继续使用。
    }
  }
  chatMessages.value = [
    {
      id: newId(),
      role: "assistant",
      text: "新会话开好了。哼，说吧，今天要让 Sierra 做什么？"
    }
  ];
}

async function loadConversation(sessionId: string) {
  if (!sessionId) {
    return;
  }
  const requestId = ++conversationLoadSeq;
  chatRunSeq += 1;
  activeChatAbortController?.abort();
  conversationActivationPromise = null;
  if (sending.value) {
    void fetch("/api/chat/cancel", { method: "POST" });
  }
  loadingConversation.value = true;
  activeView.value = "chat";
  sending.value = false;
  activityEvents.value = [];
  activeSessionId.value = sessionId;
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(sessionId)}/preview`);
    if (!response.ok) {
      throw new Error(`Conversation API ${response.status}`);
    }
    const data = await response.json();
    if (requestId !== conversationLoadSeq) {
      return;
    }
    chatMessages.value = Array.isArray(data.messages) ? mapMessages(data.messages) : [];
    applyUsageSnapshot(data.usage);
    conversationActivationPromise = activateConversation(sessionId, requestId);
  } catch (err) {
    if (requestId === conversationLoadSeq) {
      error.value = err instanceof Error ? err.message : String(err);
      loadingConversation.value = false;
      conversationActivationPromise = null;
    }
  }
}

function replaceRecentSessions(updater: (items: SessionSummary[]) => SessionSummary[]) {
  if (!payload.value) {
    return;
  }
  const current = Array.isArray(payload.value.conversation?.recent)
    ? payload.value.conversation.recent
    : [];
  payload.value = {
    ...payload.value,
    conversation: {
      ...payload.value.conversation,
      recent: updater(current)
    }
  };
}

async function renameSession(value: { id: string; title: string }) {
  const sessionId = String(value?.id || "");
  const title = String(value?.title || "").trim();
  if (!sessionId || !title) {
    return;
  }
  replaceRecentSessions((items) =>
    items.map((item) => item.id === sessionId ? { ...item, title } : item)
  );
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title })
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Conversation rename API ${response.status}`);
    }
    await loadDashboard({ bootstrap: false });
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
    await loadDashboard({ bootstrap: false });
  }
}

async function deleteSession(sessionId: string) {
  sessionId = String(sessionId || "");
  if (!sessionId) {
    return;
  }
  const wasActive = activeSessionId.value === sessionId;
  conversationLoadSeq += 1;
  chatRunSeq += 1;
  activeChatAbortController?.abort();
  if (sending.value) {
    void fetch("/api/chat/cancel", { method: "POST" });
  }
  conversationActivationPromise = null;
  replaceRecentSessions((items) => items.filter((item) => item.id !== sessionId));
  if (wasActive) {
    activeSessionId.value = "";
    chatMessages.value = [];
    activityEvents.value = [];
    loadingConversation.value = false;
  }
  try {
    const response = await fetch(`/api/conversations/${encodeURIComponent(sessionId)}`, {
      method: "DELETE"
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Conversation delete API ${response.status}`);
    }
    applyUsageSnapshot(data.usage);
    await loadDashboard({ bootstrap: false });
    if (wasActive) {
      const latest = Array.isArray(payload.value?.conversation.recent)
        ? payload.value.conversation.recent[0]
        : null;
      if (latest?.id) {
        await loadConversation(latest.id);
      } else {
        chatMessages.value = [
          {
            id: newId(),
            role: "assistant",
            text: "这轮会话已经删掉了。哼，空地整理好了，重新说吧。"
          }
        ];
      }
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
    await loadDashboard({ bootstrap: false });
  }
}

async function sendChat(message: string, options: { appendUser?: boolean } = {}) {
  const text = message.trim();
  if (!text || sending.value) {
    return;
  }

  if (conversationActivationPromise) {
    await conversationActivationPromise;
  }

  if (text.startsWith("/") && options.appendUser !== false) {
    await runCommandText(text);
    return;
  }

  const chatRequestId = ++chatRunSeq;
  if (options.appendUser !== false) {
    chatMessages.value.push({ id: newId(), role: "user", text });
  }
  sending.value = true;
  resetActivityRunTracking();
  activityEvents.value = [
    {
      id: "thinking",
      type: "thinking",
      label: "思考中",
      detail: "",
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
    const controller = new AbortController();
    activeChatAbortController = controller;
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
      signal: controller.signal
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
      if (chatRequestId !== chatRunSeq) {
        controller.abort();
        return;
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
      if (chatRequestId !== chatRunSeq) {
        return;
      }
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
        text: "这边没有拿到回复。别看我，链路那边肯定有点别扭。"
      });
    }
    await loadDashboard({ bootstrap: false });
  } catch (err) {
    if (chatRequestId !== chatRunSeq) {
      return;
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      appendSystem("已中断当前处理。");
      upsertActivity("interrupted", {
        type: "error",
        label: "已中断",
        detail: "这次 Web 请求已停止，Sierra 可以继续接收新消息。",
        status: "error"
      });
      return;
    }
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
    if (chatRequestId === chatRunSeq) {
      activeChatAbortController = null;
      sending.value = false;
      markAllActivityDone();
      window.setTimeout(() => {
        if (!sending.value && chatRequestId === chatRunSeq) {
          activityEvents.value = [];
        }
      }, 1400);
    }
  }
}

async function runCommandText(text: string) {
  const command = text.trim().split(/\s+/)[0] || "/help";
  await runCommandPayload({ command, text }, { appendUser: true, appendResult: true });
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
  const commandActivityId = `command:${String(body.command || "command").replace(/[^\w-]+/g, "_")}`;
  const showCommandActivity = options.appendUser || options.appendResult;
  if (showCommandActivity) {
    activityEvents.value = [
      {
        id: commandActivityId,
        type: "command",
        label: "执行命令",
        detail: String(body.text || body.command || "/help"),
        status: "active"
      }
    ];
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
      if (showCommandActivity) {
        markActivity(commandActivityId, {
          label: "等待确认",
          detail: String(data.text || "确认执行这个命令？"),
          status: "active"
        });
      }
      const confirmed = window.confirm(String(data.text || "确认执行这个操作？"));
      if (confirmed) {
        sending.value = false;
        await runCommandPayload({ ...body, confirmed: true }, { appendUser: false, appendResult: options.appendResult, confirmed: true });
      } else if (options.appendResult) {
        appendSystem("已取消操作。");
        markActivity(commandActivityId, {
          label: "命令已取消",
          detail: String(body.text || body.command || "/help"),
          status: "error"
        });
      }
      return;
    }
    await handleCommandResult(data, options);
    if (showCommandActivity) {
      markActivity(commandActivityId, {
        label: data.ok === false ? "命令未完成" : "命令完成",
        detail: String(data.type || body.command || "command"),
        status: data.ok === false ? "error" : "done"
      });
    }
  } catch (err) {
    appendSystem(`命令执行失败: ${err instanceof Error ? err.message : String(err)}`);
    if (showCommandActivity) {
      markActivity(commandActivityId, {
        label: "命令失败",
        detail: err instanceof Error ? err.message : String(err),
        status: "error"
      });
    }
  } finally {
    sending.value = false;
    await loadDashboard({ bootstrap: false });
    if (showCommandActivity) {
      window.setTimeout(() => {
        if (!sending.value) {
          activityEvents.value = [];
        }
      }, 1400);
    }
  }
}

async function handleCommandResult(data: any, options: { appendResult: boolean }) {
  if (data.usage) {
    applyUsageSnapshot(data.usage);
  }
  if (data.mode) {
    applyModeSnapshot(data.mode);
  }
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
    closeActiveContextActivity();
    markActivity("thinking", { status: "done", detail: "" });
    return;
  }
  if (event.type === "done") {
    setDoneAnswer(String(event.answer || ""));
    markAllActivityDone();
    return;
  }
  if (event.type === "interrupted") {
    upsertActivity("interrupted", {
      type: "error",
      label: "已中断",
      detail: String(event.text || "当前处理已停止。"),
      status: "error"
    });
    markAllActivityDone();
    return;
  }
  handleActivityEvent(event);
}

async function cancelChat() {
  if (!sending.value) {
    return;
  }
  chatRunSeq += 1;
  activeChatAbortController?.abort();
  try {
    await fetch("/api/chat/cancel", { method: "POST" });
  } catch {
    // 本地中断已经足够让 Web UI 恢复。
  }
  sending.value = false;
  upsertActivity("interrupted", {
    type: "error",
    label: "已中断",
    detail: "当前 Web 处理已停止。",
    status: "error"
  });
}

async function togglePlanMode() {
  if (planModeLoading.value || sending.value) {
    return;
  }
  const nextEnabled = !planMode.value;
  planModeLoading.value = true;
  upsertActivity("mode:plan", {
    type: "context",
    label: nextEnabled ? "开启 Plan Mode" : "关闭 Plan Mode",
    detail: nextEnabled ? "切换为只规划、只读取" : "恢复正常执行模式",
    status: "active",
    progress: 60
  });
  try {
    const response = await fetch("/api/mode/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: nextEnabled })
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.text || data.error || `Mode API ${response.status}`);
    }
    applyModeSnapshot(data.mode);
    markActivity("mode:plan", {
      label: nextEnabled ? "Plan Mode 已开启" : "Plan Mode 已关闭",
      detail: data.text || "",
      status: "done",
      progress: 100
    });
  } catch (err) {
    markActivity("mode:plan", {
      label: "模式切换失败",
      detail: err instanceof Error ? err.message : String(err),
      status: "error"
    });
  } finally {
    planModeLoading.value = false;
    window.setTimeout(() => {
      if (!sending.value && !planModeLoading.value) {
        const event = activityEvents.value.find((item) => item.id === "mode:plan");
        if (event && event.status !== "active") {
          activityEvents.value = activityEvents.value.filter((item) => item.id !== "mode:plan");
        }
      }
    }, 1200);
  }
}

function upsertActivity(id: string, patch: Omit<ChatActivityEvent, "id"> & { status?: ChatActivityStatus }) {
  const existing = activityEvents.value.find((event) => event.id === id);
  if (existing) {
    Object.assign(existing, patch);
    return;
  }
  activityEvents.value.push({ id, ...patch, status: patch.status || "active" });
}

function markActivity(id: string, patch: Partial<ChatActivityEvent>) {
  const existing = activityEvents.value.find((event) => event.id === id);
  if (existing) {
    Object.assign(existing, patch);
  }
}

function normalizeCompletedActivity(event: ChatActivityEvent) {
  if (event.type === "context" && event.id === "context") {
    event.label = "上下文已整理";
    if (!event.detail || event.detail.includes("正在")) {
      event.detail = "历史轮次已摘要化或已跳过。";
    }
  }
}

function closeActiveContextActivity() {
  const contextEvent = activityEvents.value.find(
    (event) => event.id === "context" && event.type === "context" && event.status === "active"
  );
  if (!contextEvent) {
    return;
  }
  contextEvent.status = "done";
  normalizeCompletedActivity(contextEvent);
}

function markAllActivityDone() {
  for (const event of activityEvents.value) {
    if (event.status === "active" && event.type !== "approval" && event.type !== "user-input") {
      event.status = "done";
      normalizeCompletedActivity(event);
    }
  }
}

function handleActivityEvent(event: any) {
  const type = String(event?.type || "");
  if (!type) {
    return;
  }

  if (type === "thinking") {
    upsertActivity("thinking", { type, label: "思考中", detail: "", status: "active" });
    return;
  }

  if (type === "tool_start" || type === "tool") {
    const name = String(event.name || "tool");
    const copy = toolEventCopy(name);
    upsertActivity(beginToolRun(name), {
      type: "tool",
      label: copy.activeLabel,
      detail: copy.activeDetail,
      status: "active",
      toolName: name,
      progress: 64
    });
    return;
  }

  if (type === "tool_result") {
    const name = String(event.name || "tool");
    const copy = toolEventCopy(name);
    const failed = event.success === false;
    upsertActivity(resolveToolRun(name), {
      type: "tool",
      label: failed ? copy.errorLabel : copy.doneLabel,
      detail: event.text ? String(event.text) : copy.doneDetail,
      status: failed ? "error" : "done",
      toolName: name,
      progress: 100
    });
    return;
  }

  if (type === "plan_mode_blocked") {
    const name = String(event.name || "tool");
    upsertActivity(`plan-blocked:${name}`, {
      type: "error",
      label: "Plan Mode 已拦截",
      detail: String(event.reason || `${name} 暂不允许执行`),
      status: "error",
      toolName: name,
      progress: 100
    });
    return;
  }

  if (type === "tool_approval_waiting") {
    const name = String(event.name || "tool");
    const copy = toolEventCopy(name);
    upsertActivity(`approval-waiting:${name}`, {
      type: "approval",
      label: copy.approvalLabel,
      detail: copy.approvalDetail,
      status: "active",
      toolName: name,
      risk: String(event.risk || "")
    });
    return;
  }

  if (type === "tool_approval_request") {
    const approvalId = String(event.id || "");
    const name = String(event.name || "tool");
    const copy = toolEventCopy(name);
    activityEvents.value = activityEvents.value.filter((item) => item.id !== `approval-waiting:${name}`);
    upsertActivity(`approval:${approvalId}`, {
      type: "approval",
      label: copy.approvalLabel,
      detail: copy.approvalDetail,
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
      label: approved ? "已允许" : "已拒绝",
      detail: approved
        ? `许可范围: ${event.decision === "session" ? "本会话" : "本次"}`
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
      label: event.cancelled ? "已跳过" : "已收到",
      detail: event.cancelled ? "Sierra 将按已有信息继续。" : String(event.label || "选择已提交。"),
      status: event.cancelled ? "error" : "done",
      inputId
    });
    return;
  }

  if (type === "context_compaction_start") {
    upsertActivity("context", {
      type: "context",
      label: "整理上下文",
      detail: "正在压缩较早的对话。",
      status: "active"
    });
    return;
  }

  if (type === "context_compaction_done") {
    upsertActivity("context", {
      type: "context",
      label: "上下文已整理",
      detail: "历史轮次已摘要化。",
      status: "done"
    });
    return;
  }

  if (type === "context_compaction_skipped") {
    upsertActivity("context", {
      type: "context",
      label: "上下文无需压缩",
      detail: "当前没有可安全压缩的完整历史轮次。",
      status: "done"
    });
    return;
  }

  if (type === "context_compaction_failed") {
    upsertActivity("context", {
      type: "context",
      label: "上下文整理失败",
      detail: "摘要没有完成，Sierra 已继续使用当前上下文。",
      status: "error"
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

function toolEventCopy(name: string) {
  if (name === "vision_analyze") {
    return {
      activeLabel: "分析图片",
      activeDetail: "正在把图片交给视觉模型解析。",
      doneLabel: "图片分析完成",
      doneDetail: "视觉结果已返回。",
      errorLabel: "图片分析失败",
      approvalLabel: "需要确认图片分析",
      approvalDetail: "Sierra 需要把这张图片发送给视觉模型。"
    };
  }
  return {
    activeLabel: "调用工具",
    activeDetail: "正在执行。",
    doneLabel: "工具完成",
    doneDetail: "执行完成。",
    errorLabel: "工具失败",
    approvalLabel: "需要确认",
    approvalDetail: "Sierra 需要你的许可才能继续执行这个工具。"
  };
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
  input: { value?: string; label?: string; free_text?: boolean; cancelled?: boolean }
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
      body: JSON.stringify({
        id,
        value: input.value || "",
        label: input.label || "",
        free_text: Boolean(input.free_text),
        cancelled: Boolean(input.cancelled)
      })
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

function setupShellMotion() {
  if (!appShellRef.value) {
    return;
  }
  shellMotion = gsap.matchMedia();
  shellMotion.add(
    {
      compact: "(max-width: 860px)",
      reduceMotion: "(prefers-reduced-motion: reduce)"
    },
    (context) => {
      const conditions = context.conditions as { compact: boolean; reduceMotion: boolean };
      if (conditions.reduceMotion) {
        return;
      }
      const distance = conditions.compact ? 10 : 18;
      const timeline = gsap.timeline({
        defaults: { ease: "power3.out" }
      });

      gsap.set([".sidebar-shell", ".main-shell"], { willChange: "transform, opacity" });
      timeline
        .from(".sidebar-shell", {
          autoAlpha: 0,
          x: -distance,
          duration: 0.52
        })
        .from(
          ".main-shell",
          {
            autoAlpha: 0,
            y: distance * 0.8,
            scale: 0.992,
            duration: 0.58
          },
          "<0.06"
        )
        .set([".sidebar-shell", ".main-shell"], { clearProps: "willChange" });

      return () => timeline.kill();
    },
    appShellRef.value
  );
}

watch(autoRefresh, startTimer);

onMounted(() => {
  setupShellMotion();
  loadDashboard();
  startTimer();
});

onUnmounted(() => {
  window.clearInterval(timer);
  shellMotion?.revert();
});
</script>
