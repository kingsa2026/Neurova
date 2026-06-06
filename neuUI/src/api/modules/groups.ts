/**
 * Groups API Module
 * 群组管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface Group {
  id: string
  name: string
  description: string
  type: 'public' | 'private' | 'secret'
  owner_id: string
  members: GroupMember[]
  created_at: number
  updated_at: number
  settings: GroupSettings
}

export interface GroupMember {
  user_id: string
  role: 'owner' | 'admin' | 'member' | 'guest'
  joined_at: number
  nickname?: string
}

export interface GroupSettings {
  allow_invites: boolean
  max_members: number
  default_agent_id?: string
}

export interface CreateGroupRequest {
  name: string
  description?: string
  type?: 'public' | 'private' | 'secret'
  settings?: Partial<GroupSettings>
}

export interface UpdateGroupRequest {
  name?: string
  description?: string
  type?: 'public' | 'private' | 'secret'
  settings?: Partial<GroupSettings>
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取群组列表
 * @param params 查询参数
 * @returns 群组列表
 */
export async function getGroups(params?: {
  type?: string
  limit?: number
  offset?: number
  search?: string
}): Promise<Group[]> {
  return request({
    url: `/api/v1/groups`,
    method: 'get',
    params
  })
}

/**
 * 获取群组详情
 * @param groupId 群组ID
 * @returns 群组详情
 */
export async function getGroup(groupId: string): Promise<Group> {
  return request({
    url: `/api/v1/groups/${groupId}`,
    method: 'get'
  })
}

/**
 * 创建群组
 * @param data 群组数据
 * @returns 创建的群组
 */
export async function createGroup(data: CreateGroupRequest): Promise<Group> {
  return request({
    url: `/api/v1/groups`,
    method: 'post',
    data
  })
}

/**
 * 更新群组
 * @param groupId 群组ID
 * @param data 更新数据
 * @returns 更新后的群组
 */
export async function updateGroup(groupId: string, data: UpdateGroupRequest): Promise<Group> {
  return request({
    url: `/api/v1/groups/${groupId}`,
    method: 'put',
    data
  })
}

/**
 * 删除群组
 * @param groupId 群组ID
 * @returns 删除结果
 */
export async function deleteGroup(groupId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/groups/${groupId}`,
    method: 'delete'
  })
}

/**
 * 加入群组
 * @param groupId 群组ID
 * @returns 加入结果
 */
export async function joinGroup(groupId: string): Promise<Group> {
  return request({
    url: `/api/v1/groups/${groupId}/join`,
    method: 'post'
  })
}

/**
 * 离开群组
 * @param groupId 群组ID
 * @returns 离开结果
 */
export async function leaveGroup(groupId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/groups/${groupId}/leave`,
    method: 'post'
  })
}

/**
 * 添加群组成员
 * @param groupId 群组ID
 * @param userId 用户ID
 * @param role 角色
 * @returns 更新后的群组
 */
export async function addGroupMember(
  groupId: string,
  userId: string,
  role: string = 'member'
): Promise<Group> {
  return request({
    url: `/api/v1/groups/${groupId}/members`,
    method: 'post',
    params: { user_id: userId, role }
  })
}

/**
 * 移除群组成员
 * @param groupId 群组ID
 * @param userId 用户ID
 * @returns 更新后的群组
 */
export async function removeGroupMember(groupId: string, userId: string): Promise<Group> {
  return request({
    url: `/api/v1/groups/${groupId}/members/${userId}`,
    method: 'delete'
  })
}

/**
 * 获取群组成员列表
 * @param groupId 群组ID
 * @returns 成员列表
 */
export async function getGroupMembers(groupId: string): Promise<GroupMember[]> {
  return request({
    url: `/api/v1/groups/${groupId}/members`,
    method: 'get'
  })
}

/**
 * 搜索公开群组
 * @param query 搜索关键词
 * @param limit 数量限制
 * @returns 群组列表
 */
export async function searchGroups(query: string, limit: number = 20): Promise<Group[]> {
  return request({
    url: `/api/v1/groups/search`,
    method: 'get',
    params: { q: query, limit }
  })
}