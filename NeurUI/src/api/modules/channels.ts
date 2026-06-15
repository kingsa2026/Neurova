import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Channel {
  id: string
  name: string
  type: string
  enabled: boolean
  lastMessage?: string
  description?: string
  token?: string
  webhookUrl?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/channels'

/** List all channels. */
export function listChannels() {
  return api.get<Channel[]>(BASE)
}

/** Create a new channel. */
export function createChannel(data: { name: string; type?: string; token?: string; webhookUrl?: string; description?: string }) {
  return api.post<Channel>(BASE, data)
}

/** Update a channel. */
export function updateChannel(id: string, data: { name?: string; type?: string; token?: string; webhookUrl?: string; description?: string }) {
  return api.put<Channel>(`${BASE}/${id}`, data)
}

/** Delete a channel. */
export function deleteChannel(id: string) {
  return api.delete<null>(`${BASE}/${id}`)
}

/** Test a channel connection. */
export function testChannel(id: string) {
  return api.post<null>(`${BASE}/${id}/test`)
}

/** Toggle a channel's enabled state. */
export function toggleChannel(id: string, enabled: boolean) {
  return api.put<null>(`${BASE}/${id}`, { enabled })
}
