import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Agent 行（消费方按各自字段读取；主键以 agent_id ?? id 归一）。 */
export interface AgentRow {
  agent_id?: string
  id?: string
  name?: string
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// API（P2-21：自 SettingPage 裸写 URL 收编；路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** List agents（裸数组或 {items}/{agents} 信封，消费方自行归一）。 */
export function listAgents() {
  return api.get<ApiResponse<AgentRow[]>>('/agents')
}

// ---------------------------------------------------------------------------
// Agent 布局迁移扫描（v3 分区，管理员）
// ---------------------------------------------------------------------------

/** 布局迁移扫描报告（moved/pending/conflicts/skipped/errors 逐 agent 条目）。 */
export interface AgentLayoutMigrationReport {
  dry_run?: boolean
  full?: boolean
  moved?: Array<{ agent_id?: string; bucket?: string; owner?: string; from?: string; to?: string }>
  pending?: Array<{ agent_id?: string; bucket?: string; owner?: string; reason?: string }>
  skipped?: Array<{ agent_id?: string; bucket?: string; reason?: string }>
  conflicts?: Array<{ agent_id?: string; bucket?: string; target?: string; reason?: string }>
  errors?: Array<{ agent_id?: string; bucket?: string; error?: string }>
  counts?: Record<string, number>
  legacy?: Record<string, unknown>
}

/** 触发布局迁移扫描（管理员）：owner 缺省 = 全量；指定 = 仅该属主的 agent。 */
export function scanAgentLayoutMigration(owner?: string) {
  return api.post<ApiResponse<AgentLayoutMigrationReport>>(
    '/agents/layout/migration/scan',
    owner ? { owner } : {},
  )
}

/** 迁移扫描状态（哨兵 + 属主索引）。 */
export function agentLayoutMigrationStatus() {
  return api.get<
    ApiResponse<{ v3_done: boolean; index: Record<string, { bucket?: string; owner?: string }> }>
  >('/agents/layout/migration/status')
}
