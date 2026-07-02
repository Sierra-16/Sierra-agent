<template>
  <header class="workspace-header">
    <div class="workspace-title">
      <span>{{ subtitle }}</span>
      <h2>{{ title }}</h2>
    </div>

    <div class="header-actions">
      <span class="model-pill" :title="activeModelLabel">{{ activeModelLabel }}</span>
      <span class="ctx-pill" :title="workspace">上下文 {{ usagePercent.toFixed(0) }}%</span>
      <button class="icon-action" type="button" title="打开设置" @click="$emit('open-settings')">
        <Settings2 :size="17" />
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { Settings2 } from "lucide-vue-next";

defineProps<{
  activeModelLabel: string;
  generatedAt?: string;
  subtitle: string;
  title: string;
  usagePercent: number;
  workspace?: string;
}>();

defineEmits<{
  (event: "open-settings"): void;
}>();
</script>
