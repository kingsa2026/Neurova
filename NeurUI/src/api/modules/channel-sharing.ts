import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** 渠道共享配置（GET /channel-sharing 信封 data.config）。 */
export interface ChannelSharingConfig {
  enabled?: boolean
}

/** 可共享渠道行（GET /channel-sharing/available-channels 信封 data.channels）。 */
export interface AvailableSharingChannel {
  type: string
  label: string
  description?: string
  is_shared: boolean
}

// ---------------------------------------------------------------------------
// API（P2-21：自 ContextChannelPage 裸写 URL 收编；路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** Get channel-sharing config（信封 {code, data:{config}}）。 */
export function getChannelSharingConfig() {
  return api.get<unknown>('/channel-sharing')
}

/** Get sharable channels（信封 {code, data:{channels}}）。 */
export function getAvailableSharingChannels() {
  return api.get<unknown>('/channel-sharing/available-channels')
}

/** 维护 shared_channels 集合 + 全局 shared_context 开关。 */
export function updateSharedChannels(data: { channels: string[]; shared_context: boolean }) {
  return api.post<unknown>('/channel-sharing/channels', data)
}

/** 探测单个渠道的共享连通性。 */
export function testChannelSharing(channelId: string) {
  return api.post<unknown>('/channel-sharing/test', { channel: channelId })
}
