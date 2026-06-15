import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CollabSession {
  id: string
  name: string
  description: string
  status: string
  participants?: string[]
  createdAt: string
  completedAt?: string
}

export interface CollabTemplate {
  id: string
  name: string
  description: string
  type: string
  participants?: string[]
}

export interface CreateTemplatePayload {
  name: string
  description: string
  type: string
  participants?: string[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/collaboration'

/** List collaboration history sessions. */
export function listHistory() {
  return api.get<ApiResponse<CollabSession[]>>(`${BASE}/history`)
}

/** List collaboration templates. */
export function listTemplates() {
  return api.get<ApiResponse<CollabTemplate[]>>(`${BASE}/templates`)
}

/** Create a new collaboration template. */
export function createTemplate(data: CreateTemplatePayload) {
  return api.post<ApiResponse<CollabTemplate>>(`${BASE}/templates`, data)
}

/** Update an existing collaboration template. */
export function updateTemplate(id: string, data: CreateTemplatePayload) {
  return api.put<ApiResponse<CollabTemplate>>(`${BASE}/templates/${id}`, data)
}

/** Delete a collaboration template. */
export function deleteTemplate(id: string) {
  return api.delete<ApiResponse<{ success: boolean }>>(`${BASE}/templates/${id}`)
}
