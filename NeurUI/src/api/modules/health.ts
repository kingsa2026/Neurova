import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy'
  version: string
  uptime_seconds: number
  timestamp: string
}

export interface HealthCheck {
  name: string
  status: 'pass' | 'warn' | 'fail'
  message?: string
  duration_ms: number
  details?: Record<string, unknown>
}

export interface HealthReport {
  overall: 'healthy' | 'degraded' | 'unhealthy'
  checks: HealthCheck[]
  timestamp: string
  version: string
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/health'

/** Quick health status check. */
export function getHealthStatus() {
  return api.get<ApiResponse<HealthStatus>>(`${BASE}/status`)
}

/** Detailed health checks for all subsystems. */
export function getHealthChecks() {
  return api.get<ApiResponse<HealthCheck[]>>(`${BASE}/checks`)
}

/** Full health report. */
export function getHealthReport() {
  return api.get<ApiResponse<HealthReport>>(`${BASE}/report`)
}

/** Trigger recovery for a failing subsystem. */
export function recoverSubsystem(name: string) {
  return api.post<ApiResponse<{ recovered: boolean; message: string }>>(`${BASE}/recover`, { name })
}

/** Get system metrics (CPU, memory, disk). */
export function getSystemMetrics() {
  return api.get<ApiResponse<{ cpu_percent: number; memory_percent: number; disk_percent: number; memory_mb: number }>>(`${BASE}/metrics`)
}
