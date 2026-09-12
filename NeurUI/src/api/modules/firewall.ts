import api from '@/api'

// ---------------------------------------------------------------------------
// Types —— 对齐后端真实模型（2026-09-12 P3 双模型收口）
//
// 此前本模块按虚构契约声明 {id,type:allow|deny,pattern,scope,priority,hit_count}，
// 与后端 FirewallRule {rule_id,rule_type:ip|path|rate_limit,action:block|allow|limit,value}
// 完全不同源 → POST 恒缺 value 422、保存从不生效。
// ---------------------------------------------------------------------------

export interface FirewallRule {
  rule_id: string
  name: string
  rule_type: string
  action: string
  value: string
  enabled: boolean
  created_at: number
  updated_at: number
}

export interface RuleCreatePayload {
  name: string
  rule_type: string
  action: string
  value: string
  /** rate_limit 规则的目标窗口（minute|hour） */
  window?: string
}

export interface BlockedLists {
  blocked_ips: string[]
  blocked_paths: string[]
}

export interface FirewallStats {
  total_rules: number
  active_rules: number
  blocked_ips: number
  blocked_paths: number
}

// ---------------------------------------------------------------------------
// API
// 注：axios 拦截器已剥一层，api.get<T> 实际返回 HTTP body 本身。
// GET /rules 后端返回裸数组；/blocked 与 /stats 是 {code,data} 信封。
// ---------------------------------------------------------------------------

const BASE = '/firewall'

/** List firewall rules. */
export function getFirewallRules(params?: { rule_type?: string; limit?: number }) {
  return api.get<FirewallRule[]>(`${BASE}/rules`, { params })
}

/** Create a firewall rule. */
export function createFirewallRule(data: RuleCreatePayload) {
  return api.post<FirewallRule>(`${BASE}/rules`, data)
}

/** Update a firewall rule (value/name per rule_id). */
export function updateFirewallRule(ruleId: string, data: RuleCreatePayload) {
  return api.put<FirewallRule>(`${BASE}/rules/${ruleId}`, data)
}

/** Delete a firewall rule (ip/path only; rate limits are updated via PUT). */
export function deleteFirewallRule(ruleId: string) {
  return api.delete<{ code: number; message: string }>(`${BASE}/rules/${ruleId}`)
}

/** List blocked IP/path entries. */
export function getBlockedEntries() {
  return api.get<{ code: number; data: BlockedLists }>(`${BASE}/blocked`)
}

/** Firewall summary stats. */
export function getFirewallStats() {
  return api.get<{ code: number; data: FirewallStats }>(`${BASE}/stats`)
}
