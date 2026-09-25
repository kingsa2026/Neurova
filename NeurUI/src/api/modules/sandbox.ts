import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Sandbox {
  id: string
  name?: string
  status?: string
  image?: string
  language?: string
  timeout?: number
  steps_count?: number
  created_at?: string
  updated_at?: string
  agent_id?: string | null
  topic?: string | null
}

export interface CreateSandboxPayload {
  name?: string
  image?: string
  timeout?: number
  language?: string
  // 'auto'：Docker 可用则容器、否则平台后端；'docker'：强制容器（不可用即报错，不静默降级）
  backend?: 'auto' | 'docker'
}

export interface ExecutePayload {
  command: string
  language?: string
}

export interface ExecuteResponse {
  output?: string
  stdout?: string
  stderr?: string
  exit_code?: number
  /** 实际执行后端（'docker' / 'bubblewrap' / 'seatbelt' / 'process' …） */
  backend?: string
  /** 是否真隔离：false = 平台无内核隔离，已如实降级执行 */
  enforced?: boolean
  timed_out?: boolean
  duration_ms?: number
  steps_count?: number
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
