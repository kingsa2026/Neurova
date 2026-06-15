import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Sandbox {
  id: string
  name?: string
  status?: string
  image?: string
  steps_count?: number
  created_at?: string
}

export interface CreateSandboxPayload {
  name?: string
  image?: string
  timeout?: number
}

export interface ExecutePayload {
  command: string
  language?: string
}

export interface ExecuteResponse {
  output?: string
  result?: string
  [k: string]: unknown
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/sandbox'

/** List all sandboxes. */
export function listSandboxes() {
  return api.get<Sandbox[]>(BASE)
}

/** Get details for a single sandbox. */
export function getSandbox(id: string) {
  return api.get<Sandbox>(`${BASE}/${id}`)
}

/** Create and start a new sandbox. */
export function createSandbox(data: CreateSandboxPayload) {
  return api.post<Sandbox>(`${BASE}/start`, data)
}

/** Execute a command in a sandbox. */
export function executeInSandbox(id: string, data: ExecutePayload) {
  return api.post<ExecuteResponse>(`${BASE}/${id}/execute`, data)
}

/** Commit the current sandbox state. */
export function commitSandbox(id: string) {
  return api.post<null>(`${BASE}/${id}/commit`)
}

/** Delete a sandbox. */
export function deleteSandbox(id: string) {
  return api.delete<null>(`${BASE}/${id}`)
}
