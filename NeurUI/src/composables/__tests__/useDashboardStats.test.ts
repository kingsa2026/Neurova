import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/modules/home', () => ({
  getHomeData: vi.fn(),
  getHomeTrends: vi.fn(),
}))
vi.mock('@/api/modules/stats', () => ({
  getTokenUsage: vi.fn(),
  getSystemInfo: vi.fn(),
}))
vi.mock('@/api/modules/memory', () => ({
  getMemoryStats: vi.fn(),
}))
vi.mock('@/api/modules/knowledge', () => ({
  getKnowledgeNodes: vi.fn(),
}))
vi.mock('@/api/modules/health', () => ({
  getHealthReport: vi.fn(),
}))
vi.mock('@/api/modules/scheduler', () => ({
  getSchedulerStatus: vi.fn(),
}))

import { getHomeData, getHomeTrends } from '@/api/modules/home'
import { getTokenUsage, getSystemInfo } from '@/api/modules/stats'
import { getMemoryStats } from '@/api/modules/memory'
import { getKnowledgeNodes } from '@/api/modules/knowledge'
import { getHealthReport } from '@/api/modules/health'
import { getSchedulerStatus } from '@/api/modules/scheduler'
import {
  computeDelta,
  useDashboardStats,
  type DashboardStatCard,
} from '@/composables/useDashboardStats'

describe('computeDelta', () => {
  it('computes percent delta of last day vs previous days mean', () => {
    // prev = [2, 2, 2, 3, 2, 2] mean = 2.166 → last=3 → +38.46 ≈ +38
    expect(computeDelta([2, 2, 2, 3, 2, 2, 3])).toBe(38)
  })

  it('returns undefined when previous days are all zero (division guard)', () => {
    expect(computeDelta([0, 0, 0, 0, 0, 0, 2])).toBeUndefined()
  })

  it('returns undefined for empty or single-point series', () => {
    expect(computeDelta([])).toBeUndefined()
    expect(computeDelta([5])).toBeUndefined()
  })
})

describe('useDashboardStats', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getHomeData).mockResolvedValue({ code: 0, data: { stats: { agent_count: 3, conversation_count: 688, token_consumption: 0, llm_call_count: 0, memory_count: 61 } } } as never)
    vi.mocked(getHomeTrends).mockResolvedValue({
      code: 0,
      data: {
        agent_trend: { labels: ['09-01'], data: [1] },
        conversation_trend: { labels: ['09-01'], data: [10] },
        message_trend: { labels: ['09-01'], data: [20] },
        token_trend: { labels: ['09-01'], data: [] },
        llm_trend: { labels: ['09-01'], data: [] },
      },
    } as never)
    vi.mocked(getTokenUsage).mockResolvedValue({ code: 0, data: { total: { calls: 5, prompt_tokens: 1, completion_tokens: 1, total_tokens: 12345 }, total_cost: 0.1, by_model: [{ model: 'gpt-4o', calls: 5, prompt_tokens: 4, completion_tokens: 3, total_tokens: 7 }] } } as never)
    vi.mocked(getMemoryStats).mockResolvedValue({ code: 0, data: { total_memories: 42 } } as never)
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ code: 0, data: { items: [], total: 17, page: 1, size: 1 } } as never)
    vi.mocked(getSystemInfo).mockResolvedValue({ code: 0, data: { status: 'running', cpu: { percent: 33 }, memory: { percent: 66 } } } as never)
    vi.mocked(getHealthReport).mockResolvedValue({ code: 0, data: { overall: 'healthy', checks: [{ name: 'db', status: 'pass' }], timestamp: 't', version: 'v' } } as never)
    vi.mocked(getSchedulerStatus).mockResolvedValue({ code: 0, data: { running: true, total_tasks: 8, active_tasks: 2, uptime_seconds: 60 } } as never)
  })

  it('loads and unwraps all sources into stat cards', async () => {
    const ds = useDashboardStats({ agentId: 'default' })
    await ds.refresh()

    expect(getMemoryStats).toHaveBeenCalledWith('default')
    const cards = ds.cards.value as unknown as DashboardStatCard[]
    const byKey = Object.fromEntries(cards.map((c) => [c.key, c]))
    expect(byKey.agents.value).toBe(3)
    expect(byKey.conversations.value).toBe(688)
    expect(byKey.tokens.value).toBe(12345)
    expect(byKey.calls.value).toBe(5)
    expect(byKey.memories.value).toBe(61)
    expect(byKey.knowledge.value).toBe(17)
  })

  it('falls back to memory stats when home omits memory_count', async () => {
    vi.mocked(getHomeData).mockResolvedValue({ code: 0, data: { stats: { agent_count: 3, conversation_count: 1, token_consumption: 0, llm_call_count: 0 } } } as never)
    const ds = useDashboardStats({ agentId: 'default' })
    await ds.refresh()

    const byKey = Object.fromEntries(ds.cards.value.map((c) => [c.key, c]))
    expect(byKey.memories.value).toBe(42)
  })

  it('derives trends and token distribution', async () => {
    const ds = useDashboardStats({ agentId: 'default' })
    await ds.refresh()

    expect(ds.trends.value.labels).toEqual(['09-01'])
    expect(ds.trends.value.conversation).toEqual([10])
    expect(ds.trends.value.message).toEqual([20])
    expect(ds.tokenByModel.value).toEqual([{ model: 'gpt-4o', calls: 5, prompt_tokens: 4, completion_tokens: 3, total_tokens: 7 }])
  })

  it('counts knowledge items when backend returns a bare array (contract: GET /knowledge → List)', async () => {
    vi.mocked(getKnowledgeNodes).mockResolvedValue({ code: 0, data: [{ id: 'n1' }, { id: 'n2' }, { id: 'n3' }] } as never)
    const ds = useDashboardStats({ agentId: 'default' })
    await ds.refresh()

    const byKey = Object.fromEntries(ds.cards.value.map((c) => [c.key, c]))
    expect(byKey.knowledge.value).toBe(3)
  })

  it('keeps zero-state and surfaces error when home data fails', async () => {
    vi.mocked(getHomeData).mockRejectedValueOnce(new Error('network'))
    const ds = useDashboardStats({ agentId: 'default' })
    await ds.refresh()

    expect(ds.error.value).toContain('network')
    expect(ds.loading.value).toBe(false)
    // 其他数据源仍应成功解包
    expect(ds.cardByKey('conversations')?.value ?? 0).toBe(0)
    expect(ds.cards.value.length).toBeGreaterThan(0)
  })

  it('does not crash when optional sources fail', async () => {
    vi.mocked(getMemoryStats).mockRejectedValueOnce(new Error('mem down'))
    vi.mocked(getSchedulerStatus).mockRejectedValueOnce(new Error('sched down'))
    const ds = useDashboardStats({ agentId: 'default' })
    await ds.refresh()

    expect(ds.cards.value.length).toBeGreaterThan(0)
    expect(ds.error.value).toBeNull()
  })

  it('exposes system health and scheduler summary', async () => {
    const ds = useDashboardStats({ agentId: 'default' })
    await ds.refresh()

    expect(ds.health.value.overall).toBe('healthy')
    expect(ds.health.value.checks.length).toBe(1)
    expect(ds.health.value.system?.cpu).toBe(33)
    expect(ds.scheduler.value.total_tasks).toBe(8)
    expect(ds.scheduler.value.running).toBe(true)
  })
})
