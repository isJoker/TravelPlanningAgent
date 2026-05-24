import { defineStore } from 'pinia'
import { ref } from 'vue'

const LS_KEY = 'tpa.history.v1'

export interface HistoryItem {
  thread_id: string
  title: string
  destination: string
  days_num: number
  last_active: number
  expired?: boolean
}

function loadFromStorage(): HistoryItem[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as HistoryItem[]) : []
  } catch {
    return []
  }
}

function saveToStorage(items: HistoryItem[]): void {
  localStorage.setItem(LS_KEY, JSON.stringify(items.slice(0, 50)))
}

export const useHistoryStore = defineStore('history', () => {
  const items = ref<HistoryItem[]>(loadFromStorage())

  function upsert(it: HistoryItem) {
    const idx = items.value.findIndex((x) => x.thread_id === it.thread_id)
    if (idx >= 0) items.value[idx] = { ...items.value[idx], ...it }
    else items.value.unshift(it)
    items.value.sort((a, b) => b.last_active - a.last_active)
    saveToStorage(items.value)
  }

  function remove(thread_id: string) {
    items.value = items.value.filter((x) => x.thread_id !== thread_id)
    saveToStorage(items.value)
  }

  function markExpired(thread_id: string) {
    const it = items.value.find((x) => x.thread_id === thread_id)
    if (it) {
      it.expired = true
      saveToStorage(items.value)
    }
  }

  return { items, upsert, remove, markExpired }
})
