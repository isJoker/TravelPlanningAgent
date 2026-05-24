<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import FileCard from './FileCard.vue'

const chat = useChatStore()
const { files, threadId } = storeToRefs(chat)

function refresh() {
  chat.refreshFiles()
}
</script>

<template>
  <aside class="sidebar-right">
    <div class="sidebar-header">
      <span>📁</span>
      <span>会话产物</span>
      <button v-if="threadId" style="margin-left:auto;color:var(--text-dim);font-size:11.5px;" @click="refresh">
        刷新
      </button>
    </div>
    <div class="sidebar-list">
      <FileCard v-for="f in files" :key="f.path" :file="f" />
      <div v-if="files.length === 0" class="sidebar-item" style="cursor: default; color: var(--text-muted)">
        {{ threadId ? '暂无产物' : '尚未开始任务' }}
      </div>
    </div>
  </aside>
</template>
