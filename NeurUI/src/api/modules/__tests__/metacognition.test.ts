import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock 依赖（与 execution-events.test.ts 同模式）
vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))
vi.mock('@/config', () => ({ default: { apiBaseUrl: 'http://test:9527/api' } }))
vi.mock('@/utils/security', () => ({
  secureStorage: { get: vi.fn().mockReturnValue('test-token'), set: vi.fn(), remove: vi.fn() },
}))

import api from '@/api'
import {
  getMetacognitionEntries,
  createMetacognition,
  getMetacognitionStats,
  getCognitiveState,
  getReflectionHistory,
  getLessons,
  triggerReflection,
} from '../metacognition'

const mockedApi = vi.mocked(api)

describe('metacognition api 契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedApi.get.mockResolvedValue({ code: 0, data: {} })
    mockedApi.post.mockResolvedValue({ code: 0, data: {} })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('getMetacognitionEntries 走 GET {agentId}/metacognition（分页+类型过滤）', async () => {
    await getMetacognitionEntries('a1', { page: 2, size: 10, type: 'strategy' })
    expect(mockedApi.get).toHaveBeenCalledWith('/metacognition/a1/metacognition', {
      params: { page: 2, size: 10, type: 'strategy' },
    })
  })

  it('createMetacognition 走 POST {agentId}/metacognition', async () => {
    await createMetacognition('a1', { type: 'planning', content: 'x', confidence: 0.5 })
    expect(mockedApi.post).toHaveBeenCalledWith('/metacognition/a1/metacognition', {
      type: 'planning',
      content: 'x',
      confidence: 0.5,
    })
  })

  it('getMetacognitionStats 走 GET {agentId}/metacognition/stats（total_entries 契约）', async () => {
    await getMetacognitionStats('a1')
    expect(mockedApi.get).toHaveBeenCalledWith('/metacognition/a1/metacognition/stats')
  })

  it('getCognitiveState 走 GET {agentId}/metacognition/state（负荷真状态）', async () => {
    await getCognitiveState('a1')
    expect(mockedApi.get).toHaveBeenCalledWith('/metacognition/a1/metacognition/state')
  })

  it('getReflectionHistory 走 GET {agentId}/metacognition/history', async () => {
    await getReflectionHistory('a1', 5)
    expect(mockedApi.get).toHaveBeenCalledWith('/metacognition/a1/metacognition/history', {
      params: { limit: 5 },
    })
  })

  it('getLessons 走 GET {agentId}/metacognition/lessons', async () => {
    await getLessons('a1')
    expect(mockedApi.get).toHaveBeenCalledWith('/metacognition/a1/metacognition/lessons', {
      params: { limit: 20 },
    })
  })

  it('triggerReflection 走 POST {agentId}/metacognition/reflect（零 LLM 反思）', async () => {
    await triggerReflection('a1')
    expect(mockedApi.post).toHaveBeenCalledWith('/metacognition/a1/metacognition/reflect')
  })
})
