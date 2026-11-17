/**
 * S8 审批审计轨迹契约（audit.ts 侧）
 *
 * 后端 GET /v1/audit/approvals?run_id=&limit=（挂既有 /audit 管理查询域，
 * admin 门；请求+决定成对返回）已存在，前端 audit.ts 此前未封装。
 * 本档锁 URL 形态、参数边界与成对行字段。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, message: 'success', data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import { getApprovalTrajectory } from '@/api/modules/audit'

const mockGet = vi.mocked(api.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('getApprovalTrajectory 契约', () => {
  it('GET /audit/approvals?run_id=（挂既有 audit 查询域，不新开端点域）', async () => {
    await getApprovalTrajectory('run-abc')
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith('/audit/approvals', {
      params: { run_id: 'run-abc', limit: 50 },
    })
  })

  it('limit 可调且随参数下发', async () => {
    await getApprovalTrajectory('run-abc', 100)
    expect(mockGet).toHaveBeenCalledWith('/audit/approvals', {
      params: { run_id: 'run-abc', limit: 100 },
    })
  })

  it('成对行字段边界：request_id/status/decision/decided_by/请求决定时间/时延/事件原样', async () => {
    const data = {
      run_id: 'run-abc',
      total: 1,
      requests: [
        {
          request_id: 'req-1',
          run_id: 'run-abc',
          level: 'L2',
          effective_level: 'L2',
          operation: 'delete_project',
          reason: '高风险动作',
          mode: 'governance',
          status: 'decided',
          decision: 'approved',
          decided_by: 'user-1',
          requested_at: '2026-11-17T12:00:00+00:00',
          decided_at: '2026-11-17T12:00:03+00:00',
          latency_ms: 3120,
          request_event: { timestamp: '2026-11-17T12:00:00+00:00', phase: 'request' },
          decision_event: { timestamp: '2026-11-17T12:00:03+00:00', phase: 'decide', decision: 'approved' },
        },
        {
          request_id: 'req-2',
          run_id: 'run-abc',
          level: 'L1',
          status: 'pending',
          decision: null,
          decided_by: null,
          decided_at: null,
        },
      ],
    }
    mockGet.mockResolvedValueOnce({ code: 0, message: 'success', data })
    const resp: any = await getApprovalTrajectory('run-abc')
    expect(resp.code).toBe(0)
    const first = resp.data.requests[0]
    expect(first.status).toBe('decided')
    expect(first.decision).toBe('approved')
    expect(first.decided_by).toBe('user-1')
    expect(first.latency_ms).toBe(3120)
    expect(first.request_event.phase).toBe('request')
    expect(first.decision_event.decision).toBe('approved')
    // pending 行：无决定事件，状态如实
    expect(resp.data.requests[1].status).toBe('pending')
    expect(resp.data.requests[1].decision_event).toBeUndefined()
  })
})
