/**
 * Skill Versions API Module
 * 技能版本管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface SkillVersion {
  id: string
  skill_id: string
  version: string
  changelog: string
  file_hash: string
  file_size: number
  created_at: number
  created_by: string
  status: 'active' | 'deprecated' | 'archived'
}

export interface CreateSkillVersionRequest {
  skill_id: string
  version: string
  changelog?: string
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取技能版本列表
 * @param skillId 技能ID
 * @param limit 数量限制
 * @returns 版本列表
 */
export async function getSkillVersions(skillId: string, limit: number = 20): Promise<SkillVersion[]> {
  return request({
    url: `/api/v1/skill-versions`,
    method: 'get',
    params: { skill_id: skillId, limit }
  })
}

/**
 * 获取版本详情
 * @param versionId 版本ID
 * @returns 版本详情
 */
export async function getSkillVersion(versionId: string): Promise<SkillVersion> {
  return request({
    url: `/api/v1/skill-versions/${versionId}`,
    method: 'get'
  })
}

/**
 * 创建新版本
 * @param data 版本数据
 * @returns 创建的版本
 */
export async function createSkillVersion(data: CreateSkillVersionRequest): Promise<SkillVersion> {
  return request({
    url: `/api/v1/skill-versions`,
    method: 'post',
    data
  })
}

/**
 * 设置活跃版本
 * @param versionId 版本ID
 * @returns 更新结果
 */
export async function setActiveVersion(versionId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/skill-versions/${versionId}/activate`,
    method: 'post'
  })
}

/**
 * 删除版本
 * @param versionId 版本ID
 * @returns 删除结果
 */
export async function deleteSkillVersion(versionId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/skill-versions/${versionId}`,
    method: 'delete'
  })
}

/**
 * 获取技能的活跃版本
 * @param skillId 技能ID
 * @returns 活跃版本
 */
export async function getActiveVersion(skillId: string): Promise<SkillVersion | null> {
  return request({
    url: `/api/v1/skill-versions/active`,
    method: 'get',
    params: { skill_id: skillId }
  })
}

/**
 * 获取版本统计
 * @returns 统计数据
 */
export async function getSkillVersionStats(): Promise<ApiResponse<{
  total_versions: number
  active_versions: number
  deprecated_versions: number
  archived_versions: number
}>> {
  return request({
    url: `/api/v1/skill-versions/stats`,
    method: 'get'
  })
}