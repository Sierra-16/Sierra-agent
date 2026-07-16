<template>
  <section ref="workspaceRef" class="chat-workspace">
    <header class="chat-statusbar">
      <div class="agent-presence">
        <button
          class="mobile-nav-toggle"
          type="button"
          aria-label="打开会话列表"
          @click="$emit('open-navigation')"
        >
          <Menu :size="19" aria-hidden="true" />
        </button>
        <img
          src="/brand/sierra-avatar.png?v=transparent-1"
          alt=""
          width="34"
          height="34"
        />
        <span>
          <strong translate="no">Sierra</strong>
          <small>
            <i class="status-dot" :class="{ stale: error }" aria-hidden="true"></i>
            {{ error ? "连接异常" : "在线" }}
          </small>
        </span>
      </div>

      <div class="runtime-strip">
        <span class="model-chip" :title="activeModelLabel" translate="no">{{ activeModelLabel }}</span>
        <span
          class="usage-orb"
          :style="{ '--pct': `${usagePercent}%` }"
          role="img"
          :aria-label="`当前会话窗口占用 ${usagePercent.toFixed(0)}%`"
          :title="`当前会话窗口占用 ${usagePercent.toFixed(0)}%`"
        ></span>
        <button
          class="refresh-status"
          type="button"
          :disabled="loading"
          aria-label="刷新 Sierra 状态"
          @click="$emit('refresh')"
        >
          <RefreshCw :size="15" aria-hidden="true" />
        </button>
      </div>
    </header>

    <div ref="scrollEl" class="thread-scroll">
      <div class="thread-inner">
        <div v-if="messages.length === 0" class="empty-hero">
          <h2>今天要让 Sierra 做什么？</h2>
        </div>

        <div
          v-for="message in renderedMessages"
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
              width="38"
              height="38"
            />
            <div v-else class="message-avatar user-avatar">
              <UserRound :size="18" />
            </div>
            <div class="message-block">
              <div class="message-label">
                <span>{{ message.role === "assistant" ? "Sierra" : "You" }}</span>
              </div>
              <div class="message-bubble" :class="{ 'has-attachments': message.attachments.length }">
                <p v-if="message.displayText">{{ message.displayText }}</p>
                <div v-if="message.attachments.length" class="message-attachments">
                  <template v-for="attachment in message.attachments" :key="attachment.id">
                    <button
                      v-if="attachment.kind === 'image'"
                      type="button"
                      class="message-attachment"
                      :class="attachment.kind"
                      :title="attachment.path"
                      @click="openImagePreview(attachment)"
                    >
                      <span class="attachment-image-shell">
                        <img
                          :src="attachment.url"
                          alt=""
                          width="640"
                          height="360"
                          loading="lazy"
                          @load="animateAttachmentLoad"
                        />
                        <span class="attachment-glint"></span>
                      </span>
                    </button>
                    <a
                      v-else
                      class="message-attachment"
                      :class="attachment.kind"
                      :href="attachment.url"
                      target="_blank"
                      rel="noreferrer"
                      :title="attachment.path"
                    >
                      <span class="attachment-file-icon">
                        <FileText :size="18" />
                      </span>
                      <span class="attachment-meta">
                        <strong>
                          <FileText :size="13" />
                          {{ attachment.name }}
                        </strong>
                        <small>{{ attachment.extension || "文件" }}</small>
                      </span>
                    </a>
                  </template>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <section class="composer-dock" :class="{ active: showActivity || completionOpen }">
      <div
        v-if="showProcessPanel && activeActivity"
        class="process-panel"
        :class="processClasses"
        aria-live="polite"
      >
        <header class="process-summary">
          <div class="process-portrait" aria-hidden="true">
            <span
              class="thinking-sprite hero"
              :class="activeActivity.status === 'done' ? 'done' : 'active'"
            ></span>
          </div>

          <div class="process-main">
            <div class="process-kicker">
              <component :is="activeActivityIcon" :size="14" aria-hidden="true" />
              <span>{{ processKicker }}</span>
            </div>
            <div class="process-title-row">
              <h2>{{ processTitle }}</h2>
              <code v-if="activeActivity.toolName" translate="no">{{ activeActivity.toolName }}</code>
            </div>
            <p v-if="processDetail">{{ processDetail }}</p>
          </div>

          <span class="process-state" :class="activeActivity.status">
            <span
              v-if="activeActivity.status === 'active' || activeActivity.status === 'muted'"
              class="status-spinner"
              aria-hidden="true"
            ></span>
            <Check v-else-if="activeActivity.status === 'done'" :size="15" aria-hidden="true" />
            <AlertTriangle v-else-if="activeActivity.status === 'error'" :size="15" aria-hidden="true" />
            {{ processStatusText }}
          </span>
        </header>

        <div class="process-phases" aria-label="Sierra 当前处理阶段">
          <span
            v-for="phase in activityPhases"
            :key="phase.key"
            class="process-phase"
            :class="{ active: phase.active, done: phase.done }"
          >
            <component :is="phase.icon" :size="12" aria-hidden="true" />
            {{ phase.label }}
          </span>
        </div>

        <TransitionGroup
          v-if="processFeedEvents.length"
          name="process-feed"
          tag="div"
          class="process-feed"
        >
          <article
            v-for="event in processFeedEvents"
            :key="event.id"
            class="process-feed-item"
            :class="[event.type, event.status, riskClass(event)]"
          >
            <span class="process-feed-icon">
              <component :is="iconFor(event)" :size="15" aria-hidden="true" />
            </span>

            <div class="process-feed-main">
              <div class="process-feed-title">
                <strong>{{ event.label }}</strong>
                <code v-if="event.toolName">{{ event.toolName }}</code>
                <span v-if="event.risk" class="risk-pill" :class="riskClass(event)">
                  {{ event.risk }}
                </span>
              </div>
              <p v-if="event.reason || event.detail">{{ event.reason || event.detail }}</p>

              <div v-if="event.type === 'tool' && event.status === 'active'" class="tool-progress process-tool-progress">
                <span :style="{ width: `${event.progress ?? 64}%` }"></span>
              </div>

              <details v-if="event.arguments" class="argument-preview process-argument-preview">
                <summary>参数</summary>
                <pre>{{ event.arguments }}</pre>
              </details>
            </div>

            <div class="process-feed-state">
              <span v-if="event.status === 'active' || event.status === 'muted'" class="status-spinner" aria-hidden="true"></span>
              <Check v-else-if="event.status === 'done'" :size="16" />
              <AlertTriangle v-else-if="event.status === 'error'" :size="16" />
            </div>
          </article>
        </TransitionGroup>

        <div
          v-if="showProcessActions"
          class="process-actions"
        >
          <template v-if="activeActivity.type === 'approval' && activeActivity.status === 'active' && activeActivity.approvalId">
            <button class="approval-button once" type="button" @click="approve(activeActivity, 'once')">
              本次允许
            </button>
            <button class="approval-button session" type="button" @click="approve(activeActivity, 'session')">
              本会话允许
            </button>
            <button class="approval-button deny" type="button" @click="approve(activeActivity, 'deny')">
              拒绝
            </button>
          </template>
          <div
            v-else-if="activeActivity.type === 'user-input' && activeActivity.status === 'active' && activeActivity.inputId"
            class="input-request process-input-request"
          >
            <div v-if="activeActivity.options?.length" class="input-options">
              <button
                v-for="option in activeActivity.options"
                :key="option.value || option.label"
                type="button"
                @click="submitInputOption(activeActivity, option)"
              >
                <strong>{{ option.label }}</strong>
                <small v-if="option.description">{{ option.description }}</small>
              </button>
            </div>
            <form v-if="activeActivity.allowFreeText" class="input-inline" @submit.prevent="submitInputText(activeActivity)">
              <input
                v-model="freeText[activeActivity.id]"
                name="process-reply"
                type="text"
                autocomplete="off"
                aria-label="补充信息"
                placeholder="补充一句…"
              />
              <button type="submit">发送</button>
            </form>
            <button class="approval-button deny" type="button" @click="cancelInput(activeActivity)">
              跳过
            </button>
          </div>
        </div>
      </div>

      <div v-if="draftAttachments.length" class="draft-attachments">
        <template v-for="attachment in draftAttachments" :key="attachment.id">
          <button
            v-if="attachment.kind === 'image'"
            type="button"
            class="draft-attachment"
            :class="attachment.kind"
            :title="attachment.path"
            @click="openImagePreview(attachment)"
          >
            <span class="draft-attachment-thumb">
              <img
                :src="attachment.url"
                alt=""
                width="96"
                height="64"
                loading="lazy"
                @load="animateAttachmentLoad"
              />
            </span>
          </button>
          <a
            v-else
            class="draft-attachment"
            :class="attachment.kind"
            :href="attachment.url"
            target="_blank"
            rel="noreferrer"
            :title="attachment.path"
          >
            <span class="draft-attachment-icon">
              <FileText :size="16" />
            </span>
            <span>
              <strong>{{ attachment.name }}</strong>
              <small>{{ attachment.extension || "待发送文件" }}</small>
            </span>
          </a>
        </template>
      </div>

      <div v-if="referenceChips.length" class="reference-chips">
        <span v-for="chip in referenceChips" :key="chip" class="reference-chip">
          <AtSign :size="12" />
          {{ chip }}
        </span>
      </div>

      <div class="composer-tools">
        <div class="composer-mode-group">
          <button
            type="button"
            class="composer-tool-button plan-mode-toggle composer-plan-toggle"
            :class="{ active: planMode }"
            :disabled="sending || loading || planModeLoading"
            :aria-pressed="planMode"
            :title="planMode ? 'Plan Mode 已开启：Sierra 只规划和读取' : '开启 Plan Mode：先规划，不执行修改'"
            @click="$emit('toggle-plan-mode')"
          >
            <ScrollText :size="15" aria-hidden="true" />
            <span>{{ planModeLoading ? "切换中…" : planMode ? "计划模式" : "Plan Mode" }}</span>
          </button>
        </div>
        <div class="composer-reference-tools" aria-label="添加上下文">
          <button
            type="button"
            class="composer-tool-button"
            aria-label="引用文件"
            title="引用文件"
            @click="insertReferencePrefix('@file:')"
          >
            <FileText :size="15" aria-hidden="true" />
            <span>文件</span>
          </button>
          <button
            type="button"
            class="composer-tool-button"
            aria-label="引用文件夹"
            title="引用文件夹"
            @click="insertReferencePrefix('@folder:')"
          >
            <Folder :size="15" aria-hidden="true" />
            <span>文件夹</span>
          </button>
          <button
            type="button"
            class="composer-tool-button"
            aria-label="引用 Git Diff"
            title="引用 Git Diff"
            @click="insertToken('@diff ')"
          >
            <GitBranch :size="15" aria-hidden="true" />
            <span>Diff</span>
          </button>
          <button
            type="button"
            class="composer-tool-button"
            aria-label="引用网页"
            title="引用网页"
            @click="insertReferencePrefix('@url:')"
          >
            <Link2 :size="15" aria-hidden="true" />
            <span>URL</span>
          </button>
          <button
            type="button"
            class="composer-tool-button"
            aria-label="上传文件"
            title="上传文件"
            :disabled="uploading"
            @click="triggerUpload"
          >
            <Upload :size="15" aria-hidden="true" />
            <span>{{ uploading ? "上传中…" : "上传" }}</span>
          </button>
        </div>
        <input
          ref="fileInputRef"
          class="upload-input"
          type="file"
          aria-label="选择要上传的文件"
          accept="image/png,image/jpeg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.rtf,.txt,.md,.json,.csv"
          @change="handleUploadFile"
        />
        <span v-if="uploadState" class="upload-state" aria-live="polite">{{ uploadState }}</span>
        <span class="composer-hint">
          <kbd>/</kbd> 命令 · <kbd>@</kbd> 引用上下文
        </span>
      </div>

      <div class="composer-entry">
        <div
          v-if="completionOpen"
          class="completion-popover"
          tabindex="-1"
          @keydown="handleCompletionKeydown"
          @wheel.stop
        >
          <div class="completion-head">
            <span>{{ completionMode === "slash" ? "命令" : "上下文引用" }}</span>
            <small>{{ referenceLoading ? "搜索中…" : "↑↓ 选择 · Enter 插入 · Esc 关闭" }}</small>
          </div>
          <div v-if="completionItems.length" ref="completionListRef" class="completion-list" @wheel.stop>
            <button
              v-for="(item, index) in completionItems"
              :key="`${item.kind}:${item.value}:${index}`"
              type="button"
              class="completion-item"
              :class="{ active: index === selectedCompletionIndex }"
              @mousedown.prevent="applyCompletion(item)"
              @mouseenter="selectCompletion(index)"
              @keydown.stop="handleCompletionKeydown"
            >
              <span class="completion-glyph">
                <component :is="completionIcon(item)" :size="16" aria-hidden="true" />
              </span>
              <span class="completion-copy">
                <strong>{{ item.label }}</strong>
                <small>{{ item.detail }}</small>
              </span>
              <kbd v-if="index === selectedCompletionIndex">Enter</kbd>
            </button>
          </div>
          <div v-else class="completion-empty">
            没找到匹配项。你也可以继续手动输入。
          </div>
        </div>

        <form class="composer-bar" @submit.prevent="submitDraft">
          <textarea
            ref="textareaRef"
            v-model="draft"
            name="message"
            aria-label="给 Sierra 发送消息"
            autocomplete="off"
            placeholder="输入消息，或 /help 查看命令…"
            rows="1"
            @blur="deferCloseCompletion"
            @click="updateCompletion"
            @input="onDraftInput"
            @keydown="handleKeydown"
            @keyup="handleKeyup"
          ></textarea>
          <button
            v-if="sending"
            class="stop-button"
            type="button"
            aria-label="停止当前处理"
            title="停止当前处理"
            @click="$emit('cancel-chat')"
          >
            <Square :size="15" aria-hidden="true" />
            停止
          </button>
          <button class="send-button" type="submit" :disabled="sending || !draft.trim()">
            <Send :size="17" aria-hidden="true" />
            发送
          </button>
        </form>
      </div>
    </section>

    <Teleport to="body">
      <div
        v-if="previewImage"
        ref="previewOverlayRef"
        class="image-preview-overlay"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        @keydown.esc="closeImagePreview"
        @click.self="closeImagePreview"
      >
        <button class="image-preview-close" type="button" aria-label="关闭预览" @click="closeImagePreview">
          <X :size="18" />
        </button>
        <div class="image-preview-stage">
          <img :src="previewImage.url" alt="" width="1280" height="960" />
        </div>
      </div>
    </Teleport>
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
  Menu,
  MessageCircleQuestion,
  RefreshCw,
  ScrollText,
  Send,
  ShieldAlert,
  Sparkles,
  Square,
  Upload,
  UserRound,
  WandSparkles,
  Wrench,
  X
} from "lucide-vue-next";
import { gsap } from "gsap";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import type { ChatActivityEvent, ChatMessage } from "../types";

type CompletionMode = "slash" | "reference";

type CompletionItem = {
  kind: string;
  label: string;
  detail: string;
  value: string;
  requiresArgument?: boolean;
};

type MessageAttachment = {
  id: string;
  kind: "image" | "file";
  name: string;
  path: string;
  token: string;
  url: string;
  extension: string;
};

type RenderedChatMessage = ChatMessage & {
  displayText: string;
  attachments: MessageAttachment[];
};

const props = defineProps<{
  activeModelLabel: string;
  activityEvents: ChatActivityEvent[];
  error: string;
  loading: boolean;
  messages: ChatMessage[];
  planMode: boolean;
  planModeLoading: boolean;
  sending: boolean;
  usagePercent: number;
}>();

const emit = defineEmits<{
  (event: "refresh"): void;
  (event: "send", value: string): void;
  (event: "cancel-chat"): void;
  (event: "open-navigation"): void;
  (event: "toggle-plan-mode"): void;
  (event: "approve-tool", id: string, decision: "once" | "session" | "deny"): void;
  (
    event: "respond-user-input",
    id: string,
    payload: { value?: string; label?: string; free_text?: boolean; cancelled?: boolean }
  ): void;
}>();

const DRAFT_KEY = "sierra:web:draft";
const HISTORY_KEY = "sierra:web:input-history";
const IMAGE_FILE_RE = /\.(png|jpe?g|webp|gif|bmp|svg)$/i;
const FILE_REFERENCE_RE = /@file:(`([^`]+)`|"([^"]+)"|'([^']+)'|([^\s]+))/g;
const INTERACTIVE_SELECTOR = [
  ".composer-tool-button",
  ".send-button",
  ".stop-button",
  ".refresh-status",
  ".mobile-nav-toggle",
  ".plan-mode-toggle",
  ".completion-item",
  ".approval-button",
  ".message-attachment",
  ".draft-attachment"
].join(",");

const fallbackSlashCommands: CompletionItem[] = [
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
  { kind: "command", label: "/plugins", detail: "查看插件状态", value: "/plugins" },
  { kind: "command", label: "/skills", detail: "查看可用技能", value: "/skills" },
  { kind: "command", label: "/skills-reload", detail: "重新加载技能", value: "/skills-reload" },
  { kind: "command", label: "/skills-stats", detail: "查看技能使用统计", value: "/skills-stats" },
  { kind: "command", label: "/reload-config", detail: "重新读取 config.json", value: "/reload-config" },
  { kind: "command", label: "/debug-context", detail: "查看上下文结构", value: "/debug-context" },
  { kind: "command", label: "/audit", detail: "查看工具审计日志", value: "/audit" }
];
const slashCommands = ref<CompletionItem[]>(fallbackSlashCommands);

const draft = ref("");
const freeText = ref<Record<string, string>>({});
const workspaceRef = ref<HTMLElement | null>(null);
const previewOverlayRef = ref<HTMLElement | null>(null);
const scrollEl = ref<HTMLElement | null>(null);
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const completionListRef = ref<HTMLElement | null>(null);
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
const previewImage = ref<MessageAttachment | null>(null);
let referenceRequestId = 0;
let slashRequestId = 0;
let gsapContext: ReturnType<typeof gsap.context> | undefined;
let lastAnimatedMessageId = "";

const renderedMessages = computed<RenderedChatMessage[]>(() =>
  props.messages.map((message) => {
    const attachments = extractAttachments(message.text);
    return {
      ...message,
      displayText: stripAttachmentTokens(message.text, attachments),
      attachments
    };
  })
);
const draftAttachments = computed(() => extractAttachments(draft.value));
const recentUserImageReference = computed(() =>
  renderedMessages.value
    .slice(-4)
    .some((message) => message.role === "user" && message.attachments.some((item) => item.kind === "image"))
);

const visibleActivityEvents = computed(() => props.activityEvents.slice(-5));
const activityPriority = (event: ChatActivityEvent) => {
  if (event.type === "approval") {
    return 0;
  }
  if (event.type === "user-input") {
    return 1;
  }
  if (event.type === "tool") {
    return 2;
  }
  if (event.type === "command") {
    return 3;
  }
  if (["context", "reference", "history", "memory"].includes(event.type)) {
    return 4;
  }
  if (event.type === "thinking") {
    return 5;
  }
  return 6;
};
const activeActivity = computed(() => {
  const indexedEvents = props.activityEvents.map((event, index) => ({ event, index }));
  const activeEvents = indexedEvents
    .filter((item) => item.event.status === "active");
  activeEvents.sort((left, right) => {
    const priority = activityPriority(left.event) - activityPriority(right.event);
    return priority || right.index - left.index;
  });
  if (activeEvents[0]) {
    return activeEvents[0].event;
  }
  return [...indexedEvents]
    .reverse()
    .find((item) => item.event.status !== "muted" && item.event.type !== "thinking")?.event
    || [...indexedEvents].reverse().find((item) => item.event.status !== "muted")?.event;
});
const processFeedEvents = computed(() =>
  props.activityEvents
    .filter((event) => {
      if (event.type === "thinking") {
        return false;
      }
      return ["tool", "approval", "user-input", "command", "context", "reference", "history", "memory", "error"].includes(event.type);
    })
    .slice(-6)
);
const showProcessPanel = computed(() => Boolean(activeActivity.value));
const showActivity = computed(() => showProcessPanel.value || processFeedEvents.value.length > 0);
const showProcessActions = computed(() => {
  const event = activeActivity.value;
  if (!event || event.status !== "active") {
    return false;
  }
  if (event.type === "approval") {
    return Boolean(event.approvalId);
  }
  if (event.type === "user-input") {
    return Boolean(event.inputId);
  }
  return false;
});
const activeActivityIcon = computed(() => activeActivity.value ? iconFor(activeActivity.value) : Sparkles);
const processClasses = computed(() => {
  const event = activeActivity.value;
  return event ? [event.type, event.status, riskClass(event)] : [];
});
const processKicker = computed(() => {
  const event = activeActivity.value;
  if (event?.type === "command") {
    return "命令";
  }
  if (!event) {
    return "处理";
  }
  if (event.type === "tool") {
    return "工具";
  }
  if (event.type === "approval") {
    return "确认";
  }
  if (event.type === "user-input") {
    return "等待";
  }
  if (event.type === "thinking" && recentUserImageReference.value) {
    return "视觉";
  }
  return "处理";
});
const processTitle = computed(() => {
  const event = activeActivity.value;
  if (event?.type === "command") {
    return event.status === "done" ? "命令完成" : "执行命令";
  }
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
    if (event.status === "done") {
      return event.label || "上下文已整理";
    }
    return event.label || "整理上下文";
  }
  if (event.type === "thinking") {
    if (recentUserImageReference.value && event.status === "active") {
      return "分析图片中";
    }
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
    return recentUserImageReference.value ? "正在读取你发来的图片。" : "";
  }
  if ((event.type === "context" || event.type === "reference") && event.status === "done") {
    const detail = event.reason || event.detail || "";
    return detail.includes("正在") ? "上下文整理已完成。" : detail;
  }
  return event.reason || event.detail || "";
});
const processStatusText = computed(() => {
  const status = activeActivity.value?.status;
  if (status === "done") {
    return "完成";
  }
  if (status === "error") {
    return "待处理";
  }
  return "进行中";
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
  return [
    { key: "thinking", label: "思考", icon: WandSparkles, ...phaseState(["thinking"]) },
    { key: "context", label: "上下文", icon: ScrollText, ...phaseState(["context", "reference", "history"]) },
    { key: "tool", label: "工具", icon: Wrench, ...phaseState(["tool"]) },
    { key: "approval", label: "确认", icon: ShieldAlert, ...phaseState(["approval", "user-input"]) },
    { key: "memory", label: "记忆", icon: Database, ...phaseState(["memory"]) }
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

function extractAttachments(text: string): MessageAttachment[] {
  const attachments: MessageAttachment[] = [];
  const seen = new Set<string>();
  FILE_REFERENCE_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = FILE_REFERENCE_RE.exec(text)) !== null) {
    const path = normalizeReferencePath(match[2] || match[3] || match[4] || match[5] || "");
    if (!path || seen.has(path)) {
      continue;
    }
    seen.add(path);
    const extension = fileExtension(path);
    const kind = IMAGE_FILE_RE.test(path) ? "image" : "file";
    attachments.push({
      id: `${path}:${match.index}`,
      kind,
      name: fileName(path),
      path,
      token: match[0],
      url: previewUrl(path),
      extension
    });
  }
  return attachments;
}

function normalizeReferencePath(value: string) {
  return String(value || "")
    .trim()
    .replace(/^file:/i, "")
    .replace(/^[/\\]+/, "");
}

function stripAttachmentTokens(text: string, attachments: MessageAttachment[]) {
  let displayText = String(text || "");
  for (const attachment of attachments) {
    displayText = displayText.replace(attachment.token, "");
  }
  return displayText
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function previewUrl(path: string) {
  return `/api/files/preview?path=${encodeURIComponent(path)}`;
}

function fileName(path: string) {
  const normalized = path.replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).pop() || normalized || "file";
}

function fileExtension(path: string) {
  const name = fileName(path);
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toUpperCase() : "";
}

function openImagePreview(attachment: MessageAttachment) {
  previewImage.value = attachment;
  nextTick(() => {
    const overlay = previewOverlayRef.value;
    if (!overlay) {
      return;
    }
    overlay.focus({ preventScroll: true });
    runScopedAnimation(() => {
      gsap.fromTo(
        overlay,
        { autoAlpha: 0 },
        { autoAlpha: 1, duration: 0.18, ease: "power2.out", overwrite: "auto" }
      );
      gsap.fromTo(
        overlay.querySelector(".image-preview-stage"),
        { autoAlpha: 0, y: 18, scale: 0.965 },
        { autoAlpha: 1, y: 0, scale: 1, duration: 0.28, ease: "power3.out", overwrite: "auto" }
      );
    });
  });
}

function closeImagePreview() {
  const overlay = previewOverlayRef.value;
  if (!overlay || prefersReducedMotion()) {
    previewImage.value = null;
    return;
  }
  gsap.to(overlay, {
    autoAlpha: 0,
    duration: 0.16,
    ease: "power2.in",
    overwrite: "auto",
    onComplete: () => {
      previewImage.value = null;
    }
  });
}

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
  if (event.approvalId) {
    emit("approve-tool", event.approvalId, decision);
  }
}

function submitInputOption(event: ChatActivityEvent, option: { label: string; value?: string; description?: string }) {
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
    free_text: true,
    cancelled: false
  });
  freeText.value[event.id] = "";
}

function cancelInput(event: ChatActivityEvent) {
  if (event.inputId) {
    emit("respond-user-input", event.inputId, { cancelled: true });
  }
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
  uploadState.value = `上传 ${file.name}…`;
  try {
    const contentBase64 = await fileToBase64(file);
    const response = await fetch("/api/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, content_base64: contentBase64 })
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

function commandNeedsArgument(item: CompletionItem) {
  if (item.requiresArgument) {
    return true;
  }
  return [
    "/session-search",
    "/session-load",
    "/memory-search",
    "/memory-forget",
    "/cron-add"
  ].includes(item.label);
}

function shouldSubmitExactSlashCommand(item: CompletionItem | undefined, event: KeyboardEvent) {
  if (!item || event.key !== "Enter" || event.shiftKey || completionMode.value !== "slash") {
    return false;
  }
  return draft.value.trim() === item.label && !commandNeedsArgument(item);
}

function selectCompletion(index: number) {
  selectedCompletionIndex.value = Math.max(0, Math.min(index, Math.max(completionItems.value.length - 1, 0)));
  scrollSelectedCompletionIntoView();
}

function moveCompletionSelection(direction: -1 | 1) {
  const total = completionItems.value.length;
  if (!total) {
    return;
  }
  selectedCompletionIndex.value = (selectedCompletionIndex.value + direction + total) % total;
  scrollSelectedCompletionIntoView();
}

function scrollSelectedCompletionIntoView() {
  nextTick(() => {
    const list = completionListRef.value;
    if (!list || !completionOpen.value) {
      return;
    }
    const active = list.querySelector<HTMLElement>(".completion-item.active");
    if (!active) {
      return;
    }
    active.scrollIntoView({ block: "nearest" });
    animateCompletionSelection(active);
  });
}

function animateCompletionSelection(active: HTMLElement) {
  if (prefersReducedMotion()) {
    return;
  }
  runScopedAnimation(() => {
    gsap.fromTo(
      active,
      { x: -4, scale: 0.992 },
      { x: 0, scale: 1, duration: 0.16, ease: "power2.out", overwrite: "auto" }
    );
  });
}

function handleCompletionKeydown(event: KeyboardEvent) {
  if (!completionOpen.value) {
    return;
  }
  handleKeydown(event);
}

function handleKeydown(event: KeyboardEvent) {
  if (completionOpen.value) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveCompletionSelection(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveCompletionSelection(-1);
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      const selected = completionItems.value[selectedCompletionIndex.value];
      if (shouldSubmitExactSlashCommand(selected, event)) {
        event.preventDefault();
        completionOpen.value = false;
        submitDraft();
        return;
      }
      if (selected) {
        event.preventDefault();
        applyCompletion(selected);
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

function handleKeyup(event: KeyboardEvent) {
  if (
    completionOpen.value
    && ["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"].includes(event.key)
  ) {
    return;
  }
  updateCompletion();
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

function mapCommandCompletion(item: any): CompletionItem | null {
  const label = String(item?.label || item?.value || "");
  const value = String(item?.value || label);
  if (!label || !value) {
    return null;
  }
  return {
    kind: "command",
    label,
    detail: String(item?.detail || item?.description || ""),
    value,
    requiresArgument: Boolean(item?.requires_argument || item?.requiresArgument)
  };
}

async function loadSlashCommands() {
  try {
    const response = await fetch("/api/commands/catalog");
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Command catalog API ${response.status}`);
    }
    const items = Array.isArray(data.items)
      ? data.items.map(mapCommandCompletion).filter(Boolean) as CompletionItem[]
      : [];
    if (items.length) {
      slashCommands.value = items;
    }
  } catch {
    slashCommands.value = fallbackSlashCommands;
  }
}

async function fetchSlashSuggestions(query: string) {
  const requestId = ++slashRequestId;
  try {
    const response = await fetch(`/api/commands/complete?q=${encodeURIComponent(query)}&limit=18`);
    const data = await response.json();
    if (requestId !== slashRequestId || !response.ok || data.ok === false) {
      return;
    }
    const items = Array.isArray(data.items)
      ? data.items.map(mapCommandCompletion).filter(Boolean) as CompletionItem[]
      : [];
    if (items.length || query.trim()) {
      completionItems.value = items;
      selectedCompletionIndex.value = 0;
      completionOpen.value = items.length > 0;
    }
  } catch {
    // Local fallback already filled the popover.
  }
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
    completionItems.value = slashCommands.value
      .filter((item) => item.label.toLowerCase().startsWith(query))
      .slice(0, 12);
    selectedCompletionIndex.value = 0;
    completionOpen.value = completionItems.value.length > 0;
    fetchSlashSuggestions(query);
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
  slashRequestId += 1;
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
  if (event.type === "command") {
    return ScrollText;
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

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function runScopedAnimation(callback: () => void) {
  if (prefersReducedMotion()) {
    return;
  }
  if (gsapContext) {
    gsapContext.add(callback);
  } else {
    callback();
  }
}

function setupMotion() {
  if (!workspaceRef.value) {
    return;
  }
  gsapContext = gsap.context(() => {
    if (prefersReducedMotion()) {
      return;
    }
    const intro = gsap.timeline({ defaults: { ease: "power3.out" } });
    const emptyHeroTitle = workspaceRef.value?.querySelector<HTMLElement>(".empty-hero h2");
    gsap.set([".chat-statusbar", ".composer-dock"], { willChange: "transform, opacity" });
    gsap.set(".usage-orb", { willChange: "transform" });
    intro
      .from(".chat-statusbar", {
        autoAlpha: 0,
        y: -10,
        duration: 0.42
      })
      .from(
        ".composer-dock",
        {
          autoAlpha: 0,
          y: 22,
          scale: 0.985,
          duration: 0.52
        },
        "<0.08"
      );
    if (emptyHeroTitle) {
      intro.from(
        emptyHeroTitle,
        {
          autoAlpha: 0,
          y: 14,
          scale: 0.98,
          duration: 0.48
        },
        "<0.1"
      );
    }
    intro.set([".chat-statusbar", ".composer-dock"], { clearProps: "willChange" });
    gsap.to(".usage-orb", {
      rotation: 360,
      duration: 12,
      repeat: -1,
      ease: "none"
    });
  }, workspaceRef.value);

  workspaceRef.value.addEventListener("pointerover", handleInteractiveOver);
  workspaceRef.value.addEventListener("pointerout", handleInteractiveOut);
  workspaceRef.value.addEventListener("pointerdown", handleInteractiveDown);
  workspaceRef.value.addEventListener("pointerup", handleInteractiveUp);
  textareaRef.value?.addEventListener("focus", handleComposerFocusIn);
  textareaRef.value?.addEventListener("blur", handleComposerFocusOut);
}

function cleanupMotion() {
  if (workspaceRef.value) {
    workspaceRef.value.removeEventListener("pointerover", handleInteractiveOver);
    workspaceRef.value.removeEventListener("pointerout", handleInteractiveOut);
    workspaceRef.value.removeEventListener("pointerdown", handleInteractiveDown);
    workspaceRef.value.removeEventListener("pointerup", handleInteractiveUp);
  }
  textareaRef.value?.removeEventListener("focus", handleComposerFocusIn);
  textareaRef.value?.removeEventListener("blur", handleComposerFocusOut);
  gsapContext?.revert();
  gsapContext = undefined;
}

function animateComposerFocus(focused: boolean) {
  const dock = workspaceRef.value?.querySelector<HTMLElement>(".composer-dock");
  if (!dock) {
    return;
  }
  runScopedAnimation(() => {
    gsap.to(dock, {
      y: focused ? -2 : 0,
      scale: focused ? 1.003 : 1,
      duration: focused ? 0.24 : 0.28,
      ease: focused ? "power2.out" : "power3.out",
      overwrite: "auto"
    });
  });
}

function handleComposerFocusIn() {
  animateComposerFocus(true);
}

function handleComposerFocusOut() {
  animateComposerFocus(false);
}

function animatePlanModeToggle(enabled: boolean) {
  nextTick(() => {
    const button = workspaceRef.value?.querySelector<HTMLElement>(".composer-plan-toggle");
    if (!button) {
      return;
    }
    const icon = button.querySelector("svg");
    runScopedAnimation(() => {
      const timeline = gsap.timeline({ defaults: { overwrite: "auto" } });
      timeline.fromTo(
        button,
        { scale: 0.965, y: 1 },
        { scale: 1, y: 0, duration: 0.34, ease: "back.out(2.1)", clearProps: "transform" }
      );
      if (icon) {
        timeline.fromTo(
          icon,
          { rotation: enabled ? -10 : 8, scale: 0.9 },
          { rotation: 0, scale: 1, duration: 0.3, ease: "back.out(2)", clearProps: "transform" },
          "<"
        );
      }
    });
  });
}

function interactiveTarget(event: Event) {
  const target = event.target instanceof Element
    ? event.target.closest<HTMLElement>(INTERACTIVE_SELECTOR)
    : null;
  return target && workspaceRef.value?.contains(target) ? target : null;
}

function handleInteractiveOver(event: PointerEvent) {
  const target = interactiveTarget(event);
  if (!target || target.contains(event.relatedTarget as Node | null)) {
    return;
  }
  runScopedAnimation(() => {
    gsap.to(target, {
      y: -2,
      scale: 1.015,
      duration: 0.18,
      ease: "power2.out",
      overwrite: "auto"
    });
  });
}

function handleInteractiveOut(event: PointerEvent) {
  const target = interactiveTarget(event);
  if (!target || target.contains(event.relatedTarget as Node | null)) {
    return;
  }
  runScopedAnimation(() => {
    gsap.to(target, {
      y: 0,
      scale: 1,
      duration: 0.2,
      ease: "power2.out",
      overwrite: "auto"
    });
  });
}

function handleInteractiveDown(event: PointerEvent) {
  const target = interactiveTarget(event);
  if (!target) {
    return;
  }
  runScopedAnimation(() => {
    gsap.to(target, {
      scale: 0.975,
      duration: 0.1,
      ease: "power2.out",
      overwrite: "auto"
    });
  });
}

function handleInteractiveUp(event: PointerEvent) {
  const target = interactiveTarget(event);
  if (!target) {
    return;
  }
  runScopedAnimation(() => {
    gsap.to(target, {
      y: -2,
      scale: 1.015,
      duration: 0.18,
      ease: "back.out(1.6)",
      overwrite: "auto"
    });
  });
}

function animateLatestMessage() {
  const last = renderedMessages.value[renderedMessages.value.length - 1];
  if (!last || last.id === lastAnimatedMessageId) {
    return;
  }
  lastAnimatedMessageId = last.id;
  nextTick(() => {
    const rows = workspaceRef.value?.querySelectorAll<HTMLElement>(".message-row");
    const row = rows?.[rows.length - 1];
    if (!row) {
      return;
    }
    const direction = row.classList.contains("user") ? 14 : -14;
    runScopedAnimation(() => {
      gsap.fromTo(
        row,
        { autoAlpha: 0, x: direction, y: 8, scale: 0.985, willChange: "transform, opacity" },
        {
          autoAlpha: 1,
          x: 0,
          y: 0,
          scale: 1,
          duration: 0.28,
          ease: "power3.out",
          overwrite: "auto",
          clearProps: "transform,opacity,visibility,willChange"
        }
      );
      const attachments = row.querySelectorAll(".message-attachment");
      if (attachments.length) {
        gsap.from(attachments, {
          autoAlpha: 0,
          y: 12,
          scale: 0.96,
          duration: 0.34,
          ease: "back.out(1.5)",
          stagger: 0.06
        });
      }
    });
  });
}

function animateActivityPanel() {
  nextTick(() => {
    const panel = workspaceRef.value?.querySelector<HTMLElement>(".process-panel");
    const feedItems = workspaceRef.value?.querySelectorAll<HTMLElement>(".process-feed-item");
    const actions = workspaceRef.value?.querySelector<HTMLElement>(".process-actions");
    runScopedAnimation(() => {
      if (panel) {
        const firstRun = panel.dataset.motionReady !== "true";
        panel.dataset.motionReady = "true";
        const timeline = gsap.timeline({ defaults: { ease: "power3.out", overwrite: "auto" } });
        timeline.fromTo(
          panel,
          firstRun
            ? { autoAlpha: 0, y: 14, scale: 0.988 }
            : { y: 4, scale: 0.998 },
          firstRun
            ? { autoAlpha: 1, y: 0, scale: 1, duration: 0.28 }
            : { y: 0, scale: 1, duration: 0.18 }
        );
        const activePhases = panel.querySelectorAll(".process-phase.active");
        if (activePhases.length) {
          timeline.fromTo(
            activePhases,
            { y: 2, scale: 0.94 },
            { y: 0, scale: 1, duration: 0.22, stagger: 0.025 },
            firstRun ? "<0.08" : "<"
          );
        }
      }
      if (feedItems?.length) {
        gsap.fromTo(
          feedItems[feedItems.length - 1],
          { autoAlpha: 0, y: 9, scale: 0.985 },
          {
            autoAlpha: 1,
            y: 0,
            scale: 1,
            duration: 0.24,
            ease: "power2.out",
            overwrite: "auto"
          }
        );
      }
      if (actions) {
        gsap.fromTo(
          actions,
          { autoAlpha: 0, y: 6 },
          {
            autoAlpha: 1,
            y: 0,
            duration: 0.18,
            ease: "power2.out",
            overwrite: "auto"
          }
        );
      }
    });
  });
}
function animateUploadState() {
  nextTick(() => {
    const state = workspaceRef.value?.querySelector<HTMLElement>(".upload-state");
    if (!state) {
      return;
    }
    runScopedAnimation(() => {
      gsap.fromTo(
        state,
        { autoAlpha: 0, y: 6, scale: 0.96 },
        { autoAlpha: 1, y: 0, scale: 1, duration: 0.22, ease: "back.out(1.8)", overwrite: "auto" }
      );
    });
  });
}

function animateAttachmentLoad(event: Event) {
  const target = event.currentTarget instanceof Element
    ? event.currentTarget.closest<HTMLElement>(".message-attachment, .draft-attachment")
    : null;
  if (!target) {
    return;
  }
  runScopedAnimation(() => {
    gsap.fromTo(
      target,
      { autoAlpha: 0.74, y: 8, scale: 0.975 },
      { autoAlpha: 1, y: 0, scale: 1, duration: 0.34, ease: "power3.out", overwrite: "auto" }
    );
    const glint = target.querySelector(".attachment-glint");
    if (glint) {
      gsap.fromTo(
        glint,
        { xPercent: -120, autoAlpha: 0 },
        { xPercent: 120, autoAlpha: 0.7, duration: 0.62, ease: "power2.inOut", overwrite: "auto" }
      );
    }
  });
}

async function scrollToBottom() {
  await nextTick();
  if (scrollEl.value) {
    scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
  }
}

onMounted(() => {
  loadSlashCommands();
  loadComposerState();
  setupMotion();
  animateLatestMessage();
});

onUnmounted(cleanupMotion);

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
    animateLatestMessage();
  },
  { flush: "post" }
);

watch(
  () => props.activityEvents.map((event) => `${event.id}:${event.status}:${event.detail}`).join("|"),
  animateActivityPanel,
  { flush: "post" }
);

watch(
  () => [completionOpen.value, selectedCompletionIndex.value, completionItems.value.length],
  () => {
    if (completionOpen.value) {
      scrollSelectedCompletionIntoView();
    }
  },
  { flush: "post" }
);

watch(uploadState, (value) => {
  if (value) {
    animateUploadState();
  }
});

watch(() => props.planMode, animatePlanModeToggle, { flush: "post" });
</script>
