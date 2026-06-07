/**
 * 记忆共享组管理 API
 */

import request from '@/api/request'

export interface ShareGroup {
  group_id: string
  name: string
  description: string
  agent_ids: string[]
  created_at: string
  updated_at: string
  metadata: Record<string, unknown>
}

export interface ShareGroupCreate {
  name: string
  description?: string
  agent_ids: string[]
  metadata?: Record<string, unknown>
}

export interface ShareGroupUpdate {
  name?: string
  description?: string
  metadata?: Record<string, unknown>
}

export const memoryShareGroupsAPI = {
  /**
   * 获取所有共享组
   */
  list(): Promise<ShareGroup[]> {
    return request.get('/api/v1/memory-share-groups')
  },

  /**
   * 创建共享组
   */
  create(data: ShareGroupCreate): Promise<ShareGroup> {
    return request.post('/api/v1/memory-share-groups', data)
  },

  /**
   * 获取共享组详情
   */
  get(groupId: string): Promise<ShareGroup> {
    return request.get(`/api/v1/memory-share-groups/${groupId}`)
  },

  /**
   * 更新共享组信息
   */
  update(groupId: string, data: ShareGroupUpdate): Promise<ShareGroup> {
    return request.put(`/api/v1/memory-share-groups/${groupId}`, data)
  },

  /**
   * 删除共享组
   */
  delete(groupId: string): Promise<{ success: boolean; message: string }> {
    return request.delete(`/api/v1/memory-share-groups/${groupId}`)
  },

  /**
   * 将 Agent 添加到共享组
   */
  addAgent(groupId: string, agentId: string): Promise<{ success: boolean; message: string }> {
    return request.post(`/api/v1/memory-share-groups/${groupId}/agents`, { agent_id: agentId })
  },

  /**
   * 从共享组移除 Agent
   */
  removeAgent(groupId: string, agentId: string): Promise<{ success: boolean; message: string }> {
    return request.delete(`/api/v1/memory-share-groups/${groupId}/agents/${agentId}`)
  },

  /**
   * 获取共享组中的所有 Agent
   */
  getAgents(groupId: string): Promise<{ group_id: string; agent_ids: string[] }> {
    return request.get(`/api/v1/memory-share-groups/${groupId}/agents`)
  },

  /**
   * 获取 Agent 所属的所有共享组
   */
  getGroupsForAgent(agentId: string): Promise<{ agent_id: string; groups: ShareGroup[] }> {
    return request.get(`/api/v1/memory-share-groups/agent/${agentId}`)
  },

  /**
   * 获取与指定 Agent 共享记忆的所有 Agent
   */
  getSharedAgents(agentId: string): Promise<{ agent_id: string; shared_agents: string[] }> {
    return request.get(`/api/v1/memory-share-groups/agent/${agentId}/shared-agents`)
  },

  /**
   * 检查两个 Agent 是否在同一共享组中
   */
  checkShared(agentId1: string, agentId2: string): Promise<{ agent_id_1: string; agent_id_2: string; is_shared: boolean }> {
    return request.get(`/api/v1/memory-share-groups/check/${agentId1}/${agentId2}`)
  },
}