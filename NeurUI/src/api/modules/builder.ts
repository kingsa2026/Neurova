import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BuilderTemplate {
  id: string
  name: string
  description: string
  personality: string
  system_prompt: string
  tags: string[]
  category: string
}

export interface BuilderAgent {
  agent_id: string
  name: string
  user_id: string
  template_id?: string
  system_prompt: string
  personality: string
  model?: string
  config: Record<string, unknown>
  status: string
  created_at: string
}

export interface BuildAgentRequest {
  name: string
  template_id?: string
  system_prompt?: string
  personality?: string
  model?: string
  config?: Record<string, unknown>
}

export interface ValidateConfigRequest {
  name?: string
  system_prompt?: string
  personality?: string
  config?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/builder'

/** List all predefined personality templates. */
export function getTemplates() {
  return api.get<ApiResponse<{ templates: BuilderTemplate[]; total: number }>>(`${BASE}/templates`)
}

/** Get template details. */
export function getTemplate(templateId: string) {
  return api.get<ApiResponse<BuilderTemplate>>(`${BASE}/templates/${templateId}`)
}

/** Validate agent configuration without creating. */
export function validateConfig(data: ValidateConfigRequest) {
  return api.post<ApiResponse<{ valid: boolean; errors: string[] }>>(`${BASE}/validate`, data)
}

/** Build (create) a new agent. */
export function buildAgent(data: BuildAgentRequest) {
  return api.post<ApiResponse<BuilderAgent>>(`${BASE}/build`, data)
}

/** List built agents for current user. */
export function getBuiltAgents() {
  return api.get<ApiResponse<{ agents: BuilderAgent[]; total: number }>>(`${BASE}/agents`)
}
