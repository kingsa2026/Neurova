import { request } from '@/api'

/**
 * 渠道配置 CRUD API
 * 对应后端 /api/v1/channel-configs 端点
 */

export interface ChannelConfig {
  type: string
  enabled: boolean
  config: Record<string, unknown>
  display_name?: string
  created_at?: string
  updated_at?: string
}

export interface ChannelTestResult {
  success: boolean
  message: string
  health?: string
  details?: Record<string, unknown>
}

export const channelConfigAPI = {
  /** 列出所有渠道配置 */
  list: () => request.get('/channel-configs'),

  /** 获取指定类型渠道配置 */
  get: (type: string) => request.get('/channel-configs/' + type),

  /** 创建或更新渠道配置 */
  createOrUpdate: (type: string, data: { enabled: boolean; config: Record<string, unknown> }) =>
    request.post('/channel-configs/' + type, data),

  /** 删除渠道配置 */
  remove: (type: string) => request.delete('/channel-configs/' + type),

  /** 测试渠道连接 */
  test: (type: string) => request.post('/channel-configs/' + type + '/test'),
}
