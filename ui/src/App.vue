<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import HistorySidebar from '@/components/HistorySidebar.vue'
import FilesSidebar from '@/components/FilesSidebar.vue'
import WelcomeScreen from '@/components/WelcomeScreen.vue'
import ChatStream from '@/components/ChatStream.vue'
import InputBox from '@/components/InputBox.vue'

const chat = useChatStore()
const { messages, threadId, status } = storeToRefs(chat)

const inSession = computed(() => threadId.value && messages.value.length > 0)

onMounted(() => {
  // Initial: idle on welcome screen.
})
</script>

<template>
  <div class="app">
    <HistorySidebar />

    <main class="main">
      <header class="topbar">
        <div class="brand">
          <span>✈️</span>
          <span class="title-grad">Travel Planning Agent</span>
          <span style="color:var(--text-muted); font-size:11.5px; margin-left:8px;">v0.3 demo · Mock</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="status-dot" :class="{
            'is-running': status === 'running',
            'is-error': status === 'error',
            'is-ok': status === 'ok',
          }" />
          <span style="font-size:12px;color:var(--text-muted);">
            <template v-if="status === 'running'">运行中</template>
            <template v-else-if="status === 'error'">出错</template>
            <template v-else-if="status === 'ok'">已完成</template>
            <template v-else>空闲</template>
          </span>
          <span v-if="threadId" style="font-size:11px;color:var(--text-muted);">thread_id: {{ threadId }}</span>
        </div>
      </header>

      <template v-if="!inSession">
        <WelcomeScreen />
      </template>
      <template v-else>
        <ChatStream />
        <InputBox :show-form="false" />
      </template>
    </main>

    <FilesSidebar />
  </div>
</template>
