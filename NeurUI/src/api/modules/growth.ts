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
  quality?: number
  quality_score?: number
  created_at: string
}

export interface GrowthQuestion {
  id: string
  agent_id: string
  question: string
  status: string
  answered: boolean
  answer?: string
  priority?: number
  created_at: string | number
}

/** GrowthAnalyzer 能力成长状态（GET /growth/capabilities；未装配为 null） */
export interface GrowthCapabilities {
  overall_score: number
  overall_status: string
  total_records: number
  dimension_statuses: Record<string, { score: number; status: string }>
  capability_scores?: Record<string, number>
}

export interface ProactiveAction {
  action_id: string
  agent_id: string
  timestamp: number
  action_type: string
  trigger: string
  content: string
  success: boolean
  response_received: boolean
}

/** BE GET/PUT /growth/personality envelope.data 真实契约（2026-09-16 契约收口）。
 * 曾含幻影字段 style/tone——BE 从不返回（真实字段是 communication_style/decision_style），
 * 页面标签恒空。 */
export interface PersonalityProfile {
  agent_id: string
  timestamp?: number
  traits: Record<string, number>
  values: string[]
  communication_style: string
  decision_style: string
}

/** MotivationLedger 真实快照（GET /growth/motivation envelope.data） */
export interface MotivationState {
  agent_id: string
  level: number
  factors: { name: string; impact: number }[]
  drives: Record<string, { intensity: number; satisfaction: number }>
  drive_weights: Record<string, number>
  event_count: number
  updated_at?: number | null
}

export interface ConstitutionRule {
  rule_id: string
  agent_id: string
  rule_type: string
  content: string
  priority: number
  enabled: boolean
  timestamp: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/growth'

/** BE ReflectionLog → FE GrowthReflection 字段归一（2026-09-15 契约收口）。
 * 拦截器已返回裸 body（BE 此端点是裸数组），res.data 取法恒 undefined。 */
function normalizeReflection(r: any): GrowthReflection {
  return {
    id: r.id ?? r.log_id ?? '',
    agent_id: r.agent_id ?? '',
    content: r.content ?? '',
    category: r.category ?? r.reflection_type,
    insights: r.insights ?? [],
    quality: r.quality_score ?? (r.confidence !== undefined ? Math.round(r.confidence * 50) / 10 : undefined),
    created_at: r.created_at ?? (r.timestamp ? new Date(r.timestamp * 1000).toISOString() : ''),
  }
}

/** Get growth reflections for an agent（limit/offset 对齐 BE Query；envelope.data 归一数组，2026-09-16 契约收口）。 */
export async function getReflections(agentId: string, params?: { limit?: number; offset?: number }): Promise<GrowthReflection[]> {
  const res: any = await api.get(`${BASE}/reflection`, { params: { ...params, agent_id: agentId } })
  return ((res?.data ?? []) as any[]).map(normalizeReflection)
}

/** Create a reflection. 契约对齐：agent_id 走 query；insights/confidence 真实入库；envelope.data 为创建后条目。 */
export function createReflection(agentId: string, content: string, category?: string, insights?: string[], confidence?: number) {
  return api.post<ApiResponse<GrowthReflection>>(`${BASE}/reflection`, {
    content,
    reflection_type: category ?? 'general',
    insights: insights ?? [],
    confidence: confidence ?? 0.5,
  }, { params: { agent_id: agentId } })
}

/** Get growth capabilities (real GrowthAnalyzer data; null when analyzer not wired). */
export function getCapabilities(agentId: string) {
  return api.get<ApiResponse<GrowthCapabilities | null>>(`${BASE}/capabilities`, { params: { agent_id: agentId } })
}

/** Get growth questions. 契约对齐：BE 用 limit/offset/answered 查询参；envelope.data 列表含 asked 终态。 */
export async function getQuestions(agentId: string, params?: { limit?: number; offset?: number; answered?: boolean }): Promise<GrowthQuestion[]> {
  const res: any = await api.get(`${BASE}/questions`, { params: { ...params, agent_id: agentId } })
  return (res?.data ?? []) as GrowthQuestion[]
}

/** Create a growth question (agent_id 走 query——BE Query 参数，原 body 传法会被忽略落 default；envelope.data 为创建后条目)。 */
export function createQuestion(agentId: string, question: string, questionType = 'curiosity') {
  return api.post<ApiResponse<GrowthQuestion>>(`${BASE}/questions`, { question, question_type: questionType }, { params: { agent_id: agentId } })
}

/** Answer a question. 契约对齐 2026-09-15：BE 是 PUT + query(answer)，原 POST+body 恒 405/参数丢失。 */
export function answerQuestion(agentId: string, questionId: string, answer: string) {
  return api.put<unknown>(`${BASE}/questions/${questionId}/answer`, null, { params: { agent_id: agentId, answer } })
}

/** Get proactive actions（envelope.data 列表；引擎未接线时如实为空）。 */
export async function getProactiveActions(agentId: string, params?: { status?: string }): Promise<ProactiveAction[]> {
  const res: any = await api.get(`${BASE}/proactive`, { params: { ...params, agent_id: agentId } })
  return (res?.data ?? []) as ProactiveAction[]
}

/** Get motivation state. */
export function getMotivation(agentId: string) {
  return api.get<ApiResponse<MotivationState>>(`${BASE}/motivation`, { params: { agent_id: agentId } })
}

/** Get personality profile. */
export function getPersonality(agentId: string) {
  return api.get<ApiResponse<PersonalityProfile>>(`${BASE}/personality`, { params: { agent_id: agentId } })
}

/** Update personality. agent_id 走 query（BE 是 Query 声明，body 传法被静默忽略→恒写 default）。 */
export function updatePersonality(agentId: string, data: Partial<PersonalityProfile>) {
  return api.put<ApiResponse<PersonalityProfile>>(`${BASE}/personality`, data, { params: { agent_id: agentId } })
}

/** Get constitution rules（envelope.data 列表）。 */
export function getConstitution(agentId: string) {
  return api.get<ApiResponse<ConstitutionRule[]>>(`${BASE}/constitution/rules`, { params: { agent_id: agentId } })
}

/** Add a constitution rule（envelope.data 为创建后规则）。 */
export function addConstitutionRule(agentId: string, rule: string, priority?: number) {
  return api.post<ApiResponse<ConstitutionRule>>(`${BASE}/constitution/rules`, { content: rule, priority }, { params: { agent_id: agentId } })
}

/** Update a constitution rule (partial: content/priority/enabled；envelope.data 为更新后规则)。 */
export function updateConstitutionRule(agentId: string, ruleId: string, data: Partial<ConstitutionRule>) {
  return api.put<ApiResponse<ConstitutionRule>>(`${BASE}/constitution/rules/${ruleId}`, data, { params: { agent_id: agentId } })
}

/** Delete a constitution rule. */
export function deleteConstitutionRule(agentId: string, ruleId: string) {
  return api.delete<unknown>(`${BASE}/constitution/rules/${ruleId}`, { params: { agent_id: agentId } })
}
