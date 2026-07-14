<template>
  <aside ref="sidebarRef" class="sidebar-shell">
    <div class="brand-cluster">
      <img class="brand-avatar" src="/brand/sierra-avatar.png?v=transparent-1" alt="Sierra" />
      <div class="brand-copy">
        <h1>Sierra</h1>
      </div>
    </div>

    <button class="primary-action" type="button" @click="$emit('new-chat')">
      <SierraOrnaments variant="button" compact />
      <Plus :size="16" />
      新会话
    </button>

    <nav class="main-nav" aria-label="Sierra dashboard">
      <button
        v-for="item in navItems"
        :key="item.id"
        class="nav-button"
        :class="{ active: activeView === item.id }"
        type="button"
        @click="$emit('select-view', item.id)"
      >
        <component :is="item.icon" :size="17" />
        <span>
          <strong>{{ item.label }}</strong>
          <small>{{ item.subtitle }}</small>
        </span>
      </button>
    </nav>

    <section class="session-stack">
      <div class="sidebar-label">会话记录</div>
      <div
        v-for="session in recentSessions"
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
            aria-label="会话名称"
            maxlength="120"
            @keydown.esc.prevent="cancelRename"
          />
          <button class="session-action confirm" type="submit" title="保存">
            <Check :size="14" />
          </button>
          <button class="session-action" type="button" title="取消" @click="cancelRename">
            <X :size="14" />
          </button>
        </form>
        <template v-else>
          <button
            class="session-link"
            :class="{ active: activeSessionId === session.id }"
            type="button"
            @click="$emit('open-session', session.id)"
          >
            <MessageCircle :size="15" />
            <span>
              <strong>{{ sessionTitle(session) }}</strong>
              <small>{{ formatTimestamp(session.updated || session.updated_at || session.created) }}</small>
            </span>
          </button>
          <div class="session-actions" aria-label="会话操作">
            <button class="session-action" type="button" title="重命名" @click="beginRename(session)">
              <Pencil :size="13" />
            </button>
            <button class="session-action danger" type="button" title="删除" @click="confirmDelete(session)">
              <Trash2 :size="13" />
            </button>
          </div>
        </template>
      </div>
      <p v-if="!recentSessions.length" class="sidebar-empty">暂无会话记录</p>
    </section>

    <section class="sidebar-footer">
      <button class="settings-line" type="button" @click="$emit('open-settings')">
        <SierraOrnaments variant="button" compact />
        <Settings2 :size="17" />
        <span>
          <strong>设置</strong>
          <small>模型、能力、工具接入</small>
        </span>
      </button>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { Check, MessageCircle, Pencil, Plus, Settings2, Trash2, X } from "lucide-vue-next";
import { gsap } from "gsap";
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import type { DashboardPayload, NavItem, SessionSummary, ViewId } from "../types";
import { formatTimestamp } from "../types";
import SierraOrnaments from "./SierraOrnaments.vue";

const props = defineProps<{
  activeSessionId: string;
  activeView: ViewId;
  error: string;
  loading: boolean;
  navItems: NavItem[];
  payload: DashboardPayload | null;
  recentSessions: SessionSummary[];
}>();

const emit = defineEmits<{
  (event: "select-view", value: ViewId): void;
  (event: "new-chat"): void;
  (event: "open-session", value: string): void;
  (event: "rename-session", value: { id: string; title: string }): void;
  (event: "delete-session", value: string): void;
  (event: "refresh"): void;
  (event: "open-settings"): void;
}>();

const editingSessionId = ref("");
const editingTitle = ref("");
const sidebarRef = ref<HTMLElement | null>(null);
let sidebarMotion: ReturnType<typeof gsap.matchMedia> | undefined;
const animatedSessionIds = new Set<string>();

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
      compact: "(max-width: 860px)",
      reduceMotion: "(prefers-reduced-motion: reduce)"
    },
    (context) => {
      const conditions = context.conditions as { compact: boolean; reduceMotion: boolean };
      if (conditions.reduceMotion) {
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
