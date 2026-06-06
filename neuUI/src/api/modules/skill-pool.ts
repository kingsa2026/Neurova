/**
 * Skill Pool API Module
 * 技能池管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface SkillPool {
  id: string
  name: string
  description: string
  skills: SkillPoolItem[]
  max_skills: number
  auto_discover: boolean
  created_at: number
  updated_at: number
}

export interface SkillPoolItem {
  skill_id: string
  name: string
  version: string
  enabled: boolean
  priority: number
  added_at: number
}

export interface CreateSkillPoolRequest {
  name: string
  description?: string
  max_skills?: number
  auto_discover?: boolean
}

export interface UpdateSkillPoolRequest {
  name?: string
  description?: string
  max_skills?: number
  auto_discover?: boolean
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取技能池列表
 * @param params 查询参数
 * @returns 技能池列表
 */
export async function getSkillPools(params?: {
  limit?: number
  offset?: number
}): Promise<SkillPool[]> {
  return request({
    url: `/api/v1/skill-pool`,
    method: 'get',
    params
  })
}

/**
 * 获取技能池详情
 * @param poolId 技能池ID
 * @returns 技能池详情
 */
export async function getSkillPool(poolId: string): Promise<SkillPool> {
  return request({
    url: `/api/v1/skill-pool/${poolId}`,
    method: 'get'
  })
}

/**
 * 创建技能池
 * @param data 技能池数据
 * @returns 创建的技能池
 */
export async function createSkillPool(data: CreateSkillPoolRequest): Promise<SkillPool> {
  return request({
    url: `/api/v1/skill-pool`,
    method: 'post',
    data
  })
}

/**
 * 更新技能池
 * @param poolId 技能池ID
 * @param data 更新数据
 * @returns 更新后的技能池
 */
export async function updateSkillPool(poolId: string, data: UpdateSkillPoolRequest): Promise<SkillPool> {
  return request({
    url: `/api/v1/skill-pool/${poolId}`,
    method: 'put',
    data
  })
}

/**
 * 删除技能池
 * @param poolId 技能池ID
 * @returns 删除结果
 */
export async function deleteSkillPool(poolId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/skill-pool/${poolId}`,
    method: 'delete'
  })
}

/**
 * 添加技能到池
 * @param poolId 技能池ID
 * @param skillId 技能ID
 * @param priority 优先级
 * @returns 更新后的技能池
 */
export async function addSkillToPool(
  poolId: string,
  skillId: string,
  priority: number = 0
): Promise<SkillPool> {
  return request({
    url: `/api/v1/skill-pool/${poolId}/skills`,
    method: 'post',
    params: { skill_id: skillId, priority }
  })
}

/**
 * 从池中移除技能
 * @param poolId 技能池ID
 * @param skillId 技能ID
 * @returns 更新后的技能池
 */
export async function removeSkillFromPool(poolId: string, skillId: string): Promise<SkillPool> {
  return request({
    url: `/api/v1/skill-pool/${poolId}/skills/${skillId}`,
    method: 'delete'
  })
}

/**
 * 启用/禁用池中技能
 * @param poolId 技能池ID
 * @param skillId 技能ID
 * @param enabled 是否启用
 * @returns 更新后的技能池
 */
export async function togglePoolSkill(
  poolId: string,
  skillId: string,
  enabled: boolean
): Promise<SkillPool> {
  return request({
    url: `/api/v1/skill-pool/${poolId}/skills/${skillId}/toggle`,
    method: 'put',
    params: { enabled }
  })
}

/**
 * 获取技能池统计
 * @returns 统计数据
 */
export async function getSkillPoolStats(): Promise<ApiResponse<{
  total_pools: number
  total_skills: number
  avg_skills_per_pool: number
}>> {
  return request({
    url: `/api/v1/skill-pool/stats`,
    method: 'get'
  })
}