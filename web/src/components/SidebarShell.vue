<template>
  <aside class="sidebar-shell">
    <div class="brand-cluster">
      <img class="brand-avatar" src="/brand/sierra-avatar.png?v=transparent-1" alt="Sierra" />
      <div class="brand-copy">
        <h1>Sierra</h1>
      </div>
    </div>

    <button class="primary-action" type="button" @click="$emit('new-chat')">
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
      <button
        v-for="session in recentSessions"
        :key="session.id"
        class="session-link"
        :class="{ active: activeSessionId === session.id }"
        type="button"
        @click="$emit('open-session', session.id)"
      >
        <MessageCircle :size="15" />
        <span>
          <strong>{{ session.title || "未命名会话" }}</strong>
          <small>{{ formatTimestamp(session.updated || session.updated_at || session.created) }}</small>
        </span>
      </button>
      <p v-if="!recentSessions.length" class="sidebar-empty">暂无会话记录</p>
    </section>

    <section class="sidebar-footer">
      <button class="settings-line" type="button" @click="$emit('open-settings')">
        <Settings2 :size="17" />
        <span>
          <strong>设置</strong>
          <small>模型 / 工具 / 接入</small>
        </span>
      </button>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { MessageCircle, Plus, Settings2 } from "lucide-vue-next";
import type { DashboardPayload, NavItem, SessionSummary, ViewId } from "../types";
import { formatTimestamp } from "../types";

defineProps<{
  activeSessionId: string;
  activeView: ViewId;
  error: string;
  loading: boolean;
  navItems: NavItem[];
  payload: DashboardPayload | null;
  recentSessions: SessionSummary[];
}>();

defineEmits<{
  (event: "select-view", value: ViewId): void;
  (event: "new-chat"): void;
  (event: "open-session", value: string): void;
  (event: "refresh"): void;
  (event: "open-settings"): void;
}>();
</script>
