<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { useChatStore } from '@/stores/chat'
import TripFormInline from './TripFormInline.vue'
import type { TripRequest } from '@/types/trip'

const props = defineProps<{
  /** When true, the inline form is shown; first-turn UX */
  showForm?: boolean
  placeholder?: string
}>()
const emit = defineEmits<{ (e: 'submitted'): void }>()

const chat = useChatStore()
const text = ref('')

const form = reactive<TripRequest>({
  destination: '',
  departure: '上海',
  days_num: 5,
  people_num: 2,
  start_date: '',
  travel_theme: '亲子',
})

const canSend = computed(() => {
  if (chat.status === 'running') return false
  if (props.showForm) {
    return !!form.destination.trim() && form.days_num > 0 && form.people_num > 0
  }
  return text.value.trim().length > 0 && !!chat.threadId
})

async function send() {
  if (!canSend.value) return
  const userText = text.value.trim()

  if (props.showForm) {
    const display = `${userText || ''}\n（目的地：${form.destination} · ${form.days_num}天 · ${form.people_num}人 · ${form.travel_theme || '通用'}）`.trim()
    await chat.startNewTrip(
      {
        ...form,
        bot_user_input: userText || undefined,
      },
      display
    )
  } else {
    await chat.sendRefine(userText)
  }

  text.value = ''
  emit('submitted')
}

function onEnter(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="input-wrap">
    <TripFormInline
      v-if="showForm"
      :model-value="form"
      @update:model-value="(v) => Object.assign(form, v)"
    />
    <div class="input-card">
      <textarea
        v-model="text"
        rows="1"
        :placeholder="placeholder || (showForm ? '描述你的诉求，例如：想带 3 岁小孩，避免长途车程' : '继续调整：例如「把第 3 天换成室内活动」')"
        @keydown="onEnter"
      />
      <button class="send-btn" :disabled="!canSend" @click="send" aria-label="发送">
        ➤
      </button>
    </div>
  </div>
</template>
