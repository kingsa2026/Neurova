import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface APIKey {
  key_id: string
  name: string
  agent_id: string
  permissions: string[]
  revoked: boolean
  created_at: number
  expires_at?: number
}

export interface GenerateAPIKeyRequest {
  name: string
  agent_id?: string
  permissions?: string[]
  expires_in_days?: number
}

export interface GenerateAPIKeyResponse {
  key_id: string
  api_key: string
  name: string
  agent_id: string
  permissions: string[]
  created_at: number
  expires_at?: number
}

export interface HandshakeRequest {
  agent_id: string
  agent_name: string
  capabilities?: string[]
  callback_url?: string
}

export interface SendMessageRequest {
  target_agent_id: string
  message_type?: string
  content: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export interface ExternalAgent {
  agent_id: string
  name: string
  capabilities: string[]
  callback_url?: string
  last_seen: number
  status: string
}

export interface Message {
  message_id: string
  from_agent_id: string
  to_agent_id: string
  message_type: string
  content: Record<string, unknown>
  metadata: Record<string, unknown>
  created_at: number
  status: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/agent-communication'

// --- API Keys ---

/** Generate a new API key. */
export function generateAPIKey(data: GenerateAPIKeyRequest) {
  return api.post<ApiResponse<GenerateAPIKeyResponse>>(`${BASE}/api-keys`, data)
}

/** List all API keys. */
export function getAPIKeys() {
  return api.get<ApiResponse<{ api_keys: APIKey[] }>>(`${BASE}/api-keys`)
}

/** Update an API key. */
export function updateAPIKey(keyId: string, data: { name?: string; permissions?: string[] }) {
  return api.put<ApiResponse<null>>(`${BASE}/api-keys/${keyId}`, data)
}

/** Revoke an API key. */
export function revokeAPIKey(keyId: string) {
  return api.post<ApiResponse<null>>(`${BASE}/api-keys/${keyId}/revoke`)
}

/** Delete an API key. */
export function deleteAPIKey(keyId: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/api-keys/${keyId}`)
}

// --- Handshake ---

/** Perform handshake with an external agent. */
export function handshake(data: HandshakeRequest) {
  return api.post<ApiResponse<{ handshake_id: string; status: string; server_agent_id: string; server_capabilities: string[] }>>(`${BASE}/handshake`, data)
}

// --- Messages ---

/** Send a message to an external agent. */
export function sendMessage(data: SendMessageRequest) {
  return api.post<ApiResponse<{ message_id: string; status: string; created_at: number }>>(`${BASE}/messages/send`, data)
}

/** Get message list. */
export function getMessages(params?: { agent_id?: string; limit?: number }) {
  return api.get<ApiResponse<{ messages: Message[] }>>(`${BASE}/messages`, { params })
}

// --- External Agents ---

/** List external agents. */
export function getExternalAgents() {
  return api.get<ApiResponse<{ agents: ExternalAgent[] }>>(`${BASE}/external-agents`)
}

/** Register an external agent. */
export function registerExternalAgent(data: HandshakeRequest) {
  return api.post<ApiResponse<null>>(`${BASE}/external-agents`, data)
}

/** Get external agent status. */
export function getExternalAgentStatus(agentId: string) {
  return api.get<ApiResponse<{ agent_id: string; status: string; last_seen: number }>>(`${BASE}/external-agents/${agentId}/status`)
}

// --- Routing Stats ---

/** Get routing statistics. */
export function getRoutingStats() {
  return api.get<ApiResponse<{ total_messages: number; external_agents: number; api_keys: number }>>(`${BASE}/routing/stats`)
}
