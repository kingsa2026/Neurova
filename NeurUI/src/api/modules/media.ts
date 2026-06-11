import api from '@/api'
import { request } from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MediaItem {
  id: string
  filename: string
  mime_type: string
  size: number
  agent_id?: string
  tags?: string[]
  metadata?: Record<string, unknown>
  url?: string
  created_at: string
}

export interface MediaListResult {
  items: MediaItem[]
  total: number
  page: number
  size: number
}

export interface MediaStats {
  total_files: number
  total_size_bytes: number
  by_type: { mime_prefix: string; count: number; size_bytes: number }[]
}

export interface MediaConfig {
  max_file_size: number
  allowed_types: string[]
  storage_backend: string
  quota_bytes: number
  used_bytes: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/media'

/** Upload/save a media file (multipart). */
export function saveMedia(file: File, agentId?: string, tags?: string[]) {
  const formData = new FormData()
  formData.append('file', file)
  if (agentId) formData.append('agent_id', agentId)
  if (tags) formData.append('tags', JSON.stringify(tags))
  return request.post(`${BASE}/save`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }) as unknown as Promise<ApiResponse<MediaItem>>
}

/** Get a media file (returns binary). */
export function getMedia(id: string) {
  return request.get(`${BASE}/${id}`, { responseType: 'blob' }) as unknown as Promise<Blob>
}

/** List media files. */
export function listMedia(params?: { page?: number; size?: number; agent_id?: string; mime_type?: string; search?: string }) {
  return api.get<ApiResponse<MediaListResult>>(`${BASE}/list`, { params })
}

/** Get media metadata (no binary). */
export function getMediaInfo(id: string) {
  return api.get<ApiResponse<MediaItem>>(`${BASE}/${id}/info`)
}

/** Download a media file (returns binary with content-disposition). */
export function downloadMedia(id: string) {
  return request.get(`${BASE}/${id}/download`, { responseType: 'blob' }) as unknown as Promise<Blob>
}

/** Delete a media file. */
export function deleteMedia(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Batch delete media files. */
export function batchDeleteMedia(ids: string[]) {
  return api.post<ApiResponse<{ deleted: number }>>(`${BASE}/batch-delete`, { ids })
}

/** Get media statistics. */
export function getMediaStats(params?: { agent_id?: string }) {
  return api.get<ApiResponse<MediaStats>>(`${BASE}/stats`, { params })
}

/** Get media storage configuration. */
export function getMediaConfig() {
  return api.get<ApiResponse<MediaConfig>>(`${BASE}/config`)
}

/** Update media storage configuration. */
export function updateMediaConfig(data: Partial<MediaConfig>) {
  return api.put<ApiResponse<MediaConfig>>(`${BASE}/config`, data)
}
