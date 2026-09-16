/**
 * ExperienceKnowledgePage — tab 标签 i18n 契约防回归测试。
 *
 * 根因：第三个 tab（recommendations）标签曾硬编码字面量 "Recommendations"，
 * 中文界面出现中英混排（统计/经验知识/Recommendations）。其余两个 tab 均
 * :tab="t(...)" 绑定；全语言包 experience.recommendations 译文齐备，纯页面漏绑。
 *
 * 锁定行为：三个 tab 标签必须全部走 i18n（zh-CN 下为 统计/经验知识/推荐），
 * 任何 tab 出现未翻译英文字面量即回归。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/modules/experience', () => ({
  searchSimilar: vi.fn(),
  getRecommendations: vi.fn(),
  getExperiences: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  getExperienceStats: vi.fn().mockResolvedValue({ data: { total_experiences: 0, success_rate: 0, avg_proficiency: 0, top_categories: [] } }),
  createExperience: vi.fn(),
  deleteExperience: vi.fn(),
  // 页面排行区消费（items/total 信封）；缺导出会报 "No export defined on mock" 噪声
  getExperienceRanking: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
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
  return mount(ExperienceKnowledgePage, {
    global: {
      plugins: [i18n, pinia],
      stubs: {
        'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
      },
    },
  })
}

describe('ExperienceKnowledgePage tab 标签 i18n', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('三个 tab 标签全部走 i18n（无硬编码字面量）', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    const labels = wrapper.findAll('.ant-tab-pane').map((w) => w.attributes('data-tab'))
    expect(labels).toEqual([
      zhCN.skill.stats,
      zhCN.nav.experience,
      zhCN.experience.recommendations,
    ])
    // 硬编码英文防回归：任何 tab 标签不得是未翻译字面量
    expect(labels).not.toContain('Recommendations')
  })
})
