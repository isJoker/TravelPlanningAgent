import type { FileItem } from './chat'

export interface TripRequest {
  conversation_name?: string
  bot_user_input?: string
  destination: string
  departure?: string
  days_num: number
  people_num: number
  start_date?: string
  travel_theme?: string
}

export interface TripStartResponse {
  trip_id: string
  thread_id: string
  status: string
  version: number
}

export interface TripVersion {
  version: number
  created_at: string
  pdf_path?: string | null
  md_path?: string | null
}

/** A slim message returned by `GET /api/trip/{tid}/messages`. */
export interface MessageItem {
  id: string
  role: 'user' | 'ai'
  content: string
  version?: number | null
  files: FileItem[]
  timestamp?: number | null
}

export interface MessagesResponse {
  thread_id: string
  messages: MessageItem[]
  /** True when the session_dir on disk no longer exists. */
  expired: boolean
}
