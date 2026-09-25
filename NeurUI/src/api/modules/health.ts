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
  // 后端契约是 `GET /api/v1/health`（`endpoints/health.py` 的 `@router.get("")`）；
  // 原写 `/health/status` 从未注册过路由，健康状态轮询实测恒 404
  // （并被 store 的 catch 吞成「状态未知」）。
  return api.get<ApiResponse<HealthStatus>>(BASE)
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

