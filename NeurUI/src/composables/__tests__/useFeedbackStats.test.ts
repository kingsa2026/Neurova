import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', () => {
  return {
    default: {
      get: vi.fn(),
    },
  }
})

import api from '@/api'
import { useFeedbackStats, deriveFeedbackSummary } from '@/composables/useFeedbackStats'

describe('deriveFeedbackSummary', () => {
  it('computes satisfaction rate from like/dislike counts', () => {
    const s = deriveFeedbackSummary({ like: 7, dislike: 3, total_feedback: 10, recent: [] })
    expect(s.satisfactionRate).toBe(70)
    expect(s.hasFeedback).toBe(true)
  })

  it('reports no feedback and null rate when total is zero', () => {
    const s = deriveFeedbackSummary({ like: 0, dislike: 0, total_feedback: 0, recent: [] })
    expect(s.satisfactionRate).toBeNull()
    expect(s.hasFeedback).toBe(false)
  })
})

describe('useFeedbackStats', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetches stats and derives satisfaction rate', async () => {
    let resolveFn!: (v: any) => void
    vi.mocked(api.get).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFn = resolve
      }) as any,
    )

    const { summary, loading, refresh } = useFeedbackStats()
    const pending = refresh()
    // mid-flight: loading 为 true（useChat 测试同款惯用法）
    expect(loading.value).toBe(true)
    // 注意：@/api 响应拦截器已剥掉 axios 层，resolved 值即服务端 envelope
    // {code, message, data} — 与 useChat.test.ts 的 mock 约定一致
    resolveFn({
      code: 0,
      data: {
        agent_id: '',
        like: 3,
        dislike: 1,
        total_feedback: 4,
        recent: [
          { session_id: 's1', timestamp: '2026-08-29T12:00:00', content: '很好的回答', feedback: 'like' },
        ],
      },
    })
    await pending
    expect(loading.value).toBe(false)

    expect(api.get).toHaveBeenCalledWith('/console/chat/feedback/stats', {
      params: { limit: 200 },
    })
    expect(summary.value.like).toBe(3)
    expect(summary.value.dislike).toBe(1)
    expect(summary.value.satisfactionRate).toBe(75)
    expect(summary.value.recent).toHaveLength(1)
  })

  it('passes agent_id filter when provided', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: { code: 0, data: { like: 0, dislike: 0, total_feedback: 0, recent: [] } },
    } as any)

    const { refresh } = useFeedbackStats()
    await refresh('agent-1')

    expect(api.get).toHaveBeenCalledWith('/console/chat/feedback/stats', {
      params: { agent_id: 'agent-1', limit: 200 },
    })
  })

  it('keeps zero state and marks error on API failure (dashboard must not crash)', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('network'))
    const { summary, error, refresh } = useFeedbackStats()
    await refresh()
    expect(error.value).toBeInstanceOf(Error)
    expect(summary.value.totalFeedback).toBe(0)
    expect(summary.value.satisfactionRate).toBeNull()
  })
})
