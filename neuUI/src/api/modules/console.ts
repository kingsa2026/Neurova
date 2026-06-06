/**
 * Console API Module
 * 控制台 API 模块
 */

import { request } from '../index'

// ==================== 类型定义 ====================

export interface ConsoleCommand {
  command: string
  args?: string[]
  options?: Record<string, any>
}

export interface ConsoleOutput {
  output: string
  error?: string
  exit_code: number
  timestamp: number
}

export interface ConsoleSession {
  id: string
  started_at: number
  last_active: number
  commands_count: number
}

export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ==================== API 函数 ====================

/**
 * 执行控制台命令
 * @param command 命令数据
 * @returns 命令输出
 */
export async function executeCommand(command: ConsoleCommand): Promise<ConsoleOutput> {
  return request({ url: `/api/v1/console/execute`, method: 'post', data: command })
}

/**
 * 获取控制台会话列表
 * @returns 会话列表
 */
export async function getConsoleSessions(): Promise<ConsoleSession[]> {
  return request({ url: `/api/v1/console/sessions`, method: 'get' })
}

/**
 * 创建新的控制台会话
 * @returns 会话信息
 */
export async function createConsoleSession(): Promise<ConsoleSession> {
  return request({ url: `/api/v1/console/sessions`, method: 'post' })
}

/**
 * 获取会话历史
 * @param sessionId 会话ID
 * @param limit 历史数量
 * @returns 命令历史
 */
export async function getConsoleHistory(sessionId: string, limit: number = 50): Promise<ConsoleOutput[]> {
  return request({ url: `/api/v1/console/sessions/${sessionId}/history`, method: 'get', params: { limit } })
}

/**
 * 清除会话历史
 * @param sessionId 会话ID
 * @returns 清除结果
 */
export async function clearConsoleHistory(sessionId: string): Promise<ApiResponse<{ id: string }>> {
  return request({ url: `/api/v1/console/sessions/${sessionId}/history`, method: 'delete' })
}

/**
 * 获取可用命令列表
 * @returns 命令列表
 */
export async function getAvailableCommands(): Promise<string[]> {
  return request({ url: `/api/v1/console/commands`, method: 'get' })
}

/**
 * 获取系统信息
 * @returns 系统信息
 */
export async function getSystemInfo(): Promise<ApiResponse<{
  os: string
  python_version: string
  uptime: number
  memory: { total: number; used: number; free: number }
  disk: { total: number; used: number; free: number }
}>> {
  return request({ url: `/api/v1/console/system-info`, method: 'get' })
}