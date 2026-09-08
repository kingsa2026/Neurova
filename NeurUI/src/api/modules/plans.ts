import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types（契约与后端 neurova/api/endpoints/plans.py 严格对齐）
// ---------------------------------------------------------------------------

export interface PlanQuestionOption {
  label: string
  description: string
}

export interface PlanQuestion {
  id: string
  question: string
  options: PlanQuestionOption[]
  multi: boolean
  allow_custom: boolean
}

export interface PlanAnswer {
  id: string
  selected: string[]
  custom: string
}

export interface PlanRound {
  questions: PlanQuestion[]
  answers: PlanAnswer[]
  supplement?: string
}

export interface PlanDocument {
  name: string
  rel_path: string
  title?: string
  size?: number
  modified?: number
}

export interface PlanSession {
  session_id: string
  agent_id: string
  request: string
  status: 'asking' | 'awaiting_approval' | 'approved' | 'rejected'
  rounds: PlanRound[]
  document: PlanDocument | null
  created_at: number
  updated_at: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/plans'

/** 发起计划会话（出首轮澄清问题）。 */
export function startPlanSession(agentId: string, request: string) {
  return api.post<ApiResponse<{ session: PlanSession }>>(`${BASE}/sessions`, {
    agent_id: agentId,
    request,
  })
}

/** 读取会话状态。 */
export function getPlanSession(sessionId: string) {
  return api.get<ApiResponse<{ session: PlanSession }>>(`${BASE}/sessions/${sessionId}`)
}

/** 提交一轮回答/自由补充（不限轮数；LLM 判定收口后返回计划文档）。 */
export function submitPlanAnswers(
  sessionId: string,
  answers: PlanAnswer[],
  supplement = ''
) {
  return api.post<ApiResponse<{ session: PlanSession }>>(
    `${BASE}/sessions/${sessionId}/answers`,
    { answers, supplement }
  )
}

/** 审批决定；approve 时 data.execute_prompt 含计划全文。 */
export function decidePlan(sessionId: string, action: 'approve' | 'reject', note = '') {
  return api.post<ApiResponse<{ session: PlanSession; execute_prompt: string | null }>>(
    `${BASE}/sessions/${sessionId}/decision`,
    { action, note }
  )
}

/** 列出 agent 工作目录下的计划文档（最新在前）。 */
export function listPlanDocuments(agentId: string) {
  return api.get<ApiResponse<{ documents: PlanDocument[] }>>(`${BASE}/documents`, {
    params: { agent_id: agentId },
  })
}

/** 读取计划文档全文（MD 预览数据源）。 */
export function readPlanDocument(agentId: string, name: string) {
  return api.get<ApiResponse<PlanDocument & { content: string }>>(
    `${BASE}/documents/${name}`,
    { params: { agent_id: agentId } }
  )
}
