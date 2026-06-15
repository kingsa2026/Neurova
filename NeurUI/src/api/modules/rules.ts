import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Rule {
  id: string
  name: string
  condition: string
  action: string
  active: boolean
  executionCount?: number
  priority?: string
  description?: string
}

export interface ExecutionLog {
  id: string
  ruleId: string
  timestamp: string
  success: boolean
  detail?: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/rules'

/** List all rules. */
export function listRules() {
  return api.get<Rule[]>(BASE)
}

/** Get a single rule by ID. */
export function getRule(id: string) {
  return api.get<Rule>(`${BASE}/${id}`)
}

/** Create a new rule. */
export function createRule(data: { name: string; condition?: string; action?: string; priority?: string; description?: string }) {
  return api.post<Rule>(BASE, data)
}

/** Update a rule. */
export function updateRule(id: string, data: { name?: string; condition?: string; action?: string; priority?: string; description?: string }) {
  return api.put<Rule>(`${BASE}/${id}`, data)
}

/** Delete a rule. */
export function deleteRule(id: string) {
  return api.delete<null>(`${BASE}/${id}`)
}

/** Toggle a rule's active state. */
export function toggleRule(id: string) {
  return api.put<null>(`${BASE}/${id}/toggle`)
}

/** Test a rule. */
export function testRule(id: string) {
  return api.post<null>(`${BASE}/${id}/test`)
}

/** Get execution logs for a rule. */
export function getRuleLogs(id: string) {
  return api.get<ExecutionLog[]>(`${BASE}/${id}/logs`)
}
