/**
 * Teams API Module
 * 团队管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Team {
  id: string
  name: string
  description: string
  owner_id: string
  members: TeamMember[]
  created_at: number
  updated_at: number
}

export interface TeamMember {
  user_id: string
  role: 'owner' | 'admin' | 'member' | 'viewer'
  joined_at: number
}

export interface CreateTeamRequest {
  name: string
  description?: string
  members?: Array<{ user_id: string; role?: string }>
}

export interface UpdateTeamRequest {
  name?: string
  description?: string
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取团队列表
 * @param params 查询参数
 * @returns 团队列表
 */
export async function getTeams(params?: {
  limit?: number
  offset?: number
  search?: string
}): Promise<Team[]> {
  return request({
    url: `/api/v1/teams`,
    method: 'get',
    params
  })
}

/**
 * 获取团队详情
 * @param teamId 团队ID
 * @returns 团队详情
 */
export async function getTeam(teamId: string): Promise<Team> {
  return request({
    url: `/api/v1/teams/${teamId}`,
    method: 'get'
  })
}

/**
 * 创建团队
 * @param data 团队数据
 * @returns 创建的团队
 */
export async function createTeam(data: CreateTeamRequest): Promise<Team> {
  return request({
    url: `/api/v1/teams`,
    method: 'post',
    data
  })
}

/**
 * 更新团队
 * @param teamId 团队ID
 * @param data 更新数据
 * @returns 更新后的团队
 */
export async function updateTeam(teamId: string, data: UpdateTeamRequest): Promise<Team> {
  return request({
    url: `/api/v1/teams/${teamId}`,
    method: 'put',
    data
  })
}

/**
 * 删除团队
 * @param teamId 团队ID
 * @returns 删除结果
 */
export async function deleteTeam(teamId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/teams/${teamId}`,
    method: 'delete'
  })
}

/**
 * 添加团队成员
 * @param teamId 团队ID
 * @param userId 用户ID
 * @param role 角色
 * @returns 更新后的团队
 */
export async function addTeamMember(
  teamId: string,
  userId: string,
  role: string = 'member'
): Promise<Team> {
  return request({
    url: `/api/v1/teams/${teamId}/members`,
    method: 'post',
    params: { user_id: userId, role }
  })
}

/**
 * 更新团队成员角色
 * @param teamId 团队ID
 * @param userId 用户ID
 * @param role 新角色
 * @returns 更新后的团队
 */
export async function updateTeamMemberRole(
  teamId: string,
  userId: string,
  role: string
): Promise<Team> {
  return request({
    url: `/api/v1/teams/${teamId}/members/${userId}`,
    method: 'put',
    params: { role }
  })
}

/**
 * 移除团队成员
 * @param teamId 团队ID
 * @param userId 用户ID
 * @returns 更新后的团队
 */
export async function removeTeamMember(teamId: string, userId: string): Promise<Team> {
  return request({
    url: `/api/v1/teams/${teamId}/members/${userId}`,
    method: 'delete'
  })
}

/**
 * 获取团队成员列表
 * @param teamId 团队ID
 * @returns 成员列表
 */
export async function getTeamMembers(teamId: string): Promise<TeamMember[]> {
  return request({
    url: `/api/v1/teams/${teamId}/members`,
    method: 'get'
  })
}