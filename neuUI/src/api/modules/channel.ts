import { request } from '@/api'

export interface ChannelConfigRequest {
  enabled?: boolean
  config?: Record<string, unknown>
}

export interface ChannelFieldSchema {
  name: string
  type: 'text' | 'password' | 'switch' | 'select' | 'number'
  label: string
  default?: unknown
  required?: boolean
  options?: string[]
}

export interface ChannelCapability {
  display_name: string
  description: string
  required_fields: string[]
  optional_fields: ChannelFieldSchema[]
  common_fields: ChannelFieldSchema[]
}

export interface SendMessageRequest {
  chat_id: string
  content: string
  agent_id?: string
}

export interface LinkUserRequest {
  global_user_id: string
  channel: string
  channel_user_id: string
}

export interface UploadMediaRequest {
  media_type: string
  file_name?: string
  title?: string
  description?: string
}

export interface SendMediaRequest {
  chat_id: string
  file_path: string
  media_type?: string
  caption?: string
  agent_id?: string
}

export const channelAPI = {
  list: () => request.get('/channels'),
  getStatus: (channel: string) => request.get('/channels/' + channel),
  addOrUpdate: (channel: string, data: ChannelConfigRequest) =>
    request.post('/channels/' + channel, data),
  enable: (channel: string) => request.post('/channels/' + channel + '/enable'),
  disable: (channel: string) => request.post('/channels/' + channel + '/disable'),
  remove: (channel: string) => request.delete('/channels/' + channel),
  send: (channel: string, data: SendMessageRequest) =>
    request.post('/channels/' + channel + '/send', data),
  getCapabilities: () => request.get<{ capabilities: Record<string, ChannelCapability> }>('/channels/capabilities'),
  linkUser: (data: LinkUserRequest) => request.post('/channels/users/link', data),
  getUserSessions: (globalUserId: string, agentId?: string) =>
    request.get('/channels/users/' + globalUserId + '/sessions', {
      params: agentId ? { agent_id: agentId } : undefined
    }),
  uploadMedia: (channel: string, file: File, mediaType: string = 'image', title?: string, description?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    return request.post('/channels/' + channel + '/media/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: { media_type: mediaType, title, description }
    })
  },
  downloadMedia: (channel: string, mediaId: string) =>
    request.get('/channels/' + channel + '/media/' + mediaId),
  sendMedia: (channel: string, data: SendMediaRequest) =>
    request.post('/channels/' + channel + '/media/send', data),
}
