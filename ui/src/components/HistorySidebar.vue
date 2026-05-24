<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useHistoryStore } from '@/stores/history'
import { useChatStore } from '@/stores/chat'

const history = useHistoryStore()
const chat = useChatStore()
const { items } = storeToRefs(history)

function onPick(tid: string) {
  chat.selectThread(tid)
}
function onNew() {
  chat.newSession()
}
</script>

<template>
  <aside class="sidebar-left">
    <div class="sidebar-header">
      <span>📚</span>
      <span>历史会话</span>
    </div>
    <div class="sidebar-list">
      <div
        v-for="it in items"
        :key="it.thread_id"
        class="sidebar-item"
        :class="{ 'is-active': chat.threadId === it.thread_id }"
        @click="onPick(it.thread_id)"
      >
        <div class="title">{{ it.title }}</div>
        <div class="sub">
          {{ it.destination }} · {{ it.days_num }}天
          <span v-if="it.expired" style="color: var(--warn)"> · 已过期</span>
        </div>
      </div>
      <div v-if="items.length === 0" class="sidebar-item" style="cursor: default; color: var(--text-muted)">
        暂无历史
      </div>
    </div>
    <button class="sidebar-action" @click="onNew">+ 新建会话</button>
  </aside>
</template>
