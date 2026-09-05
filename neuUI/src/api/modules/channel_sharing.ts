import { request } from '@/api'

export interface SetChannelsRequest {
  channels: string[]
  description?: string
}

export interface TestSharingRequest {
  channel: string
  other_channels?: string[]
}

export const channelSharingAPI = {
  getConfig: () => request.get('/channel-sharing'),
  enable: (sharedChannels?: string[]) =>
    request.post('/channel-sharing/enable', null, {
      params: sharedChannels ? { shared_channels: sharedChannels } : undefined
    }),
  disable: () => request.post('/channel-sharing/disable'),
  setChannels: (data: SetChannelsRequest) =>
    request.post('/channel-sharing/channels', data),
  getAvailableChannels: () => request.get('/channel-sharing/available-channels'),
  test: (data: TestSharingRequest) => request.post('/channel-sharing/test', data),
  getStatus: () => request.get('/channel-sharing/status'),
}
