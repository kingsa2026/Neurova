/**
 * Rules API Module
 * 规则管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Rule {
  id: string
  name: string
  description: string
  type: 'system' | 'user' | 'agent'
  category: string
  content: RuleContent
  enabled: boolean
  priority: number
  created_at: number
  updated_at: number
}

export interface RuleContent {
  conditions: RuleCondition[]
  actions: RuleAction[]
}

export interface RuleCondition {
  type: string
  operator: string
  value: any
}

export interface RuleAction {
  type: string
  params: Record<string, any>
}

export interface CreateRuleRequest {
  name: string
  description?: string
  type?: 'system' | 'user' | 'agent'
  category?: string
  content: RuleContent
  priority?: number
}

export interface UpdateRuleRequest {
  name?: string
  description?: string
  type?: 'system' | 'user' | 'agent'
  category?: string
  content?: RuleContent
  enabled?: boolean
  priority?: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取规则列表
 * @param params 查询参数
 * @returns 规则列表
 */
export async function getRules(params?: {
  type?: string
  category?: string
  enabled?: boolean
  limit?: number
  offset?: number
}): Promise<Rule[]> {
  return request({
    url: `/api/v1/rules`,
    method: 'get',
    params
  })
}

/**
 * 获取规则详情
 * @param ruleId 规则ID
 * @returns 规则详情
 */
export async function getRule(ruleId: string): Promise<Rule> {
  return request({
    url: `/api/v1/rules/${ruleId}`,
    method: 'get'
  })
}

/**
 * 创建规则
 * @param data 规则数据
 * @returns 创建的规则
 */
export async function createRule(data: CreateRuleRequest): Promise<Rule> {
  return request({
    url: `/api/v1/rules`,
    method: 'post',
    data
  })
}

/**
 * 更新规则
 * @param ruleId 规则ID
 * @param data 更新数据
 * @returns 更新后的规则
 */
export async function updateRule(ruleId: string, data: UpdateRuleRequest): Promise<Rule> {
  return request({
    url: `/api/v1/rules/${ruleId}`,
    method: 'put',
    data
  })
}

/**
 * 删除规则
 * @param ruleId 规则ID
 * @returns 删除结果
 */
export async function deleteRule(ruleId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/rules/${ruleId}`,
    method: 'delete'
  })
}

/**
 * 启用/禁用规则
 * @param ruleId 规则ID
 * @param enabled 是否启用
 * @returns 更新后的规则
 */
export async function toggleRule(ruleId: string, enabled: boolean): Promise<Rule> {
  return request({
    url: `/api/v1/rules/${ruleId}/toggle`,
    method: 'put',
    params: { enabled }
  })
}

/**
 * 评估规则
 * @param ruleId 规则ID
 * @param context 评估上下文
 * @returns 评估结果
 */
export async function evaluateRule(
  ruleId: string,
  context: Record<string, any>
): Promise<ApiResponse<{ matched: boolean; actions: RuleAction[] }>> {
  return request({
    url: `/api/v1/rules/${ruleId}/evaluate`,
    method: 'post',
    data: context
  })
}

/**
 * 批量评估规则
 * @param context 评估上下文
 * @returns 匹配的规则列表
 */
export async function evaluateAllRules(
  context: Record<string, any>
): Promise<ApiResponse<Array<{ rule: Rule; matched: boolean; actions: RuleAction[] }>>> {
  return request({
    url: `/api/v1/rules/evaluate`,
    method: 'post',
    data: context
  })
}

/**
 * 获取规则统计
 * @returns 统计数据
 */
export async function getRuleStats(): Promise<ApiResponse<{
  total: number
  enabled: number
  disabled: number
  by_type: Record<string, number>
  by_category: Record<string, number>
}>> {
  return request({
    url: `/api/v1/rules/stats`,
    method: 'get'
  })
}

/**
 * 获取规则分类列表
 * @returns 分类列表
 */
export async function getRuleCategories(): Promise<string[]> {
  return request({
    url: `/api/v1/rules/categories`,
    method: 'get'
  })
}