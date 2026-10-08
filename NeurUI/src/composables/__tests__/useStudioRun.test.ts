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
import * as useStudioRunModule from '@/composables/useStudioRun'

function runOf(id: string, status: string, detailJson = '{}', error = '') {
  return {
    id, project_id: 'p1', kind: 'extract', status,
    detail_json: detailJson, error, created_at: 0, updated_at: 0,
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

/**
 * H2-7 ①：`detail_json` 的带病读数必须有真读者（§6-87）。
 *
 * 改前 `track()` 只看 `status`，`done_with_fallback` 走的是 success 那一支——服务端写进去的
 * 条数与成因在界面上等于没写。这里用 stub 翻译函数把「取了哪些键」钉成可断言的读数，
 * 键名必须与结算侧的契约一致（Python 侧有跨语言判据咬合 `useStudioRun.ts` 的 `facts.*`）。
 */
describe('describeRunOutcome 把结算契约读成人能看的一句话', () => {
  const tStub = (key: string, named?: Record<string, unknown>) => `${key}|${named?.n ?? ''}`
  const reader = () => (useStudioRunModule as any).describeRunOutcome as
    ((run: any, t: typeof tStub) => string) | undefined

  it('读者存在（改前 detail_json 只写不读）', () => {
    expect(typeof reader()).toBe('function')
  })

  it('带病计数按契约键取，不自己重算 blocked_*', () => {
    const out = reader()!({
      ...runOf('r', 'done_with_fallback', '{"submitted":4,"failed":2,"blocked_no_frame":1,"fallback_failed":2,"fallback_blocked":1,"fallback":""}'),
    }, tStub)
    expect(out).toContain('studio.runPartialFailed|2')
    expect(out).toContain('studio.runPartialBlocked|1')
  })

  it('纯成因（无计数）也随行给出', () => {
    const out = reader()!({
      ...runOf('r', 'done_with_fallback', '{"episodes":1,"fallback":"LLM 输出不可解析"}'),
    }, tStub)
    expect(out).toContain('LLM 输出不可解析')
    expect(out).not.toContain('runPartialFailed')
  })

  it('干净完成不产出任何带病文案', () => {
    const out = reader()!({
      ...runOf('r', 'done', '{"done":3,"fallback_failed":0,"fallback_blocked":0,"fallback":""}'),
    }, tStub)
    expect(out).toBe('')
  })

  it('历史行只有 error 文本时退回它；detail_json 坏 JSON 不炸', () => {
    const legacy = reader()!({
      ...runOf('r', 'done_with_fallback', '{}', '1 项被阻断'),
    }, tStub)
    expect(legacy).toBe('1 项被阻断')
    const broken = reader()!({
      ...runOf('r', 'done_with_fallback', '{不是 JSON', ''),
    }, tStub)
    expect(typeof broken).toBe('string')
  })
})
