/**
 * Studio 长任务轮询的终态判据（2026-10-08 长任务闭环审计 E 批）。
 *
 * 现场形态：`extract_assets` 那一步会落 `done_with_fallback`（部分资产抽到、部分同名跳过，
 * 任务本身已经跑完），而 `waitStudioRun` 只认 `done|failed`——于是这条已完成的 run
 * 被一路 poll 到 10 分钟上限并返回 null，前端把"已成功"渲染成"超时"
 * （StudioProjectPage 的 `studio.runTimeout` 分支）。写侧有这个终态、读侧不认，
 * 就是 §2 点名的"只写不读"断点。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getProject } = vi.hoisted(() => ({ getProject: vi.fn() }))
vi.mock('@/api/modules/studio', () => ({
  getProject: (...args: any[]) => getProject(...args),
}))

import { waitStudioRun } from '@/composables/useStudioRun'

function runOf(id: string, status: string) {
  return {
    id, project_id: 'p1', kind: 'extract', status,
    detail_json: '{}', error: '', created_at: 0, updated_at: 0,
  }
}

describe('waitStudioRun 终态集合与生产写入点同源', () => {
  beforeEach(() => {
    getProject.mockReset()
  })

  it('done_with_fallback 是终态，原样交回且不再轮', async () => {
    getProject.mockResolvedValue({ data: { runs: [runOf('run_fb', 'done_with_fallback')] } })

    const run = await waitStudioRun('p1', 'run_fb')

    expect(run?.status).toBe('done_with_fallback')
    expect(getProject).toHaveBeenCalledTimes(1)
  })

  it('done / failed 仍是终态（不回归既有语义）', async () => {
    for (const status of ['done', 'failed']) {
      getProject.mockReset()
      getProject.mockResolvedValue({ data: { runs: [runOf('run_x', status)] } })
      const run = await waitStudioRun('p1', 'run_x')
      expect(run?.status).toBe(status)
      expect(getProject).toHaveBeenCalledTimes(1)
    }
  })

  it('running 不提前收：继续轮询而不是当成终态返回', async () => {
    vi.useFakeTimers()
    try {
      getProject.mockResolvedValue({ data: { runs: [runOf('run_go', 'running')] } })
      const ticking = vi.fn()
      const pending = waitStudioRun('p1', 'run_go', { onTick: ticking })
      // 跑满轮询上限：状态一直没进终态集合，应当在 deadline 处返回 null（而非提前交回）
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000 + 5000)
      const run = await pending
      expect(run).toBeNull()
      expect(getProject.mock.calls.length).toBeGreaterThan(1)
      expect(ticking).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })
})
