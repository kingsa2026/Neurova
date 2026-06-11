import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Webhook {
  id: string
  name: string
  url: string
  events: string[]
  secret?: string
  enabled: boolean
  agent_id?: string
  last_triggered?: string
  failure_count: number
  created_at: string
  updated_at?: string
}

export interface WebhookCreatePayload {
  name: string
  url: string
  events: string[]
  secret?: string
  agent_id?: string
  enabled?: boolean
}

export interface WebhookDelivery {
  id: string
  webhook_id: string
  event: string
  status_code?: number
  success: boolean
  request_body?: string
  response_body?: string
  duration_ms?: number
  created_at: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/webhooks'

/** List all webhooks. */
export function getWebhooks(params?: PageParams & { agent_id?: string }) {
  return api.get<ApiResponse<PaginatedData<Webhook>>>(BASE, { params })
}

/** Get a single webhook. */
export function getWebhook(id: string) {
  return api.get<ApiResponse<Webhook>>(`${BASE}/${id}`)
}

/** Create a webhook. */
export function createWebhook(data: WebhookCreatePayload) {
  return api.post<ApiResponse<Webhook>>(BASE, data)
}

/** Update a webhook. */
export function updateWebhook(id: string, data: Partial<WebhookCreatePayload>) {
  return api.put<ApiResponse<Webhook>>(`${BASE}/${id}`, data)
}

/** Delete a webhook. */
export function deleteWebhook(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/${id}`)
}

/** Send a test event to a webhook. */
export function testWebhook(id: string) {
  return api.post<ApiResponse<{ success: boolean; status_code: number; duration_ms: number }>>(`${BASE}/${id}/test`)
}

/** Get delivery history for a webhook. */
export function getWebhookDeliveries(webhookId: string, params?: PageParams) {
  return api.get<ApiResponse<PaginatedData<WebhookDelivery>>>(`${BASE}/${webhookId}/deliveries`, { params })
}
