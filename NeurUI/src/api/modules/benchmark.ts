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
