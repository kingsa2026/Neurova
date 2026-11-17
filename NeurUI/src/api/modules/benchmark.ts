import api from '@/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** 运行基准测试的请求体（suite + 被测 agent）。 */
export interface BenchmarkRunPayload {
  suite_id: string
  agent_id: string
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
