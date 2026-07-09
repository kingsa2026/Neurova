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

export interface StartSessionPayload {
  templateId: string
  participants: string[]
  name: string
  description: string
}

export interface CollabStats {
  sessions: number
  templates: number
  workflows: number
  projects: number
}

export interface CanvasNodeSnapshot {
  id: string
  type: string
  label: string
  icon: string
  position: { x: number; y: number }
  inputs: { id: string; label: string }[]
  outputs: { id: string; label: string }[]
  config: Record<string, unknown>
}

export interface CanvasEdgeSnapshot {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface CanvasSnapshot {
  id?: string
  name: string
  nodes: CanvasNodeSnapshot[]
  edges: CanvasEdgeSnapshot[]
}

export interface SaveCanvasPayload {
  id?: string
  name: string
  nodes: CanvasNodeSnapshot[]
  edges: CanvasEdgeSnapshot[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/collaboration'

/** List collaboration history sessions. */
export function listHistory() {
  return api.get<ApiResponse<CollabSession[]>>(`${BASE}/history`)
}

/** List active collaboration sessions. */
export function listSessions() {
  return api.get<ApiResponse<CollabSession[]>>(`${BASE}/sessions`)
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

/** Start a new collaboration session from a template. */
export function startSession(payload: StartSessionPayload) {
  return api.post<ApiResponse<CollabSession>>(`${BASE}/start`, payload)
}

/** Get collaboration overview stats. */
export function getCollabStats() {
  return api.get<ApiResponse<CollabStats>>(`${BASE}/stats`)
}

/** Save a canvas workflow (create). */
export function saveCanvas(payload: SaveCanvasPayload) {
  return api.post<ApiResponse<CanvasSnapshot>>(`${BASE}/canvas`, payload)
}

/** Run a canvas workflow. */
export function runCanvas(canvasId: string) {
  return api.post<ApiResponse<{ runId: string }>>(`${BASE}/canvas/${canvasId}/run`)
}

/** Get a canvas workflow by id. */
export function getCanvas(canvasId: string) {
  return api.get<ApiResponse<CanvasSnapshot>>(`${BASE}/canvas/${canvasId}`)
}

/** Update an existing canvas workflow. */
export function updateCanvas(canvasId: string, payload: SaveCanvasPayload) {
  return api.put<ApiResponse<CanvasSnapshot>>(`${BASE}/canvas/${canvasId}`, payload)
}
