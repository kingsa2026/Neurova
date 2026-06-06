/**
 * Growth System API Module
 * 成长系统 API 模块
 * 
 * 包含:
 * 1. 反思日志 (Reflection Logs)
 * 2. 问题队列 (Question Queue)
 * 3. 主动行为 (Proactive Behavior)
 * 4. 动机水平 (Motivation Level)
 * 5. 人格系统 (Personality System)
 * 6. 宪法系统 (Constitution System)
 */

import { request } from '../index'

// ==================== 类型定义 ====================

// 反思日志
export interface ReflectionLog {
  log_id: string
  agent_id: string
  timestamp: number
  reflection_type: string
  content: string
  insights: string[]
  confidence: number
  related_memories: string[]
}

export interface CreateReflectionLogRequest {
  reflection_type?: string
  content: string
  insights?: string[]
  confidence?: number
  related_memories?: string[]
}

// 问题条目
export interface QuestionItem {
  question_id: string
  agent_id: string
  timestamp: number
  question_type: string
  question: string
  status: string
  answer: string | null
  priority: number
}

export interface CreateQuestionRequest {
  question_type?: string
  question: string
  priority?: number
}

// 主动行为
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

export interface CreateProactiveActionRequest {
  action_type?: string
  trigger?: string
  content: string
}

// 动机水平
export interface MotivationLevel {
  agent_id: string
  timestamp: number
  overall_motivation: number
  curiosity: number
  creativity: number
  persistence: number
  social: number
  factors: Record<string, number>
}

export interface UpdateMotivationLevelRequest {
  overall_motivation?: number
  curiosity?: number
  creativity?: number
  persistence?: number
  social?: number
}

// 人格信息
export interface Personality {
  agent_id: string
  timestamp: number
  traits: Record<string, number>
  values: string[]
  communication_style: string
  decision_style: string
}

export interface UpdatePersonalityRequest {
  traits?: Record<string, number>
  values?: string[]
  communication_style?: string
  decision_style?: string
}

// 宪法规则
export interface ConstitutionRule {
  rule_id: string
  agent_id: string
  timestamp: number
  rule_type: string
  content: string
  priority: number
  enabled: boolean
}

export interface CreateConstitutionRuleRequest {
  rule_type?: string
  content: string
  priority?: number
}

// 成长数据
export interface GrowthData {
  agent_id: string
  timestamp: number
  reflection_logs: ReflectionLog[]
  questions: QuestionItem[]
  proactive_actions: ProactiveAction[]
  motivation_level: MotivationLevel | null
  personality: Personality | null
  constitution: ConstitutionRule[]
}

// 反思统计
export interface ReflectionStats {
  total_reflections: number
  average_confidence: number
  reflection_types: Record<string, number>
  recent_insights: string[]
}

// 通用响应
export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
  request_id?: string
}

// ==================== API 函数 ====================

// ==================== 成长数据 ====================

/**
 * 获取 Agent 的成长数据
 * @param agentId Agent ID
 * @returns 成长数据
 */
export async function getGrowthData(agentId: string = 'default'): Promise<ApiResponse<GrowthData>> {
  return request({
    url: `/api/v1/growth`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

// ==================== 反思日志 ====================

/**
 * 获取反思日志列表
 * @param agentId Agent ID
 * @param limit 数量限制
 * @param offset 偏移量
 * @returns 反思日志列表
 */
export async function getReflectionLogs(
  agentId: string = 'default',
  limit: number = 20,
  offset: number = 0
): Promise<ReflectionLog[]> {
  return request({
    url: `/api/v1/growth/reflection`,
    method: 'get',
    params: { agent_id: agentId, limit, offset }
  })
}

/**
 * 创建新的反思日志
 * @param agentId Agent ID
 * @param data 反思日志数据
 * @returns 创建的反思日志
 */
export async function createReflectionLog(
  agentId: string = 'default',
  data: CreateReflectionLogRequest
): Promise<ReflectionLog> {
  return request({
    url: `/api/v1/growth/reflection`,
    method: 'post',
    params: { agent_id: agentId },
    data
  })
}

/**
 * 获取反思统计
 * @param agentId Agent ID
 * @returns 反思统计数据
 */
export async function getReflectionStats(agentId: string = 'default'): Promise<ApiResponse<ReflectionStats>> {
  return request({
    url: `/api/v1/growth/reflection/stats`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

// ==================== 问题队列 ====================

/**
 * 获取问题队列
 * @param agentId Agent ID
 * @param status 状态筛选
 * @param limit 数量限制
 * @returns 问题列表
 */
export async function getQuestionQueue(
  agentId: string = 'default',
  status?: string,
  limit: number = 20
): Promise<QuestionItem[]> {
  const params: Record<string, any> = { agent_id: agentId, limit }
  if (status) params.status = status
  return request({
    url: `/api/v1/growth/questions`,
    method: 'get',
    params
  })
}

/**
 * 添加新问题
 * @param agentId Agent ID
 * @param data 问题数据
 * @returns 创建的问题
 */
export async function addQuestion(
  agentId: string = 'default',
  data: CreateQuestionRequest
): Promise<QuestionItem> {
  return request({
    url: `/api/v1/growth/questions`,
    method: 'post',
    params: { agent_id: agentId },
    data
  })
}

/**
 * 获取下一个待解答问题
 * @param agentId Agent ID
 * @returns 下一个问题
 */
export async function getNextQuestion(agentId: string = 'default'): Promise<ApiResponse<QuestionItem | null>> {
  return request({
    url: `/api/v1/growth/questions/next`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

/**
 * 标记问题已回答
 * @param agentId Agent ID
 * @param questionId 问题ID
 * @param answer 答案
 * @returns 更新结果
 */
export async function markQuestionAnswered(
  agentId: string = 'default',
  questionId: string,
  answer: string
): Promise<ApiResponse<{ question_id: string; answer: string }>> {
  return request({
    url: `/api/v1/growth/questions/${questionId}/answer`,
    method: 'put',
    params: { agent_id: agentId, answer }
  })
}

// ==================== 主动行为 ====================

/**
 * 获取主动行为记录
 * @param agentId Agent ID
 * @param limit 数量限制
 * @returns 行为记录列表
 */
export async function getProactiveActions(
  agentId: string = 'default',
  limit: number = 20
): Promise<ProactiveAction[]> {
  return request({
    url: `/api/v1/growth/proactive`,
    method: 'get',
    params: { agent_id: agentId, limit }
  })
}

/**
 * 触发主动行为
 * @param agentId Agent ID
 * @param data 行为数据
 * @returns 创建的行为记录
 */
export async function triggerProactiveAction(
  agentId: string = 'default',
  data: CreateProactiveActionRequest
): Promise<ProactiveAction> {
  return request({
    url: `/api/v1/growth/proactive`,
    method: 'post',
    params: { agent_id: agentId },
    data
  })
}

// ==================== 动机水平 ====================

/**
 * 获取内在动机水平
 * @param agentId Agent ID
 * @returns 动机水平数据
 */
export async function getMotivationLevel(agentId: string = 'default'): Promise<MotivationLevel> {
  return request({
    url: `/api/v1/growth/motivation`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

/**
 * 更新动机水平
 * @param agentId Agent ID
 * @param data 更新数据
 * @returns 更新后的动机水平
 */
export async function updateMotivationLevel(
  agentId: string = 'default',
  data: UpdateMotivationLevelRequest
): Promise<MotivationLevel> {
  return request({
    url: `/api/v1/growth/motivation`,
    method: 'put',
    params: { agent_id: agentId },
    data
  })
}

// ==================== 人格系统 ====================

/**
 * 获取人格信息
 * @param agentId Agent ID
 * @returns 人格数据
 */
export async function getPersonality(agentId: string = 'default'): Promise<Personality> {
  return request({
    url: `/api/v1/growth/personality`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

/**
 * 更新人格信息
 * @param agentId Agent ID
 * @param data 人格数据
 * @returns 更新后的人格数据
 */
export async function updatePersonality(
  agentId: string = 'default',
  data: UpdatePersonalityRequest
): Promise<Personality> {
  return request({
    url: `/api/v1/growth/personality`,
    method: 'put',
    params: { agent_id: agentId },
    data
  })
}

/**
 * 获取人格特质列表
 * @param agentId Agent ID
 * @returns 人格特质
 */
export async function getPersonalityTraits(agentId: string = 'default'): Promise<ApiResponse<{ traits: Record<string, number> }>> {
  return request({
    url: `/api/v1/growth/personality/traits`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

/**
 * 根据学习数据进化人格
 * @param agentId Agent ID
 * @param learningData 学习数据
 * @returns 进化结果
 */
export async function evolvePersonality(
  agentId: string = 'default',
  learningData: Record<string, any> = {}
): Promise<ApiResponse<any>> {
  return request({
    url: `/api/v1/growth/personality/evolve`,
    method: 'post',
    params: { agent_id: agentId },
    data: learningData
  })
}

// ==================== 宪法系统 ====================

/**
 * 获取宪法信息
 * @param agentId Agent ID
 * @returns 宪法数据
 */
export async function getConstitution(agentId: string = 'default'): Promise<ApiResponse<{ constitution: ConstitutionRule[] }>> {
  return request({
    url: `/api/v1/growth/constitution`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

/**
 * 更新宪法
 * @param agentId Agent ID
 * @param constitution 宪法规则列表
 * @returns 更新结果
 */
export async function updateConstitution(
  agentId: string = 'default',
  constitution: ConstitutionRule[]
): Promise<ApiResponse<{ constitution: ConstitutionRule[] }>> {
  return request({
    url: `/api/v1/growth/constitution`,
    method: 'put',
    params: { agent_id: agentId },
    data: constitution
  })
}

/**
 * 获取宪法规则列表
 * @param agentId Agent ID
 * @returns 规则列表
 */
export async function getConstitutionRules(agentId: string = 'default'): Promise<ConstitutionRule[]> {
  return request({
    url: `/api/v1/growth/constitution/rules`,
    method: 'get',
    params: { agent_id: agentId }
  })
}

/**
 * 添加宪法规则
 * @param agentId Agent ID
 * @param data 规则数据
 * @returns 创建的规则
 */
export async function addConstitutionRule(
  agentId: string = 'default',
  data: CreateConstitutionRuleRequest
): Promise<ConstitutionRule> {
  return request({
    url: `/api/v1/growth/constitution/rules`,
    method: 'post',
    params: { agent_id: agentId },
    data
  })
}

/**
 * 更新宪法规则
 * @param agentId Agent ID
 * @param ruleId 规则ID
 * @param data 规则数据
 * @returns 更新后的规则
 */
export async function updateConstitutionRule(
  agentId: string = 'default',
  ruleId: string,
  data: CreateConstitutionRuleRequest
): Promise<ConstitutionRule> {
  return request({
    url: `/api/v1/growth/constitution/rules/${ruleId}`,
    method: 'put',
    params: { agent_id: agentId },
    data
  })
}

/**
 * 删除宪法规则
 * @param agentId Agent ID
 * @param ruleId 规则ID
 * @returns 删除结果
 */
export async function deleteConstitutionRule(
  agentId: string = 'default',
  ruleId: string
): Promise<ApiResponse<{ rule_id: string }>> {
  return request({
    url: `/api/v1/growth/constitution/rules/${ruleId}`,
    method: 'delete',
    params: { agent_id: agentId }
  })
}

/**
 * 评估行为是否符合宪法
 * @param agentId Agent ID
 * @param action 待评估的行为
 * @returns 评估结果
 */
export async function evaluateAgainstConstitution(
  agentId: string = 'default',
  action: string
): Promise<ApiResponse<{ action: string; is_compliant: boolean; violations: any[] }>> {
  return request({
    url: `/api/v1/growth/constitution/evaluate`,
    method: 'get',
    params: { agent_id: agentId, action }
  })
}