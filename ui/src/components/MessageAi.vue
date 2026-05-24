<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import ThoughtProcess from './ThoughtProcess.vue'
import FileCard from './FileCard.vue'
import type { Message } from '@/types/chat'

const props = defineProps<{ msg: Message }>()

marked.setOptions({ gfm: true, breaks: true })

const rendered = computed(() => {
  if (!props.msg.content) {
    return props.msg.status === 'streaming'
      ? '<em style="color:var(--text-muted)">规划中…</em>'
      : ''
  }
  const html = marked.parse(props.msg.content) as string
  return DOMPurify.sanitize(html)
})
</script>

<template>
  <div class="msg-ai">
    <ThoughtProcess
      v-if="msg.logs.length > 0 || msg.status === 'streaming'"
      :logs="msg.logs"
      :running="msg.status === 'streaming'"
    />

    <div class="msg-ai-content" v-html="rendered" />

    <div v-if="msg.files.length" class="msg-ai-files" style="display:flex; flex-wrap:wrap; gap:8px;">
      <FileCard v-for="f in msg.files" :key="f.path" :file="f" />
    </div>

    <div class="msg-meta">
      <span>{{ msg.status === 'streaming' ? '规划中' : msg.status === 'done' ? '完成' : msg.status }}</span>
      <span v-if="msg.version">v{{ msg.version }}</span>
    </div>
  </div>
</template>
