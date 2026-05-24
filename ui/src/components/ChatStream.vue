<script setup lang="ts">
import { nextTick, watch, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import MessageUser from './MessageUser.vue'
import MessageAi from './MessageAi.vue'

const chat = useChatStore()
const { messages } = storeToRefs(chat)

const scrollEl = ref<HTMLDivElement | null>(null)

watch(
  () => messages.value.map((m) => m.logs.length + (m.content ? 1 : 0) + (m.files.length || 0)),
  async () => {
    await nextTick()
    if (scrollEl.value) {
      scrollEl.value.scrollTop = scrollEl.value.scrollHeight
    }
  },
  { deep: true, flush: 'post' }
)
</script>

<template>
  <div ref="scrollEl" class="chat-stream">
    <template v-for="m in messages" :key="m.id">
      <MessageUser v-if="m.role === 'user'" :msg="m" />
      <MessageAi v-else :msg="m" />
    </template>
    <div v-if="messages.length === 0" class="empty-hint">
      会话已切换 — 在下方输入指令即可继续。
    </div>
  </div>
</template>
