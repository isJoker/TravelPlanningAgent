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
