import type { WSMessage } from '@/types/ws'

type Listener = (e: WSMessage) => void

/** Resolve the absolute WS URL given a thread id. */
function resolveBase(): string {
  const base = import.meta.env.VITE_WS_BASE
  if (base) return base
  // Use the page's host; let Vite/FastAPI handle the rest via proxy.
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}`
}

export class TripWS {
  readonly threadId: string
  private url: string
  private ws: WebSocket | null = null
  private listeners = new Map<string, Set<Listener>>()
  private alive = true
  private reconnectDelay = 1500
  private heartbeatTimer: number | null = null

  constructor(threadId: string) {
    this.threadId = threadId
    this.url = `${resolveBase()}/ws/${encodeURIComponent(threadId)}`
    this.connect()
  }

  private connect(): void {
    try {
      this.ws = new WebSocket(this.url)
    } catch (e) {
      console.warn('[ws] construct failed', e)
      this.scheduleReconnect()
      return
    }
    this.ws.onopen = () => {
      // eslint-disable-next-line no-console
      console.log('[ws] open', this.threadId)
      this.dispatch({ event: 'session_created' as any, data: { _local: true } })
      this.startHeartbeat()
    }
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as WSMessage
        this.dispatch(msg)
      } catch (err) {
        console.warn('[ws] parse error', err, e.data)
      }
    }
    this.ws.onclose = () => {
      this.stopHeartbeat()
      if (this.alive) this.scheduleReconnect()
    }
    this.ws.onerror = (e) => console.warn('[ws] error', e)
  }

  private scheduleReconnect(): void {
    setTimeout(() => {
      if (!this.alive) return
      this.connect()
    }, this.reconnectDelay)
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        try { this.ws.send('ping') } catch { /* noop */ }
      }
    }, 25000)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer != null) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  on(event: string, fn: Listener): () => void {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set())
    this.listeners.get(event)!.add(fn)
    return () => this.listeners.get(event)!.delete(fn)
  }

  private dispatch(msg: WSMessage): void {
    this.listeners.get(msg.event)?.forEach((fn) => fn(msg))
    this.listeners.get('*')?.forEach((fn) => fn(msg))
  }

  close(): void {
    this.alive = false
    this.stopHeartbeat()
    try { this.ws?.close() } catch { /* noop */ }
  }
}
