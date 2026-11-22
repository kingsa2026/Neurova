/**
 * U8 park 信封解析与轮询（E2）。
 *
 * 验收：parked 信封识别（parked/park_id/poll_after/max_wait_s）；
 * 非 parked/非 JSON → null；轮询 running→completed 取回结果、
 * failed 透传、404 即败、超限诚实失败。
 */
import { describe, it, expect, vi } from 'vitest'
import { parseParkedEnvelope, pollParkedResult } from '../toolPark'

describe('parseParkedEnvelope', () => {
  it('parked 信封 → parkId/pollAfterSec/maxWaitSec', () => {
    const park = parseParkedEnvelope(JSON.stringify({
      parked: true, park_id: 'park_abc123', poll_after: 3, max_wait_s: 800,
    }))
    expect(park).toEqual({ parkId: 'park_abc123', pollAfterSec: 3, maxWaitSec: 800 })
  })

  it('缺省 poll_after/max_wait_s 回落安全默认', () => {
    const park = parseParkedEnvelope(JSON.stringify({ parked: true, park_id: 'p1' }))
    expect(park).toEqual({ parkId: 'p1', pollAfterSec: 2, maxWaitSec: 800 })
  })

  it('非 parked / 非 JSON / 空 → null', () => {
    expect(parseParkedEnvelope(JSON.stringify({ success: true }))).toBeNull()
    expect(parseParkedEnvelope('plain')).toBeNull()
    expect(parseParkedEnvelope(null)).toBeNull()
    expect(parseParkedEnvelope(JSON.stringify({ parked: true }))).toBeNull() // 缺 park_id
  })
})

describe('pollParkedResult', () => {
  it('running → completed 取回最终结果', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ data: { data: { status: 'running', park_id: 'p1' } } })
      .mockResolvedValueOnce({
        data: { data: { status: 'completed', success: true, result: { stdout: 'done' } } },
      })
    const out = await pollParkedResult(
      { parkId: 'p1', pollAfterSec: 1, maxWaitSec: 10 },
      { fetch: fetch as any, intervalMs: 1 },
    )
    expect(out.status).toBe('completed')
    expect((out.data.result as any).stdout).toBe('done')
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('failed 终态透传错误', async () => {
    const fetch = vi.fn().mockResolvedValue({
      data: { data: { status: 'failed', error: '超过 park 上限' } },
    })
    const out = await pollParkedResult(
      { parkId: 'p1', pollAfterSec: 1, maxWaitSec: 10 },
      { fetch: fetch as any, intervalMs: 1 },
    )
    expect(out.status).toBe('failed')
    expect(out.data.error).toBe('超过 park 上限')
  })

  it('404 → 立即失败（park_id 过期）', async () => {
    const fetch = vi.fn().mockRejectedValue({ response: { status: 404 } })
    await expect(
      pollParkedResult({ parkId: 'gone', pollAfterSec: 1, maxWaitSec: 10 },
        { fetch: fetch as any, intervalMs: 1 }),
    ).rejects.toThrow('不存在或已过期')
  })

  it('超限 → 诚实失败不无限挂起', async () => {
    const fetch = vi.fn().mockResolvedValue({ data: { data: { status: 'running' } } })
    await expect(
      pollParkedResult({ parkId: 'p1', pollAfterSec: 1, maxWaitSec: 10 },
        { fetch: fetch as any, intervalMs: 1, maxAttempts: 3 }),
    ).rejects.toThrow('轮询超限')
    expect(fetch).toHaveBeenCalledTimes(3)
  })
})
