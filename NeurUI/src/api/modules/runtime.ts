import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RuntimeStatus {
  status: string
  uptime: number
  start_time: number
  python_version: string
  platform: string
  agent_count: number
}

export interface ResourceUsage {
  cpu_percent: number
  memory_percent: number
  memory_used_mb: number
  memory_total_mb: number
  disk_percent: number
  disk_used_gb: number
  disk_total_gb: number
}

export interface PerformanceMetrics {
  requests_per_second: number
  average_response_time: number
  active_connections: number
  error_rate: number
  cache_hit_rate: number
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/runtime'

/** Get runtime status. */
export function getRuntimeStatus() {
  return api.get<ApiResponse<RuntimeStatus>>(`${BASE}/status`)
}

/** Get system resource usage. */
export function getResourceUsage() {
  return api.get<ApiResponse<ResourceUsage>>(`${BASE}/resources`)
}

/** Get performance metrics. */
export function getPerformanceMetrics() {
  return api.get<ApiResponse<PerformanceMetrics>>(`${BASE}/performance`)
}

/** Trigger garbage collection. */
export function triggerGC() {
  return api.post<ApiResponse<{ objects_collected: number }>>(`${BASE}/gc`)
}
