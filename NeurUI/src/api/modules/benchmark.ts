import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** 运行基准测试的请求体（suite + 被测 agent）。 */
export interface BenchmarkRunPayload {
  suite_id: string
  agent_id: string
}

/**
 * 运行记录成本标注（D-H 口径：评测手动跑 + 成本标注）。
 * 后端 suite_eval.runSuite 的 costNote 原样透传进运行记录 `cost_note`，
 * 已知键 model/est_tokens，其余键不参与展示（自由结构）。
 */
export interface BenchmarkCostNote {
  model?: string
  est_tokens?: number
  [key: string]: unknown
}

/** 运行记录行（GET /benchmark/runs、/benchmark/results 的 data.items 行）。 */
export interface BenchmarkRunRecord {
  run_id: string
  suite_id?: string
  suite_name?: string
  agent_id?: string
  user_id?: string
  status?: string
  simulated?: boolean
  score?: number | null
  tasks_total?: number | null
  tasks_correct?: number | null
  avg_latency_ms?: number | null
  tags?: string[]
  started_at?: string | null
  completed_at?: string | null
  /** 成本标注：记录带才显示，缺省不渲染（向后兼容） */
  cost_note?: BenchmarkCostNote | null
}

/**
 * 成本标注的展示归一：取模型名与预估 tokens。
 * 记录不带 cost_note、形态非法或双缺时返回 null（调用面显示占位符，不编造数字）。
 */
export function costNoteParts(note: unknown): { model: string; estTokens: number | null } | null {
  if (!note || typeof note !== 'object' || Array.isArray(note)) return null
  const rec = note as Record<string, unknown>
  const model = String(rec.model ?? '').trim()
  const raw = rec.est_tokens
  const num = typeof raw === 'number' ? raw : Number(raw)
  const estTokens = raw != null && raw !== '' && Number.isFinite(num) && num > 0 ? Math.round(num) : null
  if (!model && estTokens == null) return null
  return { model, estTokens }
}

// ---------------------------------------------------------------------------
// API（P2-21：自 BenchmarkPage 裸写 URL 收编；路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** List benchmark suites（信封 {code, data:{suites,total}}）。 */
export function listBenchmarkSuites() {
  return api.get<unknown>('/benchmark/suites')
}

/** List benchmark run results（/runs 的别名；结果列表在 data.items）。 */
export function listBenchmarkResults(params?: { suite_id?: string }) {
  return api.get<unknown>('/benchmark/results', { params })
}

/** Run a benchmark suite against an agent. */
export function runBenchmarkSuite(data: BenchmarkRunPayload) {
  return api.post<unknown>('/benchmark/run', data)
}

/** Get a single benchmark run（N3 真执行器：run 为后台执行，轮询终态用）。 */
export function getBenchmarkRun(runId: string) {
  return api.get<unknown>(`/benchmark/runs/${runId}`)
}

// ---------------------------------------------------------------------------
// S1-1E 多 agent 基线报告（只读）：后端读 runner 落盘报告，不建第二套存储
// ---------------------------------------------------------------------------

/** 单模式聚合列（solo/swarm 同形；usage 相关列 S1-1A 恢复）。 */
export interface BaselineModeMetrics {
  task_count?: number
  passed_count?: number
  success_rate?: number
  mean_score?: number
  unsolvable_identified?: number
  unsolvable_total?: number
  mean_elapsed_seconds?: number | null
  total_tokens?: number | null
  total_steps?: number
  total_tool_calls?: number
  error_count?: number
  by_effort?: Record<string, BaselineModeMetrics>
}

/** 报告列表行（listReports 只读投影，新→旧）。 */
export interface BaselineReportListItem {
  report_id: string
  generated_at?: string
  task_isolated_memory?: boolean | null
  task_count?: number
  metrics?: Record<string, BaselineModeMetrics>
  comparison?: Record<string, unknown>
}

/** 逐任务 usage 读数（prompt/completion/total tokens、步数、工具数）。 */
export interface BaselineTaskUsage {
  promptTokens?: number
  completionTokens?: number
  totalTokens?: number
  elapsedSeconds?: number
  steps?: number
  toolCalls?: number
}

/** 逐任务轨迹读数（工具序列与来源）。 */
export interface BaselineTaskTrajectory {
  toolsUsed?: string[]
  source?: string
}

/** 单份报告的逐任务行（含 usage 与轨迹列）。 */
export interface BaselineTaskRow {
  task_id?: string
  suite?: string
  mode?: string
  passed?: boolean
  score?: number
  error?: string
  rejected?: boolean
  rejection_code?: string
  subagent_id?: string
  elapsed_seconds?: number
  effort?: string
  usage?: BaselineTaskUsage
  trajectory?: BaselineTaskTrajectory
}

/** 单份基线报告全文（loadReport 原样取回）。 */
export interface BaselineReportDetail {
  generated_at?: string
  task_isolated_memory?: boolean | null
  metrics?: Record<string, BaselineModeMetrics>
  comparison?: Record<string, unknown>
  tasks?: BaselineTaskRow[]
}

/** 列出多 agent 基线报告（新→旧，含 usage/轨迹聚合列与隔离注记）。 */
export function getBaselineReports() {
  return api.get<unknown>('/benchmark/baseline-reports')
}

/** 取回单份基线报告全文（逐任务含 usage 与轨迹列）。 */
export function getBaselineReport(reportId: string) {
  return api.get<unknown>(`/benchmark/baseline-reports/${encodeURIComponent(reportId)}`)
}
