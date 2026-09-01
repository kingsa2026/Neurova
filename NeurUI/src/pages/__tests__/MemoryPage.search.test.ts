/**
 * MemoryPage 语义搜索断链修复防回归（2026-09-02 补课 2.1）
 *
 * 原状：performSemanticSearch 调 memoryApi.searchMemories → POST /memory/search
 *   （后端无此 POST 路由 → 405），页面代码注释自证断链。
 * 修复：改调 memoryApi.enhancedSearch（POST /enhanced-memory-search/search），
 *   解包 data.results，后端无 type 参数 → 前端本地过滤。
 *
 * 契约：
 *   1. 调 enhancedSearch（不再调 searchMemories）
 *   2. 响应 data.results 元素 {memory_id|id, content, score, channel|type, created_at}
 *      映射为 MemorySearchResult
 *   3. type 过滤在前端生效
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'default' } }),
}))

const { enhancedSearchMock, searchMemoriesMock } = vi.hoisted(() => ({
  enhancedSearchMock: vi.fn(),
  searchMemoriesMock: vi.fn(),
}))

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual: Record<string, unknown> = await importOriginal()
  return {
    ...actual,
    enhancedSearch: enhancedSearchMock,
    searchMemories: searchMemoriesMock,
  }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: 'admin' } }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import MemoryPage from '@/pages/MemoryPage.vue'
import * as memoryApiModule from '@/api/modules/memory'

const memoryApi = {
  enhancedSearch: memoryApiModule.enhancedSearch as unknown as ReturnType<typeof vi.fn>,
  searchMemories: memoryApiModule.searchMemories as unknown as ReturnType<typeof vi.fn>,
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { common: { error: '错误', search: '搜索' }, memory: {} } },
})

const mountPage = () =>
  mount(MemoryPage, {
    global: { plugins: [i18n] },
  })

describe('MemoryPage performSemanticSearch（断链修复）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls enhancedSearch instead of broken searchMemories', async () => {
    enhancedSearchMock.mockResolvedValue({
      code: 0,
      data: {
        query: 'hello',
        results: [
          {
            memory_id: 'm1',
            content: 'hello memory',
            score: 0.9,
            channel: 'semantic',
            created_at: '2026-09-02T00:00:00Z',
          },
        ],
        total: 1,
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    // 触发语义搜索（组件内开关默认或手动置开后调用）
    ;(wrapper.vm as any).searchQuery = 'hello'
    ;(wrapper.vm as any).semanticSearch = true
    await (wrapper.vm as any).performSemanticSearch()
    await flushPromises()

    expect(memoryApi.enhancedSearch).toHaveBeenCalledWith('hello', { top_k: 20 })
    expect(memoryApi.searchMemories).not.toHaveBeenCalled()
    const results = (wrapper.vm as any).searchResults
    expect(results).toHaveLength(1)
    expect(results[0]).toMatchObject({ id: 'm1', content: 'hello memory', type: 'semantic' })
  })

  it('maps nested data.results and filters by type locally', async () => {
    enhancedSearchMock.mockResolvedValue({
      code: 0,
      data: {
        results: [
          { memory_id: 'a', content: 'x', score: 0.8, channel: 'general' },
          { memory_id: 'b', content: 'y', score: 0.7, channel: 'fact' },
        ],
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    ;(wrapper.vm as any).searchQuery = 'q'
    ;(wrapper.vm as any).semanticSearch = true
    ;(wrapper.vm as any).activeTab = 'fact'
    await (wrapper.vm as any).performSemanticSearch()
    await flushPromises()

    const results = (wrapper.vm as any).searchResults
    expect(results).toHaveLength(1)
    expect(results[0].id).toBe('b')
  })
})
