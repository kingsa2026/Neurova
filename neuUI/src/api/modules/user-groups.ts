/**
 * User Groups API Module
 * 用户组管理 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface UserGroup {
  id: string
  name: string
  description: string
  type: 'role' | 'custom'
  members: string[]
  permissions: string[]
  created_at: number
  updated_at: number
}

export interface CreateUserGroupRequest {
  name: string
  description?: string
  type?: 'role' | 'custom'
  members?: string[]
  permissions?: string[]
}

export interface UpdateUserGroupRequest {
  name?: string
  description?: string
  members?: string[]
  permissions?: string[]
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 获取用户组列表
 * @param params 查询参数
 * @returns 用户组列表
 */
export async function getUserGroups(params?: {
  type?: string
  limit?: number
  offset?: number
}): Promise<UserGroup[]> {
  return request({
    url: `/api/v1/user-groups`,
    method: 'get',
    params
  })
}

/**
 * 获取用户组详情
 * @param groupId 用户组ID
 * @returns 用户组详情
 */
export async function getUserGroup(groupId: string): Promise<UserGroup> {
  return request({
    url: `/api/v1/user-groups/${groupId}`,
    method: 'get'
  })
}

/**
 * 创建用户组
 * @param data 用户组数据
 * @returns 创建的用户组
 */
export async function createUserGroup(data: CreateUserGroupRequest): Promise<UserGroup> {
  return request({
    url: `/api/v1/user-groups`,
    method: 'post',
    data
  })
}

/**
 * 更新用户组
 * @param groupId 用户组ID
 * @param data 更新数据
 * @returns 更新后的用户组
 */
export async function updateUserGroup(
  groupId: string,
  data: UpdateUserGroupRequest
): Promise<UserGroup> {
  return request({
    url: `/api/v1/user-groups/${groupId}`,
    method: 'put',
    data
  })
}

/**
 * 删除用户组
 * @param groupId 用户组ID
 * @returns 删除结果
 */
export async function deleteUserGroup(groupId: string): Promise<ApiResponse<{ id: string }>> {
  return request({
    url: `/api/v1/user-groups/${groupId}`,
    method: 'delete'
  })
}

/**
 * 添加用户组成员
 * @param groupId 用户组ID
 * @param userId 用户ID
 * @returns 更新后的用户组
 */
export async function addUserGroupMember(groupId: string, userId: string): Promise<UserGroup> {
  return request({
    url: `/api/v1/user-groups/${groupId}/members`,
    method: 'post',
    params: { user_id: userId }
  })
}

/**
 * 移除用户组成员
 * @param groupId 用户组ID
 * @param userId 用户ID
 * @returns 更新后的用户组
 */
export async function removeUserGroupMember(groupId: string, userId: string): Promise<UserGroup> {
  return request({
    url: `/api/v1/user-groups/${groupId}/members/${userId}`,
    method: 'delete'
  })
}

/**
 * 获取用户组成员列表
 * @param groupId 用户组ID
 * @returns 成员ID列表
 */
export async function getUserGroupMembers(groupId: string): Promise<string[]> {
  return request({
    url: `/api/v1/user-groups/${groupId}/members`,
    method: 'get'
  })
}

/**
 * 检查用户权限
 * @param userId 用户ID
 * @param permission 权限标识
 * @returns 检查结果
 */
export async function checkUserPermission(
  userId: string,
  permission: string
): Promise<ApiResponse<{ has_permission: boolean }>> {
  return request({
    url: `/api/v1/user-groups/check-permission`,
    method: 'get',
    params: { user_id: userId, permission }
  })
}