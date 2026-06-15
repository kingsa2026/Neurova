import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Provider {
  provider_id: string
  name: string
  provider_type?: string
  base_url?: string
  api_key?: string
  api_key_configured?: boolean
  enabled?: boolean
  models?: string[]
  config?: Record<string, unknown>
}

export interface ActiveModel {
  model_id: string
  name: string
  provider_name?: string
  provider?: string
}

export interface ConnectionTestResult {
  success?: boolean
  connected?: boolean
  latency_ms?: number
  error?: string
  message?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/providers'

/** List all providers. */
export function listProviders() {
  return api.get<Provider[]>(BASE)
}

/** Get a single provider. */
export function getProvider(providerId: string) {
  return api.get<Provider>(`${BASE}/${providerId}`)
}

/** Create a new provider. */
export function createProvider(data: {
  name: string
  provider_type?: string
  base_url?: string
  api_key?: string
}) {
  return api.post<Provider>(BASE, data)
}

/** Update a provider (API key, config, base_url, etc.). */
export function updateProvider(providerId: string, data: Record<string, unknown>) {
  return api.put<Provider>(`${BASE}/${providerId}`, data)
}

/** Delete a provider. */
export function deleteProvider(providerId: string) {
  return api.delete<null>(`${BASE}/${providerId}`)
}

/** Get the currently active model. */
export function getActiveModel() {
  return api.get<ActiveModel>(`${BASE}/active-model`)
}

/** Activate a model as the default. */
export function activateModel(data: { provider_id: string; model_id: string }) {
  return api.post<null>(`${BASE}/activate-model`, data)
}

/** Test connection to a provider. */
export function testConnection(providerId: string) {
  return api.post<ConnectionTestResult>(`${BASE}/${providerId}/check-connection`)
}

/** Discover available models from a provider. */
export function discoverModels(providerId: string) {
  return api.get<{ models: Record<string, unknown>[] }>(`${BASE}/${providerId}/models/discover`)
}
