/**
 * ExperienceKnowledgePage — 相似经验/推荐解包契约防回归测试。
 *
 * 根因：axios 响应拦截器已解一层（api/index.ts:84 return response.data），
 * 页面再用 Array.isArray(res.data) 判断时 res.data 是后端信封
 * {results,total} / {items,total,...} 而非数组 → 恒走 [] → Similar 弹窗
 * 与 Recommendations 恒空（P1-6）。
 *
 * 锁定行为：
 * 1. searchSimilar 返回 {results:[...]} 信封 → 列表取 results
 * 2. getRecommendations 返回 {items:[...]} 分页信封 → 列表取 items
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

const searchSimilar = vi.fn()
const getRecommendations = vi.fn()

vi.mock('@/api/modules/experience', () => ({
  searchSimilar: (...args: unknown[]) => searchSimilar(...args),
  getRecommendations: (...args: unknown[]) => getRecommendations(...args),
  getExperiences: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  getExperienceStats: vi.fn().mockResolvedValue({ data: { total_experiences: 0, success_rate: 0, avg_proficiency: 0, top_categories: [] } }),
  createExperience: vi.fn(),
  deleteExperience: vi.fn(),
}))

vi.mock('@/composables/useAgentPage', async () => {
  return {
    useAgentPage: () => ({ agentId: { value: 'default' } }),
  }
})

import ExperienceKnowledgePage from '@/pages/ExperienceKnowledgePage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

async function mountPage() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(ExperienceKnowledgePage, {
    global: { plugins: [i18n, pinia] },
  })
  await flushPromises()
  return wrapper
}

describe('ExperienceKnowledgePage 响应解包契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('searchSimilar 信封 {results:[...]} → 弹窗列表非空', async () => {
    const wrapper = await mountPage()
    const record = { id: '1', context: '查询天气', task_type: 'chat' }
    searchSimilar.mockResolvedValue({
      data: { results: [{ id: '9', context: '相似经验A' }], total: 1 },
    })
    await (wrapper.vm as any).findSimilar(record)
    await flushPromises()
    expect((wrapper.vm as any).similarExperiences).toEqual([{ id: '9', context: '相似经验A' }])
  })

  it('getRecommendations 信封 {items:[...]} → 推荐列表非空', async () => {
    const wrapper = await mountPage()
    getRecommendations.mockResolvedValue({
      data: { items: [{ id: '5', context: '推荐经验B' }], total: 1 },
    })
    await (wrapper.vm as any).fetchRecommendations()
    await flushPromises()
    expect((wrapper.vm as any).recommendations).toEqual([{ id: '5', context: '推荐经验B' }])
  })
})
