import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UsageAnalytics {
  period: string
  total_requests: number
  total_tokens: number
  avg_latency_ms: number
  by_agent: { agent_id: string; name: string; requests: number; tokens: number }[]
  by_model: { model: string; requests: number; tokens: number }[]
  daily_trend: { date: string; requests: number; tokens: number }[]
}

export interface PerformanceAnalytics {
  period: string
  avg_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
  error_rate: number
  throughput_rps: number
  by_endpoint: { endpoint: string; avg_ms: number; count: number }[]
}

export interface BehaviorAnalytics {
  period: string
  top_tools: { name: string; usage_count: number }[]
  top_skills: { name: string; usage_count: number }[]
  conversation_patterns: { pattern: string; count: number }[]
  peak_hours: { hour: number; requests: number }[]
}

export interface ErrorAnalytics {
  period: string
  total_errors: number
  error_rate: number
  by_type: { type: string; count: number }[]
  by_endpoint: { endpoint: string; count: number }[]
  recent_errors: { timestamp: string; type: string; message: string; endpoint: string }[]
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/analytics'

/** Get usage analytics. */
export function getUsageAnalytics(params?: { period?: string; agent_id?: string }) {
  return api.get<ApiResponse<UsageAnalytics>>(`${BASE}/usage`, { params })
}

/** Get performance analytics. */
export function getPerformanceAnalytics(params?: { period?: string }) {
  return api.get<ApiResponse<PerformanceAnalytics>>(`${BASE}/performance`, { params })
}

/** Get behavior analytics. */
export function getBehaviorAnalytics(params?: { period?: string; agent_id?: string }) {
  return api.get<ApiResponse<BehaviorAnalytics>>(`${BASE}/behavior`, { params })
}

/** Get error analytics. */
export function getErrorAnalytics(params?: { period?: string }) {
  return api.get<ApiResponse<ErrorAnalytics>>(`${BASE}/errors`, { params })
}
