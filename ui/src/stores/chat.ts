import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import { TripWS } from '@/api/ws'
import { createTrip, listFiles, loadMessages, refineTrip } from '@/api/trip'
import type { FileItem, LogItem, Message } from '@/types/chat'
import type { MessageItem, TripRequest } from '@/types/trip'
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

// ---------- per-thread slim message persistence ----------
//
// Strategy: localStorage `tpa.msgs.<thread_id>` holds a *slim* projection of
// settled messages — user texts, AI summaries, and produced files only. The
// noisy process trace (`logs[]`, `partial_thought`, streaming placeholders)
// is intentionally dropped, since those events are only meaningful while a
// run is active. We bound total footprint with an LRU prune keyed off
// `tpa.history.v1`.
const SLIM_KEY_PREFIX = 'tpa.msgs.'
const SLIM_THREAD_LIMIT = 20

interface SlimMessage {
  id: string
  role: 'user' | 'ai' | 'system'
  content: string
  files: FileItem[]
  version?: number
  timestamp: number
  status: Message['status']
}

function slimKey(tid: string): string {
  return SLIM_KEY_PREFIX + tid
}

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

function toSlim(m: Message): SlimMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    files: m.files,
    version: m.version,
    timestamp: m.timestamp,
    status: m.status,
  }
}

function fromSlim(s: SlimMessage): Message {
  return {
    id: s.id,
    role: s.role,
    content: s.content,
    files: s.files || [],
    version: s.version,
    timestamp: s.timestamp,
    // logs are intentionally dropped on persistence; rehydrated messages
    // never show a thought-process panel (MessageAi.vue gates on logs.length
    // || status === 'streaming').
    logs: [],
    status: s.status === 'streaming' || s.status === 'pending' ? 'done' : s.status,
  }
}

function slimFilter(m: Message): boolean {
  if (m.role === 'user') return !!m.content.trim()
  // AI: only persist completed / errored messages — never streaming
  // placeholders, otherwise reload would show a stuck "规划中".
  return m.status === 'done' || m.status === 'error'
}

function loadSlim(tid: string): Message[] {
  try {
    const raw = localStorage.getItem(slimKey(tid))
    if (!raw) return []
    const slim = JSON.parse(raw) as SlimMessage[]
    return slim.map(fromSlim)
  } catch {
    return []
  }
}

function saveSlim(tid: string, msgs: Message[]): void {
  try {
    const slim = msgs.filter(slimFilter).map(toSlim)
    localStorage.setItem(slimKey(tid), JSON.stringify(slim))
    pruneSlimLRU()
  } catch (e) {
    console.warn('[chat] saveSlim failed', e)
  }
}

/**
 * Drop slim caches for threads no longer in the top SLIM_THREAD_LIMIT of the
 * history list. Keeps total localStorage footprint bounded even if the user
 * accumulates many sessions over time.
 */
function pruneSlimLRU(): void {
  try {
    const historyRaw = localStorage.getItem('tpa.history.v1')
    if (!historyRaw) return
    const history = JSON.parse(historyRaw) as { thread_id: string; last_active: number }[]
    const keep = new Set(
      [...history]
        .sort((a, b) => b.last_active - a.last_active)
        .slice(0, SLIM_THREAD_LIMIT)
        .map((h) => h.thread_id)
    )
    const allKeys: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(SLIM_KEY_PREFIX)) allKeys.push(k)
    }
    for (const k of allKeys) {
      const tid = k.slice(SLIM_KEY_PREFIX.length)
      if (!keep.has(tid)) localStorage.removeItem(k)
    }
  } catch {
    /* noop */
  }
}

/**
 * Merge server-authoritative messages with the local slim cache.
 *
 *  - Server provides ordered AI artefacts by version (and `bot_user_input`
 *    as v1 user when checkpoint is alive). We treat it as the source of
 *    truth for AI content/files.
 *  - Local cache supplies refine user texts (which the server does not
 *    persist verbatim) and acts as the offline fallback.
 *
 * Algorithm:
 *  1. If cache is empty, materialise server messages directly.
 *  2. Otherwise, walk cached messages and patch AI versions in-place from
 *     the server map. AI versions present on the server but missing locally
 *     are appended at the end (e.g. another tab refined the same thread).
 */
function mergeMessages(cached: Message[], server: MessageItem[]): Message[] {
  if (cached.length === 0) {
    return server.map(serverToMessage)
  }
  const aiByVersion = new Map<number, MessageItem>()
  for (const sm of server) {
    if (sm.role === 'ai' && sm.version != null) aiByVersion.set(sm.version, sm)
  }

  const merged: Message[] = []
  const localAiVersions = new Set<number>()
  for (const m of cached) {
    if (m.role === 'ai' && m.version != null && aiByVersion.has(m.version)) {
      const sm = aiByVersion.get(m.version)!
      merged.push({
        ...m,
        content: sm.content || m.content,
        files: sm.files?.length ? sm.files : m.files,
        timestamp: sm.timestamp ?? m.timestamp,
        status: 'done',
      })
      localAiVersions.add(m.version)
    } else {
      merged.push(m)
    }
  }

  for (const v of [...aiByVersion.keys()].sort((a, b) => a - b)) {
    if (localAiVersions.has(v)) continue
    merged.push(serverToMessage(aiByVersion.get(v)!))
  }
  return merged
}

function serverToMessage(sm: MessageItem): Message {
  return {
    id: sm.id,
    role: sm.role,
    content: sm.content,
    logs: [],
    files: sm.files || [],
    version: sm.version ?? undefined,
    timestamp: sm.timestamp ?? Date.now(),
    status: 'done',
  }
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const threadId = ref<string | null>(null)
  const status = ref<RunStatus>('idle')
  const files = ref<FileItem[]>([])
  let ws: TripWS | null = null

  // Best-effort cleanup of orphaned slim caches at boot.
  pruneSlimLRU()

  const lastAi = computed<Message | null>(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'ai') return messages.value[i]
    }
    return null
  })

  function persist(): void {
    if (threadId.value) saveSlim(threadId.value, messages.value)
  }

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
      // Also refresh the global file panel and persist the settled thread.
      refreshFiles()
      persist()
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
      persist()
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
    // Persist immediately so the user message survives a refresh even if the
    // first run never reaches task_result.
    persist()
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
    persist()
    try {
      await refineTrip(threadId.value, instruction)
    } catch (e: any) {
      ai.status = 'error'
      ai.content = '**Refine 失败**：' + (e?.message || String(e))
      status.value = 'error'
      persist()
    }
  }

  /**
   * Switch to an existing thread. Three-phase:
   *  1. Render the slim cache from localStorage instantly (offline-friendly).
   *  2. Reconnect WS + refresh the global files panel.
   *  3. Hydrate from `GET /api/trip/{tid}/messages`, merge with cache,
   *     and write the merged result back to localStorage.
   */
  async function selectThread(tid: string) {
    if (threadId.value === tid) return
    threadId.value = tid
    status.value = 'idle'

    const cached = loadSlim(tid)
    messages.value = cached
    files.value = []
    ensureWs(tid)
    refreshFiles()

    try {
      const resp = await loadMessages(tid)
      // Guard against rapid thread switches: discard stale responses.
      if (threadId.value !== tid) return
      if (resp.expired) {
        useHistoryStore().markExpired(tid)
        return
      }
      messages.value = mergeMessages(cached, resp.messages)
      saveSlim(tid, messages.value)
    } catch (e) {
      console.warn('[chat] loadMessages failed', e)
    }
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
