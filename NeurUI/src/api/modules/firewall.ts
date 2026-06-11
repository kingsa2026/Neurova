import api from '@/api'
import type { ApiResponse, PaginatedData, PageParams } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FirewallRule {
  id: string
  name: string
  description?: string
  agent_id?: string
  type: 'allow' | 'deny'
  pattern: string
  scope: 'tool' | 'url' | 'content' | 'action'
  priority: number
  enabled: boolean
  hit_count: number
  created_at: string
  updated_at?: string
}

export interface RuleCreatePayload {
  name: string
  description?: string
  agent_id?: string
  type: 'allow' | 'deny'
  pattern: string
  scope: string
  priority?: number
  enabled?: boolean
}

export interface BlockedEntry {
  id: string
  rule_id: string
  rule_name: string
  content: string
  timestamp: string
  agent_id?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/firewall'

/** List firewall rules. */
export function getFirewallRules(params?: PageParams & { agent_id?: string; scope?: string }) {
  return api.get<ApiResponse<PaginatedData<FirewallRule>>>(`${BASE}/rules`, { params })
}

/** Get a single rule. */
export function getFirewallRule(id: string) {
  return api.get<ApiResponse<FirewallRule>>(`${BASE}/rules/${id}`)
}

/** Create a firewall rule. */
export function createFirewallRule(data: RuleCreatePayload) {
  return api.post<ApiResponse<FirewallRule>>(`${BASE}/rules`, data)
}

/** Update a firewall rule. */
export function updateFirewallRule(id: string, data: Partial<RuleCreatePayload>) {
  return api.put<ApiResponse<FirewallRule>>(`${BASE}/rules/${id}`, data)
}

/** Delete a firewall rule. */
export function deleteFirewallRule(id: string) {
  return api.delete<ApiResponse<null>>(`${BASE}/rules/${id}`)
}

/** List blocked actions. */
export function getBlockedEntries(params?: PageParams & { agent_id?: string }) {
  return api.get<ApiResponse<PaginatedData<BlockedEntry>>>(`${BASE}/blocked`, { params })
}
