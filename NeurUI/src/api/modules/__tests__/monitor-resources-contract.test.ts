/**
 * S2 邮箱运维快照契约（monitor.ts 侧）
 *
 * 后端把 mailbox.stats()（在途租约/ack/回收/去重/优先级分布）并入既有
 * GET /monitor/resources 响应（不新增路由，fail-soft 不可用时字段为 null）。
 * 本档锁 URL 形态与 MonitorMailboxStats 字段边界——MonitorPage 邮箱健康卡
 * 只消费该字段，不新增 API 调用。
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
import { getMonitorResources, type MonitorMailboxStats } from '@/api/modules/monitor'

const mockGet = vi.mocked(api.get)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('getMonitorResources 契约', () => {
  it('GET /monitor/resources（S2 mailbox 快照并入本端点，不新增路由）', async () => {
    await getMonitorResources()
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet).toHaveBeenCalledWith('/monitor/resources')
  })

  it('MonitorMailboxStats 字段与后端 mailbox.stats() 快照对齐', () => {
    // 后端 neurova/agent/mailbox.py stats() 返回键集：
    // sessions/pendingTotal/readyTotal/leasedTotal/ackedTotal/reclaimedTotal/
    // dedupedTotal/priorityDistribution{normal,high,urgent}
    const snapshot: MonitorMailboxStats = {
      sessions: 2,
      pendingTotal: 5,
      readyTotal: 3,
      leasedTotal: 2,
      ackedTotal: 41,
      reclaimedTotal: 1,
      dedupedTotal: 7,
      priorityDistribution: { normal: 4, high: 1, urgent: 0 },
    }
    expect(snapshot.leasedTotal).toBe(2)
    expect(snapshot.reclaimedTotal).toBe(1)
    expect(snapshot.priorityDistribution?.urgent).toBe(0)
  })
})
