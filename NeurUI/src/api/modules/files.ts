import api from '@/api'
import { request } from '@/api'
import type { ApiResponse, PaginatedData } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FileItem {
  id: string
  name: string
  type?: string
  size?: number
  version?: number
  status?: string
  url?: string
  agent_id?: string
  created_at: string
}

export interface FileVersion {
  version: number
  size?: number
  created_at: string
}

export interface FileListParams {
  page?: number
  page_size?: number
  agent_id?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/files'

/** List files with optional filters. */
export function listFiles(params?: FileListParams) {
  return api.get<ApiResponse<PaginatedData<FileItem>>>(BASE, { params })
}

/** Upload a file (multipart). */
export function uploadFile(formData: FormData) {
  return request.post(`${BASE}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }) as unknown as Promise<ApiResponse<FileItem>>
}

/** Get file content as text. */
export function getFileContent(id: string) {
  return api.get<ApiResponse<string>>(`${BASE}/${id}/content`)
}

/** Get version history for a file. */
export function getFileVersions(id: string) {
  return api.get<ApiResponse<FileVersion[]>>(`${BASE}/${id}/versions`)
}

/** Update file metadata. */
export function updateFile(id: string, data: Partial<FileItem>) {
  return api.put<ApiResponse<FileItem>>(`${BASE}/${id}`, data)
}

/** Delete a file. */
export function deleteFile(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Download a file (returns blob). */
export function downloadFile(id: string) {
  return request.get(`${BASE}/${id}/download`, { responseType: 'blob' }) as unknown as Promise<Blob>
}
