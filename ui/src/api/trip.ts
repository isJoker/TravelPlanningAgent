import { http } from './http'
import type { FileItem } from '@/types/chat'
import type {
  MessagesResponse,
  TripRequest,
  TripStartResponse,
  TripVersion,
} from '@/types/trip'

export async function createTrip(req: TripRequest): Promise<TripStartResponse> {
  const { data } = await http.post<TripStartResponse>('/api/trip', req)
  return data
}

export async function refineTrip(threadId: string, instruction: string): Promise<TripStartResponse> {
  const { data } = await http.post<TripStartResponse>(`/api/trip/${encodeURIComponent(threadId)}/refine`, {
    instruction,
  })
  return data
}

export async function listVersions(threadId: string): Promise<TripVersion[]> {
  const { data } = await http.get<{ versions: TripVersion[] }>(
    `/api/trip/${encodeURIComponent(threadId)}/versions`
  )
  return data.versions
}

export async function listFiles(threadId: string): Promise<FileItem[]> {
  const { data } = await http.get<{ files: FileItem[] }>('/api/files', { params: { thread_id: threadId } })
  return data.files
}

/**
 * Fetch the slim message thread (server-side reconstruction) for a
 * conversation. Combine with the per-thread localStorage cache to fill in
 * refine instruction texts, which the backend doesn't persist verbatim.
 */
export async function loadMessages(threadId: string): Promise<MessagesResponse> {
  const { data } = await http.get<MessagesResponse>(
    `/api/trip/${encodeURIComponent(threadId)}/messages`
  )
  return data
}

export function downloadUrl(absPath: string): string {
  return `${import.meta.env.VITE_API_BASE || ''}/api/download?path=${encodeURIComponent(absPath)}`
}
