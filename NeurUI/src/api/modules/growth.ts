import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GrowthReflection {
  id: string
  agent_id: string
  content: string
  category?: string
  insights?: string[]
  quality_score?: number
  created_at: string
}

export interface GrowthQuestion {
  id: string
  agent_id: string
  question: string
  context?: string
  answered: boolean
  answer?: string
  created_at: string
}

export interface ProactiveAction {
  id: string
  agent_id: string
  type: string
  description: string
  status: 'pending' | 'completed' | 'skipped'
  created_at: string
}

export interface PersonalityProfile {
  agent_id: string
  traits: Record<string, number>
  style?: string
  tone?: string
  updated_at?: string
}

export interface MotivationState {
  agent_id: string
  level: number
  factors: { name: string; impact: number }[]
  updated_at?: string
}

export interface ConstitutionRule {
  id: string
  agent_id: string
  rule: string
  priority: number
  enabled: boolean
  created_at: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/growth'

/** Get growth reflections for an agent. */
export function getReflections(agentId: string, params?: { page?: number; size?: number }) {
  return api.get<ApiResponse<{ items: GrowthReflection[]; total: number }>>(`${BASE}/reflections`, { params: { ...params, agent_id: agentId } })
}

/** Create a reflection. */
export function createReflection(agentId: string, content: string, category?: string) {
  return api.post<ApiResponse<GrowthReflection>>(`${BASE}/reflections`, { agent_id: agentId, content, category })
}

/** Get growth questions. */
export function getQuestions(agentId: string, params?: { page?: number; size?: number; answered?: boolean }) {
  return api.get<ApiResponse<{ items: GrowthQuestion[]; total: number }>>(`${BASE}/questions`, { params: { ...params, agent_id: agentId } })
}

/** Answer a question. */
export function answerQuestion(questionId: string, answer: string) {
  return api.post<ApiResponse<null>>(`${BASE}/questions/${questionId}/answer`, { answer })
}

/** Get proactive actions. */
export function getProactiveActions(agentId: string, params?: { status?: string }) {
  return api.get<ApiResponse<ProactiveAction[]>>(`${BASE}/proactive`, { params: { ...params, agent_id: agentId } })
}

/** Get motivation state. */
export function getMotivation(agentId: string) {
  return api.get<ApiResponse<MotivationState>>(`${BASE}/motivation`, { params: { agent_id: agentId } })
}

/** Get personality profile. */
export function getPersonality(agentId: string) {
  return api.get<ApiResponse<PersonalityProfile>>(`${BASE}/personality`, { params: { agent_id: agentId } })
}

/** Update personality. */
export function updatePersonality(agentId: string, data: Partial<PersonalityProfile>) {
  return api.put<ApiResponse<PersonalityProfile>>(`${BASE}/personality`, { agent_id: agentId, ...data })
}

/** Get constitution rules. */
export function getConstitution(agentId: string) {
  return api.get<ApiResponse<ConstitutionRule[]>>(`${BASE}/constitution`, { params: { agent_id: agentId } })
}

/** Add a constitution rule. */
export function addConstitutionRule(agentId: string, rule: string, priority?: number) {
  return api.post<ApiResponse<ConstitutionRule>>(`${BASE}/constitution`, { agent_id: agentId, rule, priority })
}

/** Update a constitution rule. */
export function updateConstitutionRule(ruleId: string, data: Partial<ConstitutionRule>) {
  return api.put<ApiResponse<ConstitutionRule>>(`${BASE}/constitution/${ruleId}`, data)
}

/** Delete a constitution rule. */
export function deleteConstitutionRule(ruleId: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/constitution/${ruleId}`)
}
