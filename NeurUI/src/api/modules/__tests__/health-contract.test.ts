import { describe, it, expect, vi } from 'vitest'

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }))

vi.mock('@/api', () => ({
  default: { get: vi.fn(), post: apiPost, put: vi.fn(), delete: vi.fn() },
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

import { aggregateOverallStatus, normalizeHealthChecks, runCheck } from '../health'

/**
 * P1-23（审计 2026-11-16）：健康域状态词汇前后端错位。
 * 后端枚举是 healthy/degraded/unhealthy/unknown（core/health_checker.py:36-40），
 * 前端类型却是 'pass'|'warn'|'fail' → DashboardPage 徽章判据永不命中恒红。
 * 聚合口径必须与后端 get_overall_status() 同像；runCheck 必须打真正的
 * POST /health/checks/{name}/run（此前「刷新检查/恢复」两按钮都打恒 501 的 /recover）。
 */
describe('health 模块契约（P1-23）', () => {
  it('aggregateOverallStatus 与后端 get_overall_status 同像：空→unknown', () => {
    expect(aggregateOverallStatus([])).toBe('unknown')
  })

  it('有 unhealthy 即 unhealthy，有 degraded 即 degraded，unknown 不降级整体', () => {
    expect(aggregateOverallStatus([{ status: 'healthy' }])).toBe('healthy')
    expect(aggregateOverallStatus([{ status: 'healthy' }, { status: 'degraded' }])).toBe('degraded')
    expect(aggregateOverallStatus([{ status: 'degraded' }, { status: 'unhealthy' }])).toBe('unhealthy')
    expect(aggregateOverallStatus([{ status: 'healthy' }, { status: 'unknown' }])).toBe('healthy')
  })

  it('normalizeHealthChecks：Dict→数组，数组原样，垃圾输入回空', () => {
    const dict = {
      db: { name: 'db', status: 'healthy', message: '', duration: 1, check_type: 'custom' },
      llm: { name: 'llm', status: 'unhealthy', message: 'down', duration: 2, check_type: 'dependency' },
    }
    expect(normalizeHealthChecks(dict)).toHaveLength(2)
    expect(normalizeHealthChecks(dict)[1].status).toBe('unhealthy')
    expect(normalizeHealthChecks([dict.db])).toHaveLength(1)
    expect(normalizeHealthChecks(undefined)).toEqual([])
    expect(normalizeHealthChecks('x')).toEqual([])
  })

  it('runCheck 打 POST /health/checks/{name}/run（而非恒 501 的 /recover）', () => {
    runCheck('db')
    expect(apiPost).toHaveBeenCalledWith('/health/checks/db/run')
  })
})
