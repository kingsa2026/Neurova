/**
 * Projects API Module
 * 项目管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Project {
  id: string
  name: string
  description: string
  status: 'active' | 'archived' | 'deleted'
  created_at: number
  updated_at: number
  owner_id: string
  tags: string[]
  members: string[]
}

export interface CreateProjectRequest {
  name: string
  description?: string
  tags?: string[]
  members?: string[]
}

export interface UpdateProjectRequest {
  name?: string
  description?: string
  status?: 'active' | 'archived' | 'deleted'
  tags?: string[]
  members?: string[]
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取项目列表
 * @param params 查询参数
 * @returns 项目列表
 */
export async function getProjects(params?: {
  status?: string
  limit?: number
  offset?: number
  search?: string
}): Promise<Project[]> {
  return request({
    url: `/api/v1/projects`,
    method: 'get',
    params
  })
}

/**
 * 获取项目详情
 * @param projectId 项目ID
 * @returns 项目详情
 */
export async function getProject(projectId: string): Promise<Project> {
  return request({
    url: `/api/v1/projects/${projectId}`,
    method: 'get'
  })
}

/**
 * 创建项目
 * @param data 项目数据
 * @returns 创建的项目
 */
export async function createProject(data: CreateProjectRequest): Promise<Project> {
  return request({
    url: `/api/v1/projects`,
    method: 'post',
    data
  })
}

/**
 * 更新项目
 * @param projectId 项目ID
 * @param data 更新数据
 * @returns 更新后的项目
 */
export async function updateProject(
  projectId: string,
  data: UpdateProjectRequest
): Promise<Project> {
  return request({
    url: `/api/v1/projects/${projectId}`,
    method: 'put',
    data
  })
}

/**
 * 删除项目
 * @param projectId 项目ID
 * @returns 删除结果
 */
export async function deleteProject(projectId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/projects/${projectId}`,
    method: 'delete'
  })
}

/**
 * 获取项目统计
 * @returns 统计数据
 */
export async function getProjectStats(): Promise<ApiResponse<{
  total: number
  active: number
  archived: number
  deleted: number
}>> {
  return request({
    url: `/api/v1/projects/stats`,
    method: 'get'
  })
}

/**
 * 添加项目成员
 * @param projectId 项目ID
 * @param memberId 成员ID
 * @returns 更新后的项目
 */
export async function addProjectMember(
  projectId: string,
  memberId: string
): Promise<Project> {
  return request({
    url: `/api/v1/projects/${projectId}/members`,
    method: 'post',
    params: { member_id: memberId }
  })
}

/**
 * 移除项目成员
 * @param projectId 项目ID
 * @param memberId 成员ID
 * @returns 更新后的项目
 */
export async function removeProjectMember(
  projectId: string,
  memberId: string
): Promise<Project> {
  return request({
    url: `/api/v1/projects/${projectId}/members/${memberId}`,
    method: 'delete'
  })
}

/**
 * 获取项目成员列表
 * @param projectId 项目ID
 * @returns 成员ID列表
 */
export async function getProjectMembers(projectId: string): Promise<string[]> {
  return request({
    url: `/api/v1/projects/${projectId}/members`,
    method: 'get'
  })
}