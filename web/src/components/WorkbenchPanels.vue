<template>
  <section class="workbench-page">
    <template v-if="activeView === 'sessions'">
      <div class="page-heading">
        <h3>会话</h3>
        <p>最近的本地会话。后续可以在这里接搜索、恢复、归档和分支。</p>
      </div>
      <div class="flat-list">
        <button
          v-for="session in recentSessions"
          :key="session.id"
          class="list-row clickable"
          type="button"
          @click="$emit('open-session', session.id)"
        >
          <span>
            <strong>{{ session.title || "未命名会话" }}</strong>
            <small>{{ session.id }}</small>
          </span>
          <b>{{ formatTimestamp(session.updated) }}</b>
        </button>
        <EmptyBlock v-if="!recentSessions.length" title="暂无会话" description="开始聊天后，这里会出现历史记录。" />
      </div>
    </template>

    <template v-else-if="activeView === 'memory'">
      <div class="page-heading">
        <h3>记忆</h3>
        <p>长期偏好和向量记忆状态。这里不做花哨看板，只显示能判断系统是否工作的信息。</p>
      </div>
      <div class="split-content">
        <section class="flat-section">
          <h4>Providers</h4>
          <div class="flat-list">
            <div v-for="provider in safeArray(payload.memory.providers)" :key="provider.name" class="list-row">
              <span>
                <strong>{{ provider.name }}</strong>
                <small>{{ provider.scope || provider.storage || "markdown" }}</small>
              </span>
              <b>{{ provider.records ?? provider.memory_count ?? provider.user_count ?? "on" }}</b>
            </div>
          </div>
        </section>
        <section class="flat-section">
          <h4>Curated Memory</h4>
          <pre class="memory-text">{{ payload.memory.curated || "暂无精选记忆。" }}</pre>
        </section>
      </div>
    </template>

    <template v-else-if="activeView === 'tools'">
      <div class="page-heading">
        <h3>工具</h3>
        <p>当前模型可调用的本地能力。只读工具、写入工具和高风险工具后续可以在这里配置策略。</p>
      </div>
      <div class="toolbar-line">
        <Search :size="16" />
        <input v-model="toolQuery" placeholder="搜索工具..." />
      </div>
      <div class="split-content">
        <section class="flat-section narrow">
          <h4>Toolsets</h4>
          <div class="pill-list">
            <button
              v-for="item in toolsets"
              :key="item.name"
              type="button"
              :class="{ active: activeToolset === item.name }"
              @click="activeToolset = activeToolset === item.name ? '' : item.name"
            >
              {{ item.name }}
              <b>{{ item.count }}</b>
            </button>
          </div>
        </section>
        <section class="flat-section">
          <h4>Tools</h4>
          <div class="tool-table">
            <div v-for="tool in filteredTools" :key="tool.name" class="tool-row">
              <strong>{{ tool.name }}</strong>
              <span>{{ tool.toolset }}</span>
            </div>
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="activeView === 'skills'">
      <div class="page-heading">
        <h3>Skills</h3>
        <p>渐进式披露的能力说明。Sierra 会按任务需要把相关 skill 注入上下文。</p>
      </div>
      <div class="flat-list">
        <div v-for="skill in safeArray(payload.skills.items)" :key="skill.name" class="list-row">
          <span>
            <strong>{{ skill.name }}</strong>
            <small>{{ skill.category || "general" }} · {{ skill.readiness_status || "ready" }}</small>
          </span>
          <b>{{ skill.offered ? "offered" : "idle" }}</b>
        </div>
      </div>
    </template>

    <template v-else-if="activeView === 'mcp'">
      <div class="page-heading">
        <h3>MCP</h3>
        <p>外部工具协议接入。这里展示 server、transport 和连接状态。</p>
      </div>
      <div class="flat-list">
        <div v-for="server in mcpServers" :key="server.name || server.id" class="list-row">
          <span>
            <strong>{{ server.name || server.id || "mcp-server" }}</strong>
            <small>{{ server.type || server.transport || server.url || "transport unknown" }}</small>
          </span>
          <b>{{ server.status || server.state || "configured" }}</b>
        </div>
        <EmptyBlock v-if="!mcpServers.length" title="没有 MCP Server" description="在 config.json 里配置后会显示在这里。" />
      </div>
    </template>

    <template v-else-if="activeView === 'integrations'">
      <div class="page-heading">
        <h3>平台接入</h3>
        <p>给微信、Telegram、飞书等外部平台预留的接入工作台。具体 token 和 webhook 放到右上角设置。</p>
      </div>
      <div class="integration-list">
        <div v-for="channel in channels" :key="channel.name" class="integration-row">
          <component :is="channel.icon" :size="18" />
          <span>
            <strong>{{ channel.name }}</strong>
            <small>{{ channel.description }}</small>
          </span>
          <b>{{ channel.status }}</b>
        </div>
      </div>
    </template>

    <template v-else-if="activeView === 'cron'">
      <div class="page-heading">
        <h3>定时</h3>
        <p>提醒和定时任务。当前只展示任务状态，后续可以加创建、暂停和删除。</p>
      </div>
      <div class="flat-list">
        <div v-for="task in cronTasks" :key="task.id || task.name" class="list-row">
          <span>
            <strong>{{ task.message || task.name || task.id }}</strong>
            <small>{{ task.schedule || task.interval || "schedule unknown" }}</small>
          </span>
          <b>{{ task.next_run || task.next || "pending" }}</b>
        </div>
        <EmptyBlock v-if="!cronTasks.length" title="暂无定时任务" description="在 TUI 创建提醒后会出现在这里。" />
      </div>
    </template>

    <template v-else>
      <div class="page-heading">
        <h3>审计</h3>
        <p>工具调用与风险确认记录。这里用来排查 Sierra 做过什么。</p>
      </div>
      <div class="audit-table">
        <div v-for="record in safeArray(payload.audit.records)" :key="`${record.timestamp}-${record.tool}`" class="audit-row">
          <span>{{ formatTime(record.timestamp) }}</span>
          <strong>{{ record.tool || record.tool_name || record.name || "tool" }}</strong>
          <b :class="{ good: record.success === true, bad: record.success === false }">
            {{ record.success === false ? "failed" : record.success === true ? "ok" : record.risk || "event" }}
          </b>
        </div>
        <EmptyBlock v-if="!safeArray(payload.audit.records).length" title="暂无审计记录" description="调用工具后会写入这里。" />
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { Bot, Cable, MessageCircle, Search, Send } from "lucide-vue-next";
import { computed, defineComponent, h, ref } from "vue";
import type { DashboardPayload, SessionSummary, ViewId } from "../types";
import { formatTime, formatTimestamp, safeArray } from "../types";

const props = defineProps<{
  activeSessionId: string;
  activeView: Exclude<ViewId, "chat">;
  memoryRecordCount: number;
  payload: DashboardPayload;
  recentSessions: SessionSummary[];
  toolsets: Array<{ name: string; count: number }>;
}>();

defineEmits<{
  (event: "open-session", value: string): void;
}>();

const toolQuery = ref("");
const activeToolset = ref("");

const EmptyBlock = defineComponent({
  props: {
    description: { type: String, required: true },
    title: { type: String, required: true }
  },
  setup(blockProps) {
    return () =>
      h("div", { class: "empty-block" }, [
        h("strong", blockProps.title),
        h("p", blockProps.description)
      ]);
  }
});

const filteredTools = computed(() => {
  const query = toolQuery.value.trim().toLowerCase();
  return safeArray<any>(props.payload.tools.items).filter((tool) => {
    const matchesQuery = !query || `${tool.name} ${tool.toolset}`.toLowerCase().includes(query);
    const matchesToolset = !activeToolset.value || tool.toolset === activeToolset.value;
    return matchesQuery && matchesToolset;
  });
});

const mcpServers = computed(() => {
  const raw = props.payload.mcp?.servers || props.payload.mcp?.items || [];
  if (Array.isArray(raw)) {
    return raw;
  }
  if (raw && typeof raw === "object") {
    return Object.entries(raw).map(([name, value]) => ({ name, ...(value as Record<string, any>) }));
  }
  return [];
});

const cronTasks = computed(() => {
  return safeArray<any>(props.payload.cron?.tasks);
});

const channels = [
  {
    name: "微信",
    status: "规划中",
    description: "个人陪伴提醒、轻量通知、日常对话。",
    icon: MessageCircle
  },
  {
    name: "Telegram",
    status: "规划中",
    description: "跨设备机器人指令、文件转发、快速消息。",
    icon: Send
  },
  {
    name: "飞书",
    status: "规划中",
    description: "团队通知、知识库、审批和工作流事件。",
    icon: Bot
  },
  {
    name: "Webhook",
    status: "预留",
    description: "给其他平台统一接入事件。",
    icon: Cable
  }
];
</script>
