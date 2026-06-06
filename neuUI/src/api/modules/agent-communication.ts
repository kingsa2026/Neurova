/**
 * Agent Communication API Module
 * Agent 通信 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface AgentMessage {
  id: string
  from_agent_id: string
  to_agent_id: string
  type: 'text' | 'command' | 'data' | 'request' | 'response'
  content: any
  status: 'pending' | 'sent' | 'delivered' | 'read'
  timestamp: number
}

export interface SendMessageRequest {
  to_agent_id: string
  type?: string
  content: any
}

export interface CommunicationStats {
  total_messages: number
  messages_by_type: Record<string, number>
  avg_latency_ms: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 发送消息
 * @param data 消息数据
 * @returns 发送的消息
 */
export async function sendMessage(data: SendMessageRequest): Promise<AgentMessage> {
  return request({ url: `/api/v1/agent-communication/send`, method: 'post', data })
}

/**
 * 获取收件箱消息
 * @param agentId Agent ID
 * @param limit 数量限制
 * @returns 消息列表
 */
export async function getInboxMessages(agentId: string, limit: number = 20): Promise<AgentMessage[]> {
  return request({ url: `/api/v1/agent-communication/inbox`, method: 'get', params: { agent_id: agentId, limit } })
}

/**
 * 获取发件箱消息
 * @param agentId Agent ID
 * @param limit 数量限制
 * @returns 消息列表
 */
export async function getOutboxMessages(agentId: string, limit: number = 20): Promise<AgentMessage[]> {
  return request({ url: `/api/v1/agent-communication/outbox`, method: 'get', params: { agent_id: agentId, limit } })
}

/**
 * 标记消息已读
 * @param messageId 消息ID
 * @returns 更新结果
 */
export async function markMessageAsRead(messageId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/agent-communication/messages/${messageId}/read`, method: 'put' })
}

/**
 * 删除消息
 * @param messageId 消息ID
 * @returns 删除结果
 */
export async function deleteMessage(messageId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/agent-communication/messages/${messageId}`, method: 'delete' })
}

/**
 * 获取通信统计
 * @param agentId Agent ID
 * @returns 统计数据
 */
export async function getCommunicationStats(agentId?: string): Promise<CommunicationStats> {
  return request({ url: `/api/v1/agent-communication/stats`, method: 'get', params: { agent_id: agentId } })
}

/**
 * 获取对话历史
 * @param agentId1 Agent 1 ID
 * @param agentId2 Agent 2 ID
 * @param limit 数量限制
 * @returns 对话历史
 */
export async function getConversationHistory(
  agentId1: string,
  agentId2: string,
  limit: number = 50
): Promise<AgentMessage[]> {
  return request({ url: `/api/v1/agent-communication/conversation`, method: 'get', params: { agent_id_1: agentId1, agent_id_2: agentId2, limit } })
}

/**
 * 广播消息
 * @param fromAgentId 发送者 Agent ID
 * @param content 消息内容
 * @param type 消息类型
 * @returns 广播结果
 */
export async function broadcastMessage(
  fromAgentId: string,
  content: any,
  type: string = 'text'
): Promise<ApiResponse<{ sent_count: number }>> {
  return request({ url: `/api/v1/agent-communication/broadcast`, method: 'post', params: { from_agent_id: fromAgentId, type }, data: { content } })
}