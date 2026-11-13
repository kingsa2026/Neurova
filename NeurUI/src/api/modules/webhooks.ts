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

/** List all webhooks. 后端 GET /webhooks 不收任何查询参数（P1-13 核对：
 * webhooks.py list_webhooks 无 limit/offset/筛选），不假装支持分页。 */
export function getWebhooks() {
  return api.get<ApiResponse<PaginatedData<Webhook>>>(BASE)
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

/** Get delivery history for a webhook. 后端只收 limit（webhooks.py
 * list_deliveries(limit: int = 50)，无 offset），不假装支持 offset。 */
export function getWebhookDeliveries(webhookId: string, params?: Pick<PageParams, 'limit'>) {
  return api.get<ApiResponse<PaginatedData<WebhookDelivery>>>(`${BASE}/${webhookId}/deliveries`, { params })
}
