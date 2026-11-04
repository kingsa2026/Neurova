import api from '@/api'
import type { ApiResponse } from '@/types/response'

// 契约与 neurova/api/endpoints/build_mode.py 对齐（N0）

export interface BuildQuestionOption {
  label: string
  description?: string
  recommended?: boolean
}

export interface BuildQuestion {
  id: string
  question: string
  kind: 'choice' | 'multi' | 'text' | 'secret' | 'confirm'
  options: BuildQuestionOption[]
  multi: boolean
  allow_custom: boolean
  why: string
  impact: string
  required: boolean
  secret_key: string
  timeout_seconds: number
}

export interface BuildAnswer {
  id: string
  selected: string[]
  custom: string
  secret_value?: string
}

export interface BuildRound {
  questions: BuildQuestion[]
  answers: BuildAnswer[]
  supplement?: string
}

export interface BuildInteraction {
  interaction_id: string
  build_session_id?: string
  question: BuildQuestion
  status: 'pending' | 'answered'
  answer: Record<string, unknown> | null
  created_at: number
  answered_at: number
}

export interface BuildSession {
  session_id: string
  request: string
  agent_id: string
  user_id: string
  target_kind: string
  target_id: string
  status: string
  checklist: Record<string, boolean>
  rounds: BuildRound[]
  build_plan: Record<string, unknown>
  interactions: BuildInteraction[]
  batch_id: string
  approved_by: string
  approved_at: number
  created_at: number
  updated_at: number
  error: string
}

const BASE = '/build'

export function startBuildSession(
  agentId: string,
  request: string,
  targetKind = '',
  targetId = '',
) {
  return api.post<ApiResponse<{ session: BuildSession }>>(`${BASE}/sessions`, {
    agent_id: agentId,
    request,
    target_kind: targetKind,
    target_id: targetId,
  })
}

export function getBuildSession(sessionId: string) {
  return api.get<ApiResponse<{ session: BuildSession }>>(`${BASE}/sessions/${sessionId}`)
}

export function submitBuildAnswers(
  sessionId: string,
  answers: BuildAnswer[],
  supplement = '',
) {
  return api.post<ApiResponse<{ session: BuildSession }>>(
    `${BASE}/sessions/${sessionId}/answers`,
    { answers, supplement },
  )
}

export function approveBuildSession(sessionId: string, note = '') {
  return api.post<ApiResponse<{ session: BuildSession }>>(
    `${BASE}/sessions/${sessionId}/approve`,
    { note },
  )
}

export function answerBuildInteraction(
  sessionId: string,
  interactionId: string,
  answer: BuildAnswer,
) {
  return api.post<ApiResponse<{ session: BuildSession; interaction_id: string }>>(
    `${BASE}/sessions/${sessionId}/interactions/${interactionId}/answer`,
    answer,
  )
}

export function cancelBuildSession(sessionId: string) {
  return api.post<ApiResponse<{ session: BuildSession }>>(
    `${BASE}/sessions/${sessionId}/cancel`,
    {},
  )
}
