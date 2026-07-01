<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="open" class="settings-overlay" @keydown.esc="$emit('close')">
        <button class="settings-backdrop" type="button" aria-label="关闭设置" @click="$emit('close')"></button>
        <aside class="settings-drawer" role="dialog" aria-modal="true" aria-label="Sierra 设置">
          <header class="settings-header">
            <div>
              <span>Settings</span>
              <h2>Sierra 控制中心</h2>
            </div>
            <button class="icon-action" type="button" title="关闭" @click="$emit('close')">
              <X :size="18" />
            </button>
          </header>

          <div class="settings-split">
            <nav class="settings-nav" aria-label="Settings sections">
              <button
                v-for="section in sections"
                :key="section.id"
                :class="{ active: activeSection === section.id }"
                type="button"
                @click="activeSection = section.id"
              >
                <component :is="section.icon" :size="16" />
                <span>{{ section.label }}</span>
              </button>
            </nav>

            <main class="settings-content">
              <section v-if="activeSection === 'model'" class="settings-section">
                <SectionTitle title="模型" description="查看已配置模型，并直接切换当前对话使用的模型。" />
                <ListRow title="当前模型" :description="activeModelLabel" />
                <button
                  v-for="model in models"
                  :key="model.key"
                  class="settings-row interactive"
                  type="button"
                  :disabled="model.active"
                  @click="emitCommand({ command: 'model', key: model.key, text: `/model ${model.key}` })"
                >
                  <span>
                    <strong>{{ model.key }}</strong>
                    <small>{{ model.name }}</small>
                  </span>
                  <b>{{ model.active ? "active" : "switch" }}</b>
                </button>
              </section>

              <section v-else-if="activeSection === 'safety'" class="settings-section">
                <SectionTitle title="安全" description="Web 和 TUI 使用同一套权限策略：高风险操作会请求确认。" />
                <ListRow title="只读工具" description="读取、搜索、列目录等操作默认可直接运行。" meta="auto" />
                <ListRow title="写入 / 删除 / 终端" description="需要你确认后才会继续执行。" meta="confirm" />
                <button class="settings-row interactive" type="button" @click="emitCommand('/audit')">
                  <span>
                    <strong>查看审计</strong>
                    <small>最近工具调用与权限记录</small>
                  </span>
                  <b>open</b>
                </button>
              </section>

              <section v-else-if="activeSection === 'tools'" class="settings-section">
                <SectionTitle title="工具" description="当前工具注册表和按工具集分组的能力概览。" />
                <ListRow title="总数" :description="String(payload?.tools.total || 0)" />
                <ListRow title="直接暴露" :description="String(payload?.tools.direct || 0)" />
                <ListRow title="延迟搜索" :description="payload?.tools.tool_search_active ? '已启用' : '未启用'" />
                <ListRow
                  v-for="item in toolsets"
                  :key="item.name"
                  :title="item.name"
                  :description="`${item.count} 个工具`"
                />
              </section>

              <section v-else-if="activeSection === 'skills'" class="settings-section">
                <SectionTitle title="Skills" description="技能索引、使用统计和重新加载入口。" />
                <div class="settings-actions">
                  <button type="button" @click="emitCommand('/skills')">查看技能</button>
                  <button type="button" @click="emitCommand('/skills-reload')">重新加载</button>
                  <button type="button" @click="emitCommand('/skills-stats')">使用统计</button>
                </div>
                <ListRow title="总数" :description="String(payload?.skills.count || 0)" />
                <ListRow
                  v-for="skill in skills"
                  :key="skill.name"
                  :title="skill.name"
                  :description="`${skill.category || 'general'} · ${skill.readiness_status || 'ready'}`"
                  :meta="skill.offered ? 'offered' : ''"
                />
              </section>

              <section v-else-if="activeSection === 'memory'" class="settings-section">
                <SectionTitle title="记忆" description="搜索向量记忆，查看记忆 Provider 状态，或清理当前工作区记忆。" />
                <div class="settings-form">
                  <input v-model="memoryQuery" type="text" placeholder="搜索记忆..." />
                  <button type="button" @click="searchMemory">搜索</button>
                </div>
                <div class="settings-form">
                  <input v-model="forgetId" type="text" placeholder="记忆 ID" />
                  <button type="button" @click="forgetMemory">删除</button>
                  <button type="button" class="danger" @click="clearMemory">清空</button>
                </div>
                <ListRow
                  v-for="provider in memoryProviders"
                  :key="provider.name"
                  :title="provider.name || 'provider'"
                  :description="provider.available === false ? provider.error || '不可用' : providerDescription(provider)"
                  :meta="provider.available === false ? 'off' : 'ready'"
                />
              </section>

              <section v-else-if="activeSection === 'task'" class="settings-section">
                <SectionTitle title="任务" description="查看当前计划，恢复中断任务，或放弃当前任务。" />
                <ListRow
                  v-if="currentTask"
                  :title="currentTask.objective || currentTask.id || '当前任务'"
                  :description="currentTask.status || 'unknown'"
                  :meta="taskProgress"
                />
                <ListRow v-else title="当前没有任务" description="Sierra 创建计划后会显示在这里。" />
                <div class="settings-actions">
                  <button type="button" @click="emitCommand('/task')">查看任务</button>
                  <button v-if="recoveryTask" type="button" @click="emitCommand({ command: 'task_resume', id: recoveryTask.id })">
                    恢复任务
                  </button>
                  <button v-if="currentTask" type="button" class="danger" @click="abandonTask">
                    放弃任务
                  </button>
                </div>
              </section>

              <section v-else-if="activeSection === 'integrations'" class="settings-section">
                <SectionTitle title="平台接入" description="预留多平台消息入口，后续可接 webhook、token 和消息路由。" />
                <ListRow title="微信" description="未配置 webhook / token" meta="planned" />
                <ListRow title="Telegram" description="未配置 bot token" meta="planned" />
                <ListRow title="飞书" description="未配置 app id / secret" meta="planned" />
                <ListRow title="Webhook" description="预留统一事件入口" meta="ready slot" />
              </section>

              <section v-else-if="activeSection === 'mcp'" class="settings-section">
                <SectionTitle title="MCP" description="外部 MCP Server 与工具协议状态。" />
                <div class="settings-actions">
                  <button type="button" @click="emitCommand('/mcp')">刷新状态</button>
                </div>
                <ListRow
                  v-for="server in mcpServers"
                  :key="server.name || server.id"
                  :title="server.name || server.id || 'mcp-server'"
                  :description="server.type || server.transport || server.url || 'transport unknown'"
                  :meta="server.status || server.state || (server.running ? 'running' : 'configured')"
                />
                <ListRow v-if="!mcpServers.length" title="没有 MCP Server" description="在 config.json 的 mcpServers 中配置。" />
              </section>

              <section v-else-if="activeSection === 'cron'" class="settings-section">
                <SectionTitle title="定时" description="创建和删除定时提示，Web 与 TUI 共用同一份任务存储。" />
                <div class="settings-form">
                  <input v-model.number="cronMinutes" type="number" min="1" placeholder="分钟" />
                  <input v-model="cronPrompt" type="text" placeholder="提醒内容" />
                  <button type="button" @click="addCron">创建</button>
                </div>
                <button
                  v-for="task in cronTasks"
                  :key="task.id || task.name"
                  class="settings-row interactive"
                  type="button"
                  @click="removeCron(task)"
                >
                  <span>
                    <strong>{{ task.prompt || task.message || task.name || task.id }}</strong>
                    <small>every {{ task.interval_minutes || task.interval || "?" }} min · next {{ task.next_run_at || task.next || "pending" }}</small>
                  </span>
                  <b>delete</b>
                </button>
                <ListRow v-if="!cronTasks.length" title="暂无定时任务" description="创建提醒后会显示在这里。" />
              </section>

              <section v-else-if="activeSection === 'audit'" class="settings-section">
                <SectionTitle title="审计" description="最近工具调用和安全记录。" />
                <div class="settings-actions">
                  <button type="button" @click="emitCommand('/audit')">查看完整记录</button>
                </div>
                <ListRow
                  v-for="record in auditRecords"
                  :key="`${record.timestamp}-${record.tool || record.name}`"
                  :title="record.tool || record.tool_name || record.name || 'tool'"
                  :description="record.timestamp || 'unknown time'"
                  :meta="record.success === false ? 'failed' : record.success === true ? 'ok' : record.risk || 'event'"
                />
                <ListRow v-if="!auditRecords.length" title="暂无审计记录" description="调用工具后会显示。" />
              </section>

              <section v-else class="settings-section">
                <SectionTitle title="关于" description="Sierra Web Dashboard" />
                <ListRow title="版本" description="0.1.0" />
              </section>
            </main>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import {
  BrainCircuit,
  CalendarClock,
  Database,
  KeyRound,
  Network,
  ScrollText,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  WandSparkles,
  Wrench,
  X
} from "lucide-vue-next";
import { computed, defineComponent, h, ref } from "vue";
import type { DashboardPayload } from "../types";

type SettingsSection =
  | "model"
  | "safety"
  | "tools"
  | "skills"
  | "memory"
  | "task"
  | "integrations"
  | "mcp"
  | "cron"
  | "audit"
  | "about";

const props = defineProps<{
  activeModelLabel: string;
  open: boolean;
  payload: DashboardPayload | null;
  usagePercent: number;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "run-command", value: string | Record<string, any>): void;
}>();

const activeSection = ref<SettingsSection>("model");
const cronMinutes = ref(60);
const cronPrompt = ref("");
const memoryQuery = ref("");
const forgetId = ref("");

const sections = [
  { id: "model", label: "模型", icon: SlidersHorizontal },
  { id: "safety", label: "安全", icon: ShieldCheck },
  { id: "tools", label: "工具", icon: Wrench },
  { id: "skills", label: "Skills", icon: WandSparkles },
  { id: "memory", label: "记忆", icon: Database },
  { id: "task", label: "任务", icon: BrainCircuit },
  { id: "integrations", label: "平台", icon: KeyRound },
  { id: "mcp", label: "MCP", icon: Network },
  { id: "cron", label: "定时", icon: CalendarClock },
  { id: "audit", label: "审计", icon: ScrollText },
  { id: "about", label: "关于", icon: Settings2 }
] as const;

const models = computed(() => {
  return Array.isArray(props.payload?.identity.models) ? props.payload?.identity.models : [];
});

const mcpServers = computed(() => {
  const raw = props.payload?.mcp?.servers || props.payload?.mcp?.items || [];
  if (Array.isArray(raw)) {
    return raw;
  }
  if (raw && typeof raw === "object") {
    return Object.entries(raw).map(([name, value]) => ({ name, ...(value as Record<string, any>) }));
  }
  return [];
});

const toolsets = computed(() => {
  const raw = props.payload?.tools?.toolsets || {};
  return Object.entries(raw)
    .map(([name, count]) => ({ name, count: Number(count) }))
    .sort((a, b) => b.count - a.count);
});

const skills = computed(() => {
  return Array.isArray(props.payload?.skills?.items) ? props.payload?.skills?.items : [];
});

const memoryProviders = computed(() => {
  return Array.isArray(props.payload?.memory?.providers) ? props.payload?.memory?.providers : [];
});

const currentTask = computed(() => props.payload?.tasks?.current || null);
const recoveryTask = computed(() => props.payload?.tasks?.recovery || null);

const taskProgress = computed(() => {
  const steps = Array.isArray(currentTask.value?.steps) ? currentTask.value.steps : [];
  if (!steps.length) {
    return currentTask.value?.status || "";
  }
  const done = steps.filter((step: any) => step.status === "completed").length;
  return `${done}/${steps.length}`;
});

const cronTasks = computed(() => {
  return Array.isArray(props.payload?.cron?.tasks) ? props.payload?.cron?.tasks : [];
});

const auditRecords = computed(() => {
  return Array.isArray(props.payload?.audit?.records) ? props.payload?.audit?.records : [];
});

function emitCommand(value: string | Record<string, any>) {
  emit("run-command", value);
}

function addCron() {
  const prompt = cronPrompt.value.trim();
  if (!prompt) {
    return;
  }
  emitCommand({
    command: "cron_add",
    interval_minutes: Number(cronMinutes.value || 60),
    prompt,
    text: `/cron-add ${Number(cronMinutes.value || 60)} ${prompt}`
  });
  cronPrompt.value = "";
}

function removeCron(task: Record<string, any>) {
  const id = String(task.id || "");
  if (!id) {
    return;
  }
  if (window.confirm("确认删除这个定时提示吗？")) {
    emitCommand({ command: "cron_remove", id, confirmed: true, text: `/cron-remove ${id}` });
  }
}

function searchMemory() {
  const query = memoryQuery.value.trim();
  if (!query) {
    return;
  }
  emitCommand({ command: "memory_search", query, text: `/memory-search ${query}` });
}

function forgetMemory() {
  const id = forgetId.value.trim();
  if (!id) {
    return;
  }
  if (window.confirm(`确认删除向量记忆 #${id} 吗？`)) {
    emitCommand({ command: "memory_forget", id, confirmed: true, text: `/memory-forget ${id}` });
  }
}

function clearMemory() {
  if (window.confirm("确认清空当前工作区全部向量记忆吗？")) {
    emitCommand({ command: "memory_clear", confirmed: true, text: "/memory-clear" });
  }
}

function abandonTask() {
  if (window.confirm("确认放弃当前任务吗？")) {
    emitCommand({ command: "task_abandon", confirmed: true, text: "/task-cancel" });
  }
}

function providerDescription(provider: Record<string, any>) {
  if (provider.name === "local_vector") {
    return `${provider.records || 0} 条 · ${provider.embedding_model || "embedding"}`;
  }
  if (provider.name === "markdown") {
    return `MEMORY ${provider.memory_entries || 0} 条 · USER ${provider.user_entries || 0} 条`;
  }
  return "ready";
}

const SectionTitle = defineComponent({
  props: {
    description: { type: String, required: true },
    title: { type: String, required: true }
  },
  setup(blockProps) {
    return () =>
      h("div", { class: "section-title-block" }, [
        h("h3", blockProps.title),
        h("p", blockProps.description)
      ]);
  }
});

const ListRow = defineComponent({
  props: {
    description: { type: String, required: true },
    meta: { type: String, default: "" },
    title: { type: String, required: true }
  },
  setup(rowProps) {
    return () =>
      h("div", { class: "settings-row" }, [
        h("span", [h("strong", rowProps.title), h("small", rowProps.description)]),
        rowProps.meta ? h("b", rowProps.meta) : null
      ]);
  }
});
</script>
