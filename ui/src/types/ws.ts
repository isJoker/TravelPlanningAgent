export type WSEventName =
  | 'session_created'
  | 'node_start'
  | 'node_end'
  | 'tool_start'
  | 'tool_end'
  | 'review_iteration'
  | 'partial_thought'
  | 'task_result'
  | 'error'
  | 'pong'

export interface WSMessage<T = any> {
  event: WSEventName
  data: T
}

export interface SessionCreated { path: string }
export interface NodeStart { node: string; ts: number }
export interface NodeEnd { node: string; duration_ms: number; summary?: string | null }
export interface ToolStart { tool_name: string; args?: Record<string, unknown> }
export interface ToolEnd { tool_name: string; summary?: string | null }
export interface ReviewIteration { iteration: number; passed: boolean; feedback?: string | null }
export interface PartialThought { text: string }
export interface TaskResult {
  result: string
  version: number
  files: { name: string; path: string; url: string; size?: number; mtime?: number }[]
}
export interface ErrorEvent { where?: string; message: string }
