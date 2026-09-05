import { request } from '@/api'

export interface WebhookCreate {
  name: string
  url: string
  events: string[]
  filter_agents?: string[]
  filter_channels?: string[]
  max_retries?: number
}

export interface WebhookUpdate {
  name?: string
  url?: string
  events?: string[]
  is_active?: boolean
  filter_agents?: string[]
  filter_channels?: string[]
  max_retries?: number
}

export interface WebhookTestRequest {
  event_type: string
  data?: Record<string, unknown>
}

export interface ListWebhooksRequest {
  app_id?: string
  event_type?: string
  is_active?: boolean
  page?: number
  page_size?: number
}

export const webhooksAPI = {
  list: (params?: ListWebhooksRequest) =>
    request.get('/webhooks/', { params }),
  create: (data: WebhookCreate) => request.post('/webhooks/', data),
  get: (webhookId: string) => request.get('/webhooks/' + webhookId),
  update: (webhookId: string, data: WebhookUpdate) =>
    request.put('/webhooks/' + webhookId, data),
  delete: (webhookId: string) => request.delete('/webhooks/' + webhookId),
  test: (webhookId: string, data?: WebhookTestRequest) =>
    request.post('/webhooks/' + webhookId + '/test', data || {
      event_type: 'CHAT_MESSAGE_RECEIVED',
      data: {}
    }),
  getDeliveries: (webhookId: string, params?: {
    status?: string
    limit?: number
  }) => request.get('/webhooks/' + webhookId + '/deliveries', { params }),
  getDelivery: (webhookId: string, deliveryId: string) =>
    request.get('/webhooks/' + webhookId + '/deliveries/' + deliveryId),
  retryDelivery: (webhookId: string, deliveryId: string) =>
    request.post('/webhooks/' + webhookId + '/deliveries/' + deliveryId + '/retry'),
  verify: (challenge: string) => request.get('/webhooks/verify/' + challenge),
}
