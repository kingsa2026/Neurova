import api from '@/api'

// ---------------------------------------------------------------------------
// Types —— 后端契约单源（P1-23，审计 2026-11-16）
//
// 枚举与字段名逐项对照后端：
// - `neurova/core/health_checker.py` 的 `HealthStatus` 枚举
//   healthy / degraded / unhealthy / unknown —— 此前前端自造 'pass'|'warn'|'fail'
//   词汇，两边永远对不上（DashboardPage 徽章恒红、HealthPage 判定失效）。
// - `neurova/api/endpoints/health.py` 的三个响应模型：
//   HealthStatusResponse{status,timestamp:float,uptime:float,checks_count,...}、
//   CheckResultResponse{name,status,message,duration:毫秒,check_type}、
//   HealthReportResponse{status,checks:Dict[name,CheckResult],total_checks,...}。
//   axios 拦截器已解包一层，api.get<T> 的 T 即裸载荷。
// ---------------------------------------------------------------------------

export type HealthState = 'healthy' | 'degraded' | 'unhealthy' | 'unknown'

export interface HealthStatus {
  status: HealthState
  timestamp: number
  uptime: number
  checks_count: number
  healthy_count: number
  unhealthy_count: number
  /** 检查器缺席/无注册检查时的降级原因（后端 HealthStatusResponse.message） */
  message: string
}

export interface HealthCheck {
  name: string
  status: HealthState
  message: string
  /** 后端以毫秒计（health_checker 用 (monotonic-start)*1000） */
  duration: number
  check_type: string
}

export interface HealthReport {
  status: HealthState
  /** Dict[name, CheckResult]——不是数组，消费方须经 normalizeHealthChecks 归一 */
  checks: Record<string, HealthCheck>
  total_checks: number
  healthy_count: number
  unhealthy_count: number
  timestamp: number
}

/**
 * 整体状态聚合，与后端 `HealthChecker.get_overall_status()` 严格同像：
 * 空 → unknown；有 unhealthy → unhealthy；有 degraded → degraded；其余 healthy。
 * （unknown 检查项不降级整体——后端就是这个口径，前端不自创第二份聚合语义。）
 */
export function aggregateOverallStatus(checks: Array<{ status?: string }>): HealthState {
  if (!checks.length) return 'unknown'
  if (checks.some((c) => c.status === 'unhealthy')) return 'unhealthy'
  if (checks.some((c) => c.status === 'degraded')) return 'degraded'
  return 'healthy'
}

/**
 * /health/report 的 checks 是 Dict[name, CheckResult]；/health/checks 是数组。
 * 消费方统一走这里拿数组（数组输入原样，非法输入回空——不猜形状）。
 */
export function normalizeHealthChecks(raw: unknown): HealthCheck[] {
  if (Array.isArray(raw)) return raw as HealthCheck[]
  if (raw && typeof raw === 'object') return Object.values(raw as Record<string, HealthCheck>)
  return []
}

// ---------------------------------------------------------------------------
// API（BASE = /health，路由注册见 endpoints/health.py）
// ---------------------------------------------------------------------------

const BASE = '/health'

/** Quick health status check：GET /health（裸 HealthStatusResponse）。 */
export function getHealthStatus() {
  return api.get<HealthStatus>(BASE)
}

/** Detailed health checks：GET /health/checks（裸 CheckResultResponse[]）。 */
export function getHealthChecks() {
  return api.get<HealthCheck[]>(`${BASE}/checks`)
}

/** Full health report：GET /health/report（裸 HealthReportResponse，checks 是 Dict）。 */
export function getHealthReport() {
  return api.get<HealthReport>(`${BASE}/report`)
}

/** 手动执行指定检查：POST /health/checks/{name}/run（裸 CheckResultResponse）。
 *  此前「刷新检查/恢复」两按钮都打 POST /health/recover——后端显式 501（未实现），
 *  而真正的 run 端点全仓零消费者（P1-23）。 */
export function runCheck(name: string) {
  return api.post<HealthCheck>(`${BASE}/checks/${encodeURIComponent(name)}/run`)
}
