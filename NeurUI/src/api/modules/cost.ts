import api from '@/api'

// ---------------------------------------------------------------------------
// 类型定义（与后端 SQLite 账本 / 预算服务返回结构对齐）
// ---------------------------------------------------------------------------

/** 当前小时概览 */
export interface CurrentHour {
  cost: number
  input_tokens: number
  output_tokens: number
  active_agents: number
}

/** 每日成本条目 */
export interface DailyCostPoint {
  date: string
  total_cost: number
  total_input: number
  total_output: number
  call_count: number
}

/** 每小时趋势条目 */
export interface HourlyTrendPoint {
  hour: string
  total_cost: number
  total_input: number
  total_output: number
  call_count: number
}

/** 看板聚合指标 */
export interface DashboardMetrics {
  current_hour: CurrentHour
  last_7_days: DailyCostPoint[]
  hourly_trend: HourlyTrendPoint[]
}

/** 聚合系统状态 */
export interface RollupStatus {
  store_ready: boolean
  running: boolean
  last_run_at: string | null
}

/** 单条预算状态 */
export interface BudgetStatus {
  scope: string
  identifier: string
  amount: number
  usage: number
  remaining: number
  percentage: number
  is_active: boolean
  is_over_budget: boolean
}

/** 指定 agent 成本汇总 */
export interface AgentCostSummary {
  agent_id: string
  summary: {
    provider: string
    model: string
    total_input: number
    total_output: number
    total_cost: number
  }[]
  total_cost: number
}

// ---------------------------------------------------------------------------
// Cost Rollup API（/api/cost-rollup/*）
// ---------------------------------------------------------------------------

const ROLLUP_BASE = '/cost-rollup'

/** 看板指标：当前小时 + 近 7 天 + 24 小时趋势。 */
export function getDashboardMetrics() {
  return api.get<DashboardMetrics>(`${ROLLUP_BASE}/dashboard/metrics`)
}

/** 聚合系统状态。 */
export function getRollupStatus() {
  return api.get<RollupStatus>(`${ROLLUP_BASE}/rollup/status`)
}

/** 立即聚合上一小时。 */
export function forceRollupNow() {
  return api.post<{ success: boolean; affected_rows: number }>(`${ROLLUP_BASE}/rollup/now`)
}

/** 近 N 天每日成本历史。 */
export function getDailyHistory(days = 30) {
  return api.get<{ days: number; history: DailyCostPoint[] }>(
    `${ROLLUP_BASE}/history/daily`,
    { params: { days } },
  )
}

/** 近 N 小时成本趋势。 */
export function getHourlyHistory(hours = 24) {
  return api.get<{ hours: number; trend: HourlyTrendPoint[] }>(
    `${ROLLUP_BASE}/history/hourly`,
    { params: { hours } },
  )
}

/** 指定 agent 在时间窗内的成本汇总。 */
export function getAgentCost(agentId: string, params?: { start?: string; end?: string }) {
  return api.get<AgentCostSummary>(
    `${ROLLUP_BASE}/agent/${encodeURIComponent(agentId)}/cost`,
    { params },
  )
}

// ---------------------------------------------------------------------------
// Budget API（/api/budgets/*）
// ---------------------------------------------------------------------------

const BUDGET_BASE = '/budgets'

/** 所有预算状态总览（看板用）。 */
export function getAllBudgetStatuses() {
  return api.get<{ budgets: BudgetStatus[] }>(`${BUDGET_BASE}/status/all`)
}

/** 指定 agent 的预算状态。 */
export function getAgentBudgetStatus(agentId: string) {
  return api.get<BudgetStatus>(`${BUDGET_BASE}/status/${encodeURIComponent(agentId)}`)
}

/** 预算系统健康检查。 */
export function getBudgetHealth() {
  return api.get<Record<string, any>>(`${BUDGET_BASE}/health`)
}
