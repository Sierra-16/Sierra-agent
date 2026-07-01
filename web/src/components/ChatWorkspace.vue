<template>
  <section class="chat-workspace">
    <header class="chat-statusbar">
      <button class="connection-chip" type="button" :disabled="loading" @click="$emit('refresh')">
        <span class="status-dot" :class="{ stale: error }"></span>
        <span>{{ error ? "连接异常" : "Sierra 在线" }}</span>
      </button>

      <div class="runtime-strip">
        <span class="model-chip" :title="activeModelLabel">{{ activeModelLabel }}</span>
        <span
          class="usage-orb"
          :style="{ '--pct': `${usagePercent}%` }"
          :title="`当前会话窗口占用 ${usagePercent.toFixed(0)}%`"
        ></span>
      </div>
    </header>

    <div ref="scrollEl" class="thread-scroll">
      <div class="thread-inner">
        <div class="empty-hero" v-if="messages.length === 0">
          <h3>今天要让 Sierra 做什么？</h3>
        </div>

        <div
          v-for="message in messages"
          :key="message.id"
          class="message-row"
          :class="message.role"
        >
          <template v-if="message.role === 'system'">
            <div class="system-message">
              <span>系统</span>
              <p>{{ message.text }}</p>
            </div>
          </template>

          <template v-else>
            <img
              v-if="message.role === 'assistant'"
              class="message-avatar"
              src="/brand/sierra-avatar.png?v=transparent-1"
              alt="Sierra"
            />
            <div v-else class="message-avatar user-avatar">
              <UserRound :size="18" />
            </div>
            <div class="message-block">
              <div class="message-label">
                <span>{{ message.role === "assistant" ? "Sierra" : "You" }}</span>
              </div>
              <div class="message-bubble">
                <p>{{ message.text }}</p>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <section class="composer-dock" :class="{ active: showActivity || completionOpen }">
      <div
        v-if="showActivity && activeActivity"
        class="process-panel"
        :class="processClasses"
      >
        <SierraOrnaments variant="process" :active="activeActivity.status === 'active'" />

        <div class="process-portrait">
          <span
            class="thinking-sprite hero"
            :class="activeActivity.status === 'done' ? 'done' : 'active'"
          ></span>
          <span class="process-glow"></span>
        </div>

        <div class="process-main">
          <div class="process-kicker">
            <component :is="activeActivityIcon" :size="14" />
            <span>状态</span>
          </div>
          <div class="process-title-row">
            <h4>{{ processTitle }}</h4>
            <code v-if="activeActivity.toolName">{{ activeActivity.toolName }}</code>
          </div>
          <p v-if="processDetail">{{ processDetail }}</p>

          <div class="process-phases" aria-label="Sierra 当前处理阶段">
            <span
              v-for="phase in activityPhases"
              :key="phase.key"
              class="process-phase"
              :class="{ active: phase.active, done: phase.done }"
            >
              <component :is="phase.icon" :size="12" />
              {{ phase.label }}
            </span>
          </div>
        </div>

        <div class="process-side">
          <span class="process-gem"></span>
          <strong>{{ processStatusText }}</strong>
          <small>{{ processSideText }}</small>
        </div>
      </div>

      <TransitionGroup name="activity-list" tag="div" class="status-stack" v-if="stackActivityEvents.length">
        <article
          v-for="event in stackActivityEvents"
          :key="event.id"
          class="status-card"
          :class="[event.type, event.status, riskClass(event)]"
        >
          <div class="status-leading">
            <span
              v-if="event.type === 'thinking'"
              class="thinking-sprite compact"
              :class="event.status === 'active' ? 'active' : 'done'"
            ></span>
            <span v-else class="status-icon">
              <component :is="iconFor(event)" :size="17" />
            </span>
          </div>

          <div class="status-main">
            <div class="status-title-line">
              <strong>{{ event.label }}</strong>
              <code v-if="event.toolName">{{ event.toolName }}</code>
              <span v-if="event.risk" class="risk-pill" :class="riskClass(event)">
                {{ event.risk }}
              </span>
            </div>
            <p v-if="event.detail">{{ event.detail }}</p>
            <p v-if="event.reason" class="approval-reason">{{ event.reason }}</p>

            <div v-if="event.type === 'tool' && event.status === 'active'" class="tool-progress">
              <span :style="{ width: `${event.progress ?? 64}%` }"></span>
            </div>

            <div
              v-if="event.type === 'user-input' && event.status === 'active' && event.inputId"
              class="input-request"
            >
              <div v-if="event.options?.length" class="input-options">
                <button
                  v-for="option in event.options"
                  :key="option.value || option.label"
                  type="button"
                  @click="submitInputOption(event, option)"
                >
                  <strong>{{ option.label }}</strong>
                  <small v-if="option.description">{{ option.description }}</small>
                </button>
              </div>
              <form
                v-if="event.allowFreeText"
                class="input-inline"
                @submit.prevent="submitInputText(event)"
              >
                <input
                  v-model="freeText[event.id]"
                  type="text"
                  placeholder="补充一句..."
                />
                <button type="submit">发送</button>
              </form>
            </div>

            <details v-if="event.arguments" class="argument-preview">
              <summary>参数</summary>
              <pre>{{ event.arguments }}</pre>
            </details>
          </div>

          <div class="status-actions">
            <template v-if="event.type === 'approval' && event.status === 'active' && event.approvalId">
              <button class="approval-button once" type="button" @click="approve(event, 'once')">
                本次允许
              </button>
              <button class="approval-button session" type="button" @click="approve(event, 'session')">
                本会话允许
              </button>
              <button class="approval-button deny" type="button" @click="approve(event, 'deny')">
                拒绝
              </button>
            </template>
            <template v-else-if="event.type === 'user-input' && event.status === 'active' && event.inputId">
              <button class="approval-button deny" type="button" @click="cancelInput(event)">
                跳过
              </button>
            </template>
            <span v-else-if="event.status === 'active'" class="status-spinner" aria-hidden="true"></span>
            <Check v-else-if="event.status === 'done'" :size="17" />
            <AlertTriangle v-else-if="event.status === 'error'" :size="17" />
          </div>
        </article>
      </TransitionGroup>

      <div class="reference-chips" v-if="referenceChips.length">
        <span v-for="chip in referenceChips" :key="chip" class="reference-chip">
          <AtSign :size="12" />
          {{ chip }}
        </span>
      </div>

      <div class="composer-tools">
        <button type="button" class="composer-tool-button" title="引用文件" @click="insertReferencePrefix('@file:')">
          <FileText :size="15" />
          <span>文件</span>
        </button>
        <button type="button" class="composer-tool-button" title="引用文件夹" @click="insertReferencePrefix('@folder:')">
          <Folder :size="15" />
          <span>文件夹</span>
        </button>
        <button type="button" class="composer-tool-button" title="引用 Git diff" @click="insertToken('@diff ')">
          <GitBranch :size="15" />
          <span>Diff</span>
        </button>
        <button type="button" class="composer-tool-button" title="引用网页" @click="insertReferencePrefix('@url:')">
          <Link2 :size="15" />
          <span>URL</span>
        </button>
        <button type="button" class="composer-tool-button" title="Upload file" :disabled="uploading" @click="triggerUpload">
          <Upload :size="15" />
          <span>{{ uploading ? "上传中" : "上传" }}</span>
        </button>
        <input
          ref="fileInputRef"
          class="upload-input"
          type="file"
          accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.rtf,.txt,.md,.json,.csv"
          @change="handleUploadFile"
        />
        <span v-if="uploadState" class="upload-state">{{ uploadState }}</span>
        <span class="composer-hint">
          输入 <kbd>/</kbd> 选命令，输入 <kbd>@</kbd> 附加上下文
        </span>
      </div>

      <div v-if="completionOpen" class="completion-popover">
        <div class="completion-head">
          <span>{{ completionMode === "slash" ? "命令" : "上下文引用" }}</span>
          <small>{{ referenceLoading ? "搜索中..." : "↑↓ 选择 · Enter 插入 · Esc 关闭" }}</small>
        </div>
        <div class="completion-list" v-if="completionItems.length">
          <button
            v-for="(item, index) in completionItems"
            :key="`${item.kind}:${item.value}:${index}`"
            type="button"
            class="completion-item"
            :class="{ active: index === selectedCompletionIndex }"
            @mousedown.prevent="applyCompletion(item)"
            @mouseenter="selectedCompletionIndex = index"
          >
            <span class="completion-glyph">
              <component :is="completionIcon(item)" :size="16" />
            </span>
            <span class="completion-copy">
              <strong>{{ item.label }}</strong>
              <small>{{ item.detail }}</small>
            </span>
            <kbd v-if="index === selectedCompletionIndex">Enter</kbd>
          </button>
        </div>
        <div class="completion-empty" v-else>
          没找到匹配项。你也可以继续手动输入。
        </div>
      </div>

      <form class="composer-bar" @submit.prevent="submitDraft">
        <textarea
          ref="textareaRef"
          v-model="draft"
          placeholder="输入消息，或 /help 查看命令..."
          rows="1"
          @blur="deferCloseCompletion"
          @click="updateCompletion"
          @input="onDraftInput"
          @keydown="handleKeydown"
          @keyup="updateCompletion"
        ></textarea>
        <button class="send-button" type="submit" :disabled="sending || !draft.trim()">
          <Send :size="17" />
          发送
        </button>
      </form>
    </section>
  </section>
</template>

<script setup lang="ts">
import {
  AlertTriangle,
  AtSign,
  Check,
  Database,
  FileText,
  Folder,
  GitBranch,
  History,
  Link2,
  MessageCircleQuestion,
  ScrollText,
  Send,
  ShieldAlert,
  Sparkles,
  Upload,
  UserRound,
  WandSparkles,
  Wrench
} from "lucide-vue-next";
import { computed, nextTick, onMounted, ref, watch } from "vue";
import type { ChatActivityEvent, ChatMessage } from "../types";
import SierraOrnaments from "./SierraOrnaments.vue";

type CompletionMode = "slash" | "reference";

type CompletionItem = {
  kind: string;
  label: string;
  detail: string;
  value: string;
};

const props = defineProps<{
  activeModelLabel: string;
  activityEvents: ChatActivityEvent[];
  error: string;
  loading: boolean;
  messages: ChatMessage[];
  sending: boolean;
  usagePercent: number;
  workspace?: string;
}>();

const emit = defineEmits<{
  (event: "refresh"): void;
  (event: "send", value: string): void;
  (event: "approve-tool", id: string, decision: "once" | "session" | "deny"): void;
  (
    event: "respond-user-input",
    id: string,
    payload: { value?: string; label?: string; free_text?: string; cancelled?: boolean }
  ): void;
}>();

const DRAFT_KEY = "sierra:web:draft";
const HISTORY_KEY = "sierra:web:input-history";

const slashCommands: CompletionItem[] = [
  { kind: "command", label: "/help", detail: "查看 Web 可用命令", value: "/help " },
  { kind: "command", label: "/new", detail: "开启一个新对话", value: "/new" },
  { kind: "command", label: "/sessions", detail: "查看历史会话", value: "/sessions" },
  { kind: "command", label: "/session-search", detail: "搜索历史会话，需要关键词", value: "/session-search " },
  { kind: "command", label: "/session-load", detail: "按 ID 切换会话", value: "/session-load " },
  { kind: "command", label: "/undo", detail: "撤回最近一轮对话", value: "/undo " },
  { kind: "command", label: "/retry", detail: "重试上一轮请求", value: "/retry" },
  { kind: "command", label: "/model", detail: "查看或切换模型", value: "/model " },
  { kind: "command", label: "/compress", detail: "手动压缩当前会话历史", value: "/compress" },
  { kind: "command", label: "/memory", detail: "查看记忆状态", value: "/memory" },
  { kind: "command", label: "/memory-search", detail: "搜索长期记忆，需要问题", value: "/memory-search " },
  { kind: "command", label: "/memory-forget", detail: "删除指定向量记忆", value: "/memory-forget " },
  { kind: "command", label: "/memory-clear", detail: "清空当前工作区向量记忆", value: "/memory-clear" },
  { kind: "command", label: "/task", detail: "查看任务计划与进度", value: "/task" },
  { kind: "command", label: "/task-cancel", detail: "放弃当前任务计划", value: "/task-cancel" },
  { kind: "command", label: "/jobs", detail: "查看后台任务队列", value: "/jobs" },
  { kind: "command", label: "/cron", detail: "查看定时提醒", value: "/cron" },
  { kind: "command", label: "/cron-add", detail: "创建定时提醒：分钟 + 内容", value: "/cron-add " },
  { kind: "command", label: "/cron-remove", detail: "删除定时提醒", value: "/cron-remove " },
  { kind: "command", label: "/mcp", detail: "查看 MCP 连接状态", value: "/mcp" },
  { kind: "command", label: "/skills", detail: "查看可用技能", value: "/skills" },
  { kind: "command", label: "/skills-reload", detail: "重新加载技能", value: "/skills-reload" },
  { kind: "command", label: "/skills-stats", detail: "查看技能使用统计", value: "/skills-stats" },
  { kind: "command", label: "/debug-context", detail: "查看上下文结构", value: "/debug-context" },
  { kind: "command", label: "/audit", detail: "查看工具审计日志", value: "/audit" }
];

const draft = ref("");
const freeText = ref<Record<string, string>>({});
const scrollEl = ref<HTMLElement | null>(null);
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const completionOpen = ref(false);
const completionMode = ref<CompletionMode>("slash");
const completionItems = ref<CompletionItem[]>([]);
const selectedCompletionIndex = ref(0);
const completionTokenStart = ref(0);
const referenceLoading = ref(false);
const uploading = ref(false);
const uploadState = ref("");
const inputHistory = ref<string[]>([]);
const historyIndex = ref(-1);
let referenceRequestId = 0;

const visibleActivityEvents = computed(() => props.activityEvents.slice(-5));
const showActivity = computed(() => props.activityEvents.length > 0);
const stackActivityEvents = computed(() =>
  visibleActivityEvents.value.filter((event) => event.type !== "thinking" || event.status !== "active")
);
const activeActivity = computed(() => {
  return (
    visibleActivityEvents.value.find((event) => event.status === "active") ||
    visibleActivityEvents.value[visibleActivityEvents.value.length - 1]
  );
});
const activeActivityIcon = computed(() => {
  return activeActivity.value ? iconFor(activeActivity.value) : Sparkles;
});
const processClasses = computed(() => {
  const event = activeActivity.value;
  return event ? [event.type, event.status, riskClass(event)] : [];
});
const processTitle = computed(() => {
  const event = activeActivity.value;
  if (!event) {
    return "处理中";
  }
  if (event.status === "error") {
    return "处理异常";
  }
  if (event.type === "approval") {
    return "等待确认";
  }
  if (event.type === "user-input") {
    return "等待输入";
  }
  if (event.type === "tool") {
    return event.status === "done" ? "工具完成" : "调用工具";
  }
  if (event.type === "memory") {
    return "整理记忆";
  }
  if (event.type === "history") {
    return "检索会话";
  }
  if (event.type === "context" || event.type === "reference") {
    return "整理上下文";
  }
  if (event.type === "thinking") {
    return event.status === "done" ? "完成" : "思考中";
  }
  return event.label || "处理中";
});
const processDetail = computed(() => {
  const event = activeActivity.value;
  if (!event) {
    return "";
  }
  if (event.type === "thinking") {
    return "";
  }
  if (event.reason) {
    return event.reason;
  }
  if (event.detail) {
    return event.detail;
  }
  if (event.toolName) {
    return "";
  }
  if (event.type === "approval") {
    return "请在下方选择允许或拒绝。";
  }
  if (event.type === "user-input") {
    return "请补充信息后继续。";
  }
  return "";
});
const processStatusText = computed(() => {
  const status = activeActivity.value?.status;
  if (status === "done") {
    return "已完成";
  }
  if (status === "error") {
    return "需处理";
  }
  return "进行中";
});
const processSideText = computed(() => {
  const event = activeActivity.value;
  if (!event) {
    return "整理思路";
  }
  if (event.type === "approval") {
    return "等待确认";
  }
  if (event.type === "user-input") {
    return "等待回复";
  }
  if (event.type === "tool") {
    return "工具调用";
  }
  if (event.type === "memory") {
    return "记忆维护";
  }
  if (event.type === "context" || event.type === "reference") {
    return "上下文";
  }
  return "思考中";
});
const activityPhases = computed(() => {
  const events = visibleActivityEvents.value;
  const phaseState = (types: string[]) => {
    const related = events.filter((event) => types.includes(event.type));
    return {
      active: related.some((event) => event.status === "active"),
      done: related.length > 0 && related.every((event) => event.status !== "active")
    };
  };
  const thinking = phaseState(["thinking"]);
  const context = phaseState(["context", "reference", "history"]);
  const tool = phaseState(["tool"]);
  const approval = phaseState(["approval", "user-input"]);
  const memory = phaseState(["memory"]);
  return [
    { key: "thinking", label: "思考", icon: WandSparkles, ...thinking },
    { key: "context", label: "上下文", icon: ScrollText, ...context },
    { key: "tool", label: "工具", icon: Wrench, ...tool },
    { key: "approval", label: "确认", icon: ShieldAlert, ...approval },
    { key: "memory", label: "记忆", icon: Database, ...memory }
  ];
});

const referenceChips = computed(() => {
  const tokens = draft.value.match(/@(diff|staged|file:`[^`]+`|folder:`[^`]+`|url:\S+)/g) || [];
  return tokens.slice(0, 6).map((token) => {
    if (token.startsWith("@file:")) {
      return token.replace("@file:", "文件 ");
    }
    if (token.startsWith("@folder:")) {
      return token.replace("@folder:", "文件夹 ");
    }
    if (token.startsWith("@url:")) {
      return "网页";
    }
    return token;
  });
});

function submitDraft() {
  const message = draft.value.trim();
  if (!message || props.sending) {
    return;
  }
  rememberInput(message);
  draft.value = "";
  persistDraft();
  completionOpen.value = false;
  historyIndex.value = -1;
  emit("send", message);
  resizeTextarea();
}

function approve(event: ChatActivityEvent, decision: "once" | "session" | "deny") {
  if (!event.approvalId) {
    return;
  }
  emit("approve-tool", event.approvalId, decision);
}

function submitInputOption(
  event: ChatActivityEvent,
  option: { label: string; value?: string; description?: string }
) {
  if (!event.inputId) {
    return;
  }
  emit("respond-user-input", event.inputId, {
    value: option.value || option.label,
    label: option.label,
    cancelled: false
  });
}

function submitInputText(event: ChatActivityEvent) {
  if (!event.inputId) {
    return;
  }
  const value = (freeText.value[event.id] || "").trim();
  if (!value) {
    return;
  }
  emit("respond-user-input", event.inputId, {
    value,
    label: value,
    free_text: value,
    cancelled: false
  });
  freeText.value[event.id] = "";
}

function cancelInput(event: ChatActivityEvent) {
  if (!event.inputId) {
    return;
  }
  emit("respond-user-input", event.inputId, { cancelled: true });
}

function insertReferencePrefix(prefix: string) {
  focusComposer();
  insertToken(prefix);
  updateCompletion();
}

function insertToken(value: string) {
  const textarea = textareaRef.value;
  const cursor = textarea?.selectionStart ?? draft.value.length;
  const before = draft.value.slice(0, cursor);
  const after = draft.value.slice(cursor);
  const spacer = before && !/\s$/.test(before) ? " " : "";
  draft.value = `${before}${spacer}${value}${after}`;
  const nextCursor = before.length + spacer.length + value.length;
  nextTick(() => {
    textareaRef.value?.setSelectionRange(nextCursor, nextCursor);
    resizeTextarea();
    persistDraft();
  });
}

function triggerUpload() {
  fileInputRef.value?.click();
}

async function handleUploadFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || uploading.value) {
    return;
  }
  const maxBytes = 25 * 1024 * 1024;
  if (file.size > maxBytes) {
    uploadState.value = "文件超过 25MB";
    window.setTimeout(() => {
      uploadState.value = "";
    }, 2400);
    return;
  }

  uploading.value = true;
  uploadState.value = `上传 ${file.name}...`;
  try {
    const contentBase64 = await fileToBase64(file);
    const response = await fetch("/api/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content_base64: contentBase64
      })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `Upload API ${response.status}`);
    }
    insertToken(String(data.reference || `@file:\`${data.relative_path}\` `));
    uploadState.value = "已插入文件引用";
  } catch (err) {
    uploadState.value = `上传失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    uploading.value = false;
    window.setTimeout(() => {
      uploadState.value = "";
    }, 2400);
  }
}

async function fileToBase64(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const chunkSize = 0x8000;
  let binary = "";
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return window.btoa(binary);
}

function applyCompletion(item: CompletionItem) {
  const textarea = textareaRef.value;
  const cursor = textarea?.selectionStart ?? draft.value.length;
  const before = draft.value.slice(0, completionTokenStart.value);
  const after = draft.value.slice(cursor);
  draft.value = `${before}${item.value}${after}`;
  const nextCursor = before.length + item.value.length;
  completionOpen.value = false;
  selectedCompletionIndex.value = 0;
  nextTick(() => {
    textareaRef.value?.focus();
    textareaRef.value?.setSelectionRange(nextCursor, nextCursor);
    resizeTextarea();
    persistDraft();
  });
}

function handleKeydown(event: KeyboardEvent) {
  if (completionOpen.value) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      selectedCompletionIndex.value = (selectedCompletionIndex.value + 1) % Math.max(completionItems.value.length, 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      selectedCompletionIndex.value =
        (selectedCompletionIndex.value - 1 + Math.max(completionItems.value.length, 1)) %
        Math.max(completionItems.value.length, 1);
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      if (completionItems.value[selectedCompletionIndex.value]) {
        event.preventDefault();
        applyCompletion(completionItems.value[selectedCompletionIndex.value]);
        return;
      }
    }
    if (event.key === "Escape") {
      event.preventDefault();
      completionOpen.value = false;
      return;
    }
  }

  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitDraft();
    return;
  }

  if ((event.key === "ArrowUp" || event.key === "ArrowDown") && !draft.value.trim() && inputHistory.value.length) {
    event.preventDefault();
    browseHistory(event.key === "ArrowUp" ? -1 : 1);
  }
}

function browseHistory(direction: -1 | 1) {
  if (!inputHistory.value.length) {
    return;
  }
  if (historyIndex.value < 0) {
    historyIndex.value = inputHistory.value.length;
  }
  historyIndex.value = Math.max(0, Math.min(inputHistory.value.length - 1, historyIndex.value + direction));
  draft.value = inputHistory.value[historyIndex.value] || "";
  nextTick(() => {
    const end = draft.value.length;
    textareaRef.value?.setSelectionRange(end, end);
    resizeTextarea();
  });
}

function onDraftInput() {
  historyIndex.value = -1;
  resizeTextarea();
  persistDraft();
  updateCompletion();
}

function updateCompletion() {
  const textarea = textareaRef.value;
  const cursor = textarea?.selectionStart ?? draft.value.length;
  const before = draft.value.slice(0, cursor);
  const slash = before.match(/(^|\s)(\/[\w-]*)$/);
  if (slash) {
    referenceRequestId += 1;
    referenceLoading.value = false;
    completionMode.value = "slash";
    completionTokenStart.value = cursor - slash[2].length;
    const query = slash[2].toLowerCase();
    completionItems.value = slashCommands
      .filter((item) => item.label.toLowerCase().startsWith(query))
      .slice(0, 12);
    selectedCompletionIndex.value = 0;
    completionOpen.value = completionItems.value.length > 0;
    return;
  }

  const reference = before.match(/(^|\s)(@(?:file:|folder:|url:)?[^\s`]*)$/);
  if (reference) {
    completionMode.value = "reference";
    completionTokenStart.value = cursor - reference[2].length;
    completionOpen.value = true;
    selectedCompletionIndex.value = 0;
    fetchReferenceSuggestions(reference[2].slice(1));
    return;
  }

  referenceRequestId += 1;
  referenceLoading.value = false;
  completionOpen.value = false;
}

async function fetchReferenceSuggestions(query: string) {
  const requestId = ++referenceRequestId;
  referenceLoading.value = true;
  try {
    const response = await fetch(`/api/context/suggestions?q=${encodeURIComponent(query)}&limit=18`);
    const data = await response.json();
    if (requestId !== referenceRequestId) {
      return;
    }
    completionItems.value = Array.isArray(data.items)
      ? data.items.map((item: any) => ({
        kind: String(item.kind || "reference"),
        label: String(item.label || item.value || "@"),
        detail: String(item.detail || ""),
        value: String(item.value || "")
      })).filter((item: CompletionItem) => item.value)
      : [];
  } catch {
    if (requestId === referenceRequestId) {
      completionItems.value = [];
    }
  } finally {
    if (requestId === referenceRequestId) {
      referenceLoading.value = false;
      completionOpen.value = true;
    }
  }
}

function completionIcon(item: CompletionItem) {
  if (item.kind === "file") {
    return FileText;
  }
  if (item.kind === "folder") {
    return Folder;
  }
  if (item.kind === "diff" || item.kind === "staged") {
    return GitBranch;
  }
  if (item.kind === "url") {
    return Link2;
  }
  return AtSign;
}

function deferCloseCompletion() {
  window.setTimeout(() => {
    completionOpen.value = false;
  }, 120);
}

function focusComposer() {
  nextTick(() => textareaRef.value?.focus());
}

function resizeTextarea() {
  const textarea = textareaRef.value;
  if (!textarea) {
    return;
  }
  textarea.style.height = "42px";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 118)}px`;
}

function persistDraft() {
  window.localStorage.setItem(DRAFT_KEY, draft.value);
}

function rememberInput(value: string) {
  const existing = inputHistory.value.filter((item) => item !== value);
  inputHistory.value = [...existing, value].slice(-80);
  window.localStorage.setItem(HISTORY_KEY, JSON.stringify(inputHistory.value));
}

function loadComposerState() {
  draft.value = window.localStorage.getItem(DRAFT_KEY) || "";
  try {
    const history = JSON.parse(window.localStorage.getItem(HISTORY_KEY) || "[]");
    inputHistory.value = Array.isArray(history) ? history.filter((item) => typeof item === "string") : [];
  } catch {
    inputHistory.value = [];
  }
  nextTick(resizeTextarea);
}

function iconFor(event: ChatActivityEvent) {
  if (event.type === "approval") {
    return ShieldAlert;
  }
  if (event.type === "user-input") {
    return MessageCircleQuestion;
  }
  if (event.status === "error") {
    return AlertTriangle;
  }
  if (event.type === "tool") {
    return Wrench;
  }
  if (event.type === "memory") {
    return Database;
  }
  if (event.type === "history") {
    return History;
  }
  if (event.type === "context") {
    return ScrollText;
  }
  if (event.type === "reference") {
    return FileText;
  }
  if (event.type === "thinking") {
    return WandSparkles;
  }
  return Sparkles;
}

function riskClass(event: ChatActivityEvent) {
  const risk = String(event.risk || "").toLowerCase();
  if (risk.includes("high")) {
    return "risk-high";
  }
  if (risk.includes("medium")) {
    return "risk-medium";
  }
  if (risk.includes("low")) {
    return "risk-low";
  }
  return "";
}

async function scrollToBottom() {
  await nextTick();
  if (scrollEl.value) {
    scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
  }
}

onMounted(loadComposerState);

watch(
  () => [
    props.messages.length,
    props.sending,
    props.activityEvents.length,
    props.messages[props.messages.length - 1]?.text,
    props.activityEvents.map((event) => `${event.id}:${event.status}:${event.detail}`).join("|")
  ],
  () => {
    scrollToBottom();
  },
  { flush: "post" }
);
</script>
