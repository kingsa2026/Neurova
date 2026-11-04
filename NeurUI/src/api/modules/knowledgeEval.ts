/**
 * 知识检索评测控制台 API（C6 评测面产品化）。
 *
 * 只封装既有端点（`api/endpoints/knowledge_core.py`）：
 * - GET  /knowledge/evaluation/baseline      基线读数（未冻结回 unevidenced，不回 0）
 * - POST /knowledge/audit/evaluation/compare 变体 A/B 对照（管理员）
 * - GET  /knowledge/audit/retrieval-metrics  检索在线快照（管理员）
 */
import { api } from '@/api'
import type { ApiResponse } from '@/types/response'

const BASE = '/knowledge'

export interface EvaluationBaselineReadings {
  recall_at_k?: number | null
  mrr?: number | null
  unhit_rate?: number | null
}

export interface EvaluationBaseline {
  measure_state: string
  run_id?: string | null
  frozen_at?: string | null
  case_count?: number
  top_k?: number | null
  context?: Record<string, unknown>
  readings: EvaluationBaselineReadings | null
  missing_reason?: string
}

export interface EvaluationCompareRequest {
  run_a: string
  run_b: string
  min_cases?: number
}

export function getEvaluationBaseline() {
  return api.get<ApiResponse<EvaluationBaseline>>(`${BASE}/evaluation/baseline`)
}

export function compareEvaluationRuns(body: EvaluationCompareRequest) {
  return api.post<ApiResponse<Record<string, unknown>>>(`${BASE}/audit/evaluation/compare`, body)
}

export function getRetrievalMetricsSnapshot() {
  return api.get<ApiResponse<Record<string, unknown>>>(`${BASE}/audit/retrieval-metrics`)
}
