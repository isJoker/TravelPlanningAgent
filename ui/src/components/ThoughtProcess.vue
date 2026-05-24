<script setup lang="ts">
import { computed } from 'vue'
import ToolCallCard from './ToolCallCard.vue'
import type { LogItem } from '@/types/chat'

const props = defineProps<{ logs: LogItem[]; running: boolean }>()

const summary = computed(() => {
  const total = props.logs.length
  const tools = props.logs.filter((l) => l.kind === 'tool').length
  const nodes = props.logs.filter((l) => l.kind === 'node').length
  if (props.running) return `思维链运行中… (${total} 步：节点 ${nodes} · 工具 ${tools})`
  if (total === 0) return '无中间步骤'
  return `思维链已完成 (${total} 步：节点 ${nodes} · 工具 ${tools})`
})
</script>

<template>
  <details class="thought" :open="running">
    <summary>
      <span class="arrow">▶</span>
      <span v-if="running" class="spinner" aria-hidden="true" />
      <span>{{ summary }}</span>
    </summary>
    <div class="thought-list">
      <ToolCallCard v-for="log in logs" :key="log.id" :log="log" />
    </div>
  </details>
</template>
