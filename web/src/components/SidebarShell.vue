<template>
  <aside
    ref="sidebarRef"
    class="sidebar-shell"
    :class="{ 'mobile-open': mobileOpen }"
    :aria-hidden="compactLayout && !mobileOpen"
  >
    <header class="brand-cluster">
      <img
        class="brand-avatar"
        src="/brand/sierra-avatar.png?v=transparent-1"
        alt=""
        width="44"
        height="44"
      />
      <div class="brand-copy">
        <h1 translate="no">Sierra</h1>
        <span class="brand-presence" :class="{ offline: error }">
          <i aria-hidden="true"></i>
          {{ error ? "连接异常" : "在线" }}
        </span>
      </div>
      <button
        v-if="compactLayout"
        class="sidebar-close"
        type="button"
        aria-label="关闭会话列表"
        @click="$emit('close')"
      >
        <PanelLeftClose :size="18" aria-hidden="true" />
      </button>
    </header>

    <button
      class="primary-action"
      type="button"
      :disabled="newChatLoading"
      :aria-busy="newChatLoading"
      @click="openNewChat"
    >
      <LoaderCircle v-if="newChatLoading" class="new-chat-spinner" :size="17" aria-hidden="true" />
      <Plus v-else :size="17" aria-hidden="true" />
      <span>{{ newChatLoading ? "正在开启…" : "新会话" }}</span>
    </button>

    <section class="session-stack" aria-labelledby="session-list-title">
      <header class="session-stack-header">
        <div>
          <span id="session-list-title" class="sidebar-label">会话</span>
          <b>{{ recentSessions.length }}</b>
        </div>
        <button
          class="sidebar-refresh"
          type="button"
          :disabled="loading"
          aria-label="刷新会话"
          @click="$emit('refresh')"
        >
          <RefreshCw :size="14" aria-hidden="true" />
        </button>
      </header>

      <label class="session-search">
        <span class="sr-only">搜索会话</span>
        <Search :size="15" aria-hidden="true" />
        <input
          v-model.trim="sessionQuery"
          name="session-search"
          type="search"
          autocomplete="off"
          placeholder="搜索会话…"
        />
      </label>

      <div class="session-list">
        <div
          v-for="session in filteredSessions"
          :key="session.id"
          class="session-row"
          :class="{ active: activeSessionId === session.id }"
        >
          <form
            v-if="editingSessionId === session.id"
            class="session-edit-form"
            @submit.prevent="commitRename(session)"
          >
            <input
              v-model="editingTitle"
              name="session-title"
              aria-label="会话名称"
              autocomplete="off"
              maxlength="120"
              @keydown.esc.prevent="cancelRename"
            />
            <button class="session-action confirm" type="submit" aria-label="保存会话名称">
              <Check :size="14" aria-hidden="true" />
            </button>
            <button class="session-action" type="button" aria-label="取消重命名" @click="cancelRename">
              <X :size="14" aria-hidden="true" />
            </button>
          </form>
          <template v-else>
            <button
              class="session-link"
              :class="{ active: activeSessionId === session.id }"
              type="button"
              @click="openSession(session.id)"
            >
              <MessageCircle :size="15" aria-hidden="true" />
              <span>
                <strong>{{ sessionTitle(session) }}</strong>
                <small>{{ formatTimestamp(session.updated || session.updated_at || session.created) }}</small>
              </span>
            </button>
            <div class="session-actions" aria-label="会话操作">
              <button
                class="session-action"
                type="button"
                :aria-label="`重命名会话 ${sessionTitle(session)}`"
                @click="beginRename(session)"
              >
                <Pencil :size="13" aria-hidden="true" />
              </button>
              <button
                class="session-action danger"
                type="button"
                :aria-label="`删除会话 ${sessionTitle(session)}`"
                @click="confirmDelete(session)"
              >
                <Trash2 :size="13" aria-hidden="true" />
              </button>
            </div>
          </template>
        </div>
        <p v-if="!recentSessions.length" class="sidebar-empty">还没有会话，先和 Sierra 说句话。</p>
        <p v-else-if="!filteredSessions.length" class="sidebar-empty">没有匹配的会话。</p>
      </div>
    </section>

    <footer class="sidebar-footer">
      <button class="settings-line" type="button" @click="openSettings">
        <Settings2 :size="18" aria-hidden="true" />
        <span>
          <strong>设置</strong>
          <small>模型、能力与接入</small>
        </span>
        <ChevronRight :size="15" aria-hidden="true" />
      </button>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import {
  Check,
  ChevronRight,
  LoaderCircle,
  MessageCircle,
  PanelLeftClose,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  X
} from "lucide-vue-next";
import { gsap } from "gsap";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import type { DashboardPayload, SessionSummary } from "../types";
import { formatTimestamp } from "../types";

const props = defineProps<{
  activeSessionId: string;
  compactLayout: boolean;
  error: string;
  loading: boolean;
  mobileOpen: boolean;
  newChatLoading: boolean;
  payload: DashboardPayload | null;
  recentSessions: SessionSummary[];
}>();

const emit = defineEmits<{
  (event: "new-chat"): void;
  (event: "open-session", value: string): void;
  (event: "rename-session", value: { id: string; title: string }): void;
  (event: "delete-session", value: string): void;
  (event: "refresh"): void;
  (event: "open-settings"): void;
  (event: "close"): void;
}>();

const editingSessionId = ref("");
const editingTitle = ref("");
const sessionQuery = ref("");
const sidebarRef = ref<HTMLElement | null>(null);
let sidebarMotion: ReturnType<typeof gsap.matchMedia> | undefined;
const animatedSessionIds = new Set<string>();

const filteredSessions = computed(() => {
  const query = sessionQuery.value.trim().toLocaleLowerCase();
  if (!query) {
    return props.recentSessions;
  }
  return props.recentSessions.filter((session) => sessionTitle(session).toLocaleLowerCase().includes(query));
});

function prefersReducedMotion() {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

function setupSidebarMotion() {
  if (!sidebarRef.value) {
    return;
  }
  sidebarMotion = gsap.matchMedia();
  sidebarMotion.add(
    {
      compact: "(max-width: 900px)",
      reduceMotion: "(prefers-reduced-motion: reduce)"
    },
    (context) => {
      const conditions = context.conditions as { compact: boolean; reduceMotion: boolean };
      if (conditions.reduceMotion || conditions.compact) {
        return;
      }
      const timeline = gsap.timeline({
        defaults: { duration: conditions.compact ? 0.28 : 0.38, ease: "power3.out" }
      });
      timeline
        .from(".brand-cluster", { autoAlpha: 0, x: -10 })
        .from(".primary-action", { autoAlpha: 0, y: 8, scale: 0.98 }, "<0.08")
        .from(".main-nav", { autoAlpha: 0, y: 7 }, "<0.06")
        .from(".sidebar-label", { autoAlpha: 0, x: -6 }, "<0.06")
        .from(".sidebar-footer", { autoAlpha: 0, y: 8 }, "<0.04");
      return () => timeline.kill();
    },
    sidebarRef.value
  );
}

async function animateNewSessions() {
  await nextTick();
  if (!sidebarRef.value) {
    return;
  }
  const rows = Array.from(sidebarRef.value.querySelectorAll<HTMLElement>(".session-row"));
  const freshRows = rows.filter((row, index) => {
    const id = String(props.recentSessions[index]?.id || "");
    if (!id || animatedSessionIds.has(id)) {
      return false;
    }
    animatedSessionIds.add(id);
    return true;
  });
  if (!freshRows.length || prefersReducedMotion()) {
    return;
  }
  gsap.fromTo(
    freshRows,
    { autoAlpha: 0, x: -8, y: 4 },
    {
      autoAlpha: 1,
      x: 0,
      y: 0,
      duration: 0.3,
      ease: "power2.out",
      stagger: 0.035,
      clearProps: "transform,opacity,visibility"
    }
  );
}

async function animateActiveSession() {
  await nextTick();
  const row = sidebarRef.value?.querySelector<HTMLElement>(".session-row.active");
  if (!row || prefersReducedMotion()) {
    return;
  }
  gsap.killTweensOf(row);
  gsap.fromTo(
    row,
    { x: -4, scale: 0.985 },
    {
      x: 0,
      scale: 1,
      duration: 0.34,
      ease: "back.out(1.8)",
      clearProps: "transform"
    }
  );
}

function sessionTitle(session: SessionSummary) {
  return String(session.title || "未命名会话");
}

function openNewChat() {
  emit("new-chat");
  emit("close");
}

function openSession(sessionId: string) {
  emit("open-session", sessionId);
  emit("close");
}

function openSettings() {
  emit("open-settings");
  emit("close");
}

function beginRename(session: SessionSummary) {
  editingSessionId.value = String(session.id || "");
  editingTitle.value = sessionTitle(session);
}

function cancelRename() {
  editingSessionId.value = "";
  editingTitle.value = "";
}

function commitRename(session: SessionSummary) {
  const id = String(session.id || "");
  const title = editingTitle.value.trim();
  if (id && title && title !== sessionTitle(session)) {
    emit("rename-session", { id, title });
  }
  cancelRename();
}

function confirmDelete(session: SessionSummary) {
  const id = String(session.id || "");
  if (!id) {
    return;
  }
  if (window.confirm(`删除会话「${sessionTitle(session)}」？`)) {
    emit("delete-session", id);
  }
}

watch(
  () => props.recentSessions.map((session) => String(session.id || "")).join("|"),
  animateNewSessions,
  { flush: "post" }
);

watch(() => props.activeSessionId, animateActiveSession, { flush: "post" });
onMounted(() => {
  setupSidebarMotion();
  animateNewSessions();
});

onUnmounted(() => {
  sidebarMotion?.revert();
  if (sidebarRef.value) {
    gsap.killTweensOf(sidebarRef.value.querySelectorAll("*"));
  }
});
</script>
