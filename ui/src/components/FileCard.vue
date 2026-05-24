<script setup lang="ts">
import { computed } from 'vue'
import type { FileItem } from '@/types/chat'

const props = defineProps<{ file: FileItem }>()
const icon = computed(() => {
  if (props.file.name.endsWith('.pdf')) return '📄'
  if (props.file.name.endsWith('.md')) return '📝'
  return '📦'
})
const sizeText = computed(() => {
  const s = props.file.size
  if (typeof s !== 'number') return ''
  if (s < 1024) return `${s} B`
  if (s < 1024 * 1024) return `${(s / 1024).toFixed(1)} KB`
  return `${(s / 1024 / 1024).toFixed(2)} MB`
})
const href = computed(() => {
  // Use the URL the backend returned, falling back to /api/download with abs path.
  if (props.file.url) return props.file.url
  return `/api/download?path=${encodeURIComponent(props.file.path)}`
})
</script>

<template>
  <a class="file-card" :href="href" target="_blank" rel="noopener">
    <div class="icon">{{ icon }}</div>
    <div>
      <div class="name">{{ file.name }}</div>
      <div class="meta">{{ sizeText }} · 点击下载/预览</div>
    </div>
  </a>
</template>
