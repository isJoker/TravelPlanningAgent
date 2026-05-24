export type LogKind = 'tool' | 'node' | 'review' | 'info' | 'success' | 'error'

export interface LogItem {
  /** stable identifier so we can update the same item from start→end. */
  id: string
  kind: LogKind
  title: string
  detail?: string
  args?: Record<string, unknown>
  status?: 'running' | 'done' | 'error'
  duration_ms?: number
  ts: number
}

export interface FileItem {
  name: string
  path: string
  url: string
  size?: number
  mtime?: number
}

export interface Message {
  id: string
  role: 'user' | 'ai' | 'system'
  content: string
  logs: LogItem[]
  files: FileItem[]
  version?: number
  timestamp: number
  status: 'pending' | 'streaming' | 'done' | 'error'
}
