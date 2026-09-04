import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types — 与后端 neurova/api/endpoints/metacognition_api.py 逐字对齐
// ---------------------------------------------------------------------------

export interface MetacognitionEntry {
  id: string
  agent_id?: string
  type: 'self_assessment' | 'strategy' | 'monitoring' | 'planning' | string
  content: string
  context?: string
  confidence?: number
  metadata?: Record<string, unknown>
  created_at: string
}

export interface MetacognitionCreatePayload {
  type: string
  content: string
  context?: string
  confidence?: number
}

export interface MetacognitionStats {
  total_entries: number
  by_type: { type: string; count: number }[]
  avg_confidence: number
  recent_trend: { date: string; count: number }[]
}

/** 认知负荷真状态（B 状态机写穿透） */
export interface CognitiveLoadState {
  load_level: 'low' | 'moderate' | 'high' | 'overload' | string
  load_score: number
  active_tasks: number
  memory_usage: number
  response_time_ms: number
  error_rate: number
  factors: { tasks: number; memory: number; response: number; error: number }
  created_at: string | null
}

/** 反思时间线条目 */
export interface ReflectionHistoryItem {
  created_at: string
  confidence: number
  trigger: string
  summary: string
}

/** 结构化教训（洞察编译器产出，source=template 零 LLM） */
export interface StructuredLesson {
  subject: string
  operator: 'drift' | 'contrast' | 'sequence' | 'calibration' | 'budget' | string
  condition: string
  finding: string
  recommendation: string
  text: string
  evidence: Record<string, number>
  source: 'template' | 'llm' | string
  confidence: number
}

export interface ReflectReport {
  trigger: string
  lessons: StructuredLesson[]
  observations: string[]
  confidence: number
  summary: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/metacognition'

/** List metacognition entries (paged, optional type filter). */
export function getMetacognitionEntries(agentId: string, params?: { page?: number; size?: number; type?: string }) {
  return api.get<ApiResponse<{ items: MetacognitionEntry[]; total: number; page: number; size: number }>>(
    `${BASE}/${agentId}/metacognition`,
    { params },
  )
}

/** Create a metacognition entry. */
export function createMetacognition(agentId: string, data: MetacognitionCreatePayload) {
  return api.post<ApiResponse<MetacognitionEntry>>(`${BASE}/${agentId}/metacognition`, data)
}

/** Get metacognition statistics. */
export function getMetacognitionStats(agentId: string) {
  return api.get<ApiResponse<MetacognitionStats>>(`${BASE}/${agentId}/metacognition/stats`)
}

/** Get cognitive load state (real-time, written through by chat pipeline). */
export function getCognitiveState(agentId: string) {
  return api.get<ApiResponse<CognitiveLoadState>>(`${BASE}/${agentId}/metacognition/state`)
}

/** Get reflection report timeline. */
export function getReflectionHistory(agentId: string, limit = 20) {
  return api.get<ApiResponse<{ items: ReflectionHistoryItem[]; total: number }>>(
    `${BASE}/${agentId}/metacognition/history`,
    { params: { limit } },
  )
}

/** Get structured lessons (insight compiler output, source=template). */
export function getLessons(agentId: string, limit = 20) {
  return api.get<ApiResponse<{ items: StructuredLesson[]; total: number }>>(
    `${BASE}/${agentId}/metacognition/lessons`,
    { params: { limit } },
  )
}

/** Manually trigger a deterministic reflection (insight compiler, zero LLM). */
export function triggerReflection(agentId: string) {
  return api.post<ApiResponse<ReflectReport>>(`${BASE}/${agentId}/metacognition/reflect`)
}
