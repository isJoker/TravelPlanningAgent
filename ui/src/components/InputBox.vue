<script setup lang="ts">
import { ref, computed, reactive, nextTick } from 'vue'
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
const textareaRef = ref<HTMLTextAreaElement | null>(null)

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

/**
 * Best-effort parse a quick-pick hint like "5 天大阪亲子游" into form fields.
 * Returns only the fields that could be confidently extracted.
 */
function parseHint(hint: string): Partial<TripRequest> {
  const out: Partial<TripRequest> = {}
  const dayMatch = hint.match(/(\d+)\s*天/)
  if (dayMatch) out.days_num = Number(dayMatch[1])

  const rest = hint.replace(/^\s*\d+\s*天\s*/, '').trim()
  // Themes supported by TripFormInline's <select>; keep in sync with that list.
  const supportedThemes = ['亲子', '蜜月', '美食', '户外', '文化']
  // Extra keywords that may follow the destination but aren't in the dropdown.
  const themeKeywords = [...supportedThemes, '海岛', '深度', '度假']

  let themeIdx = -1
  let matchedTheme = ''
  for (const t of themeKeywords) {
    const i = rest.indexOf(t)
    if (i >= 0 && (themeIdx < 0 || i < themeIdx)) {
      themeIdx = i
      matchedTheme = t
    }
  }

  if (themeIdx > 0) {
    out.destination = rest.slice(0, themeIdx).trim()
    out.travel_theme = supportedThemes.includes(matchedTheme) ? matchedTheme : ''
  } else {
    out.destination = rest.replace(/(之旅|游)$/, '').trim()
  }
  return out
}

/**
 * Apply a quick-pick hint from WelcomeScreen: fill the textarea with the hint
 * text, pre-fill the inline form fields when possible, and focus the input
 * so the user can edit or submit immediately.
 */
async function applyHint(hint: string) {
  text.value = hint
  if (props.showForm) {
    const parsed = parseHint(hint)
    if (parsed.days_num !== undefined) form.days_num = parsed.days_num
    if (parsed.destination) form.destination = parsed.destination
    if (parsed.travel_theme !== undefined) form.travel_theme = parsed.travel_theme
  }
  await nextTick()
  textareaRef.value?.focus()
}

defineExpose({ applyHint })
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
        ref="textareaRef"
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
