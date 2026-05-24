import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { TripWS } from '@/api/ws'
import { createTrip, listFiles, refineTrip } from '@/api/trip'
import type { FileItem, LogItem, Message } from '@/types/chat'
import type { TripRequest } from '@/types/trip'
import type {
  ErrorEvent,
  NodeEnd, NodeStart,
  PartialThought,
  ReviewIteration,
  TaskResult,
  ToolEnd, ToolStart,
  WSMessage,
} from '@/types/ws'
import { useHistoryStore } from './history'

type RunStatus = 'idle' | 'running' | 'error' | 'ok'

function uid(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
}

function emptyAi(version?: number): Message {
  return {
    id: uid(),
    role: 'ai',
    content: '',
    logs: [],
    files: [],
    version,
    timestamp: Date.now(),
    status: 'streaming',
  }
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const threadId = ref<string | null>(null)
  const status = ref<RunStatus>('idle')
  const files = ref<FileItem[]>([])
  let ws: TripWS | null = null

  const lastAi = computed<Message | null>(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'ai') return messages.value[i]
    }
    return null
  })

  function ensureWs(tid: string) {
    if (ws && ws.threadId === tid) return ws
    if (ws) ws.close()
    ws = new TripWS(tid)
    ws.on('*', handleEvent)
    return ws
  }

  function appendLogToCurrent(log: LogItem) {
    const m = lastAi.value
    if (!m) return
    m.logs.push(log)
  }

  function patchLogTitle(idPrefix: 'tool' | 'node', name: string, patch: Partial<LogItem>) {
    const m = lastAi.value
    if (!m) return
    // Patch the most recent matching running log of the same kind+name.
    for (let i = m.logs.length - 1; i >= 0; i--) {
      const log = m.logs[i]
      if (log.kind === idPrefix && log.title.endsWith(name) && log.status === 'running') {
        Object.assign(log, patch)
        return
      }
    }
    // No running entry found — append a synthetic done one.
    appendLogToCurrent({
      id: `${idPrefix}-${name}-${uid()}`,
      kind: idPrefix,
      title: `${idPrefix === 'tool' ? '🔧 ' : '🟦 '}${name}`,
      status: 'done',
      ts: Date.now(),
      ...patch,
    })
  }

  async function refreshFiles() {
    if (!threadId.value) return
    try {
      files.value = await listFiles(threadId.value)
    } catch (e) {
      console.warn('refresh files failed', e)
    }
  }

  function handleEvent(msg: WSMessage) {
    if (msg.event === 'session_created') {
      // local pseudo-event from ws.ts open handler is also session_created;
      // skip purely local opens (data._local) that have no path.
      const d = msg.data as any
      if (d?._local) return
      appendLogToCurrent({
        id: 'sess-' + uid(),
        kind: 'info',
        title: '📁 会话目录已创建',
        detail: d?.path,
        status: 'done',
        ts: Date.now(),
      })
      return
    }
    if (msg.event === 'tool_start') {
      const d = msg.data as ToolStart
      appendLogToCurrent({
        id: 'tool-' + d.tool_name + '-' + uid(),
        kind: 'tool',
        title: '🔧 ' + d.tool_name,
        args: d.args,
        status: 'running',
        ts: Date.now(),
      })
      return
    }
    if (msg.event === 'tool_end') {
      const d = msg.data as ToolEnd
      patchLogTitle('tool', d.tool_name, {
        status: 'done',
        detail: d.summary || undefined,
      })
      return
    }
    if (msg.event === 'node_start') {
      const d = msg.data as NodeStart
      appendLogToCurrent({
        id: 'node-' + d.node + '-' + uid(),
        kind: 'node',
        title: '🟦 ' + d.node,
        status: 'running',
        ts: Date.now(),
      })
      return
    }
    if (msg.event === 'node_end') {
      const d = msg.data as NodeEnd
      patchLogTitle('node', d.node, {
        status: 'done',
        detail: d.summary || undefined,
        duration_ms: d.duration_ms,
      })
      return
    }
    if (msg.event === 'review_iteration') {
      const d = msg.data as ReviewIteration
      appendLogToCurrent({
        id: 'rev-' + uid(),
        kind: 'review',
        title: `🛡 review #${d.iteration} ${d.passed ? '通过' : '需要重试'}`,
        detail: d.feedback || undefined,
        status: d.passed ? 'done' : 'error',
        ts: Date.now(),
      })
      return
    }
    if (msg.event === 'partial_thought') {
      const d = msg.data as PartialThought
      appendLogToCurrent({
        id: 'pt-' + uid(),
        kind: 'info',
        title: '💭 ' + d.text,
        status: 'done',
        ts: Date.now(),
      })
      return
    }
    if (msg.event === 'task_result') {
      const d = msg.data as TaskResult
      const m = lastAi.value
      if (m) {
        m.content = d.result || ''
        m.files = (d.files || []) as FileItem[]
        m.version = d.version
        m.status = 'done'
      }
      status.value = 'ok'
      // Also refresh the global file panel.
      refreshFiles()
      return
    }
    if (msg.event === 'error') {
      const d = msg.data as ErrorEvent
      appendLogToCurrent({
        id: 'err-' + uid(),
        kind: 'error',
        title: '❌ ' + (d.where || 'error'),
        detail: d.message,
        status: 'error',
        ts: Date.now(),
      })
      const m = lastAi.value
      if (m && m.status !== 'done') {
        m.status = 'error'
        if (!m.content) m.content = `**出错**：${d.message}`
      }
      status.value = 'error'
    }
  }

  async function startNewTrip(req: TripRequest, displayText: string) {
    // Push user message
    messages.value.push({
      id: uid(),
      role: 'user',
      content: displayText,
      logs: [],
      files: [],
      timestamp: Date.now(),
      status: 'done',
    })
    // Push placeholder AI
    const ai = emptyAi(1)
    messages.value.push(ai)
    status.value = 'running'

    const resp = await createTrip(req)
    threadId.value = resp.thread_id
    ensureWs(resp.thread_id)

    // Track in history sidebar
    const history = useHistoryStore()
    history.upsert({
      thread_id: resp.thread_id,
      title: req.bot_user_input?.trim() || `${req.destination} ${req.days_num}天`,
      destination: req.destination,
      days_num: req.days_num,
      last_active: Date.now(),
    })
  }

  async function sendRefine(instruction: string) {
    if (!threadId.value) return
    messages.value.push({
      id: uid(),
      role: 'user',
      content: instruction,
      logs: [],
      files: [],
      timestamp: Date.now(),
      status: 'done',
    })
    const ai = emptyAi()
    messages.value.push(ai)
    status.value = 'running'

    ensureWs(threadId.value)
    try {
      await refineTrip(threadId.value, instruction)
    } catch (e: any) {
      ai.status = 'error'
      ai.content = '**Refine 失败**：' + (e?.message || String(e))
      status.value = 'error'
    }
  }

  function selectThread(tid: string) {
    if (threadId.value === tid) return
    threadId.value = tid
    messages.value = []
    files.value = []
    ensureWs(tid)
    refreshFiles()
  }

  function newSession() {
    if (ws) { ws.close(); ws = null }
    threadId.value = null
    messages.value = []
    files.value = []
    status.value = 'idle'
  }

  return {
    messages, threadId, status, files,
    startNewTrip, sendRefine, selectThread, newSession, refreshFiles,
  }
})
