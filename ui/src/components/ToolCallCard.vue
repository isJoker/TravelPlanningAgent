<script setup lang="ts">
import type { LogItem } from '@/types/chat'

defineProps<{ log: LogItem }>()
</script>

<template>
  <div
    class="call-card"
    :class="{
      'is-tool': log.kind === 'tool',
      'is-node': log.kind === 'node',
      'is-error': log.kind === 'error',
      'is-review': log.kind === 'review',
    }"
  >
    <span v-if="log.status === 'running'" class="spinner" aria-hidden="true" />
    <span v-else class="badge">{{ log.kind.toUpperCase() }}</span>
    <span class="name">{{ log.title }}</span>
    <span v-if="log.detail" class="summary">— {{ log.detail }}</span>
    <span v-if="typeof log.duration_ms === 'number'" class="duration">{{ Math.round(log.duration_ms) }} ms</span>
  </div>
</template>
