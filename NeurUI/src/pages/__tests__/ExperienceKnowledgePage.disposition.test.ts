/**
 * 工单 015 · ExperienceKnowledgePage 处置面。
 *
 * 根因：记录表只有"查看相似 + 删除"两个按钮（`:155-171`）——运营看到一条做砸了的
 * 经验，唯一能做的就是把它删了。降权/隐藏是可逆处置，删除不是，两者不能只有一个入口。
 *
 * 锁定行为：
 * 1. 未处置行给出 审核通过 / 降权 / 隐藏 三个动作；已处置行额外给出 恢复；
 * 2. 点动作真的打到 PUT 处置端点（带正确处置态），并在成功后刷新列表；
 * 3. `experience_count` 显示服务端给的聚合值（后端曾硬编码 1）；
 * 4. 采纳证据与处置态在列表里看得见，否则"降过权的条目"和"没动过的条目"长得一样；
 * 5. 文案全部走 i18n（zh-CN 环境下不得出现裸英文字面量按钮）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import Antd from 'ant-design-vue'

import type { ExperienceRecord } from '@/api/modules/experience'

const RECORD: ExperienceRecord = {
  id: '7',
  agent_id: 'default',
  task_type: 'web_search',
  skill_name: 'web_search',
  context: '搜索 天气 资料',
  outcome: 'failure',
  success_rate: null,
  proficiency: null,
  experience_count: 7,
  lessons: [],
  adoption_outcome: 'failure',
  evidence_state: 'evidenced',
  injected_count: 2,
  seen_count: 1,
  operator_disposition: null,
  metadata: {},
  created_at: '2026-09-20T00:00:00+00:00',
}

const listRecords = vi.fn()
const listRanking = vi.fn()
const setExperienceDisposition = vi.fn()

vi.mock('@/api/modules/experience', () => ({
  searchSimilar: vi.fn().mockResolvedValue({ data: { results: [], total: 0 } }),
  getRecommendations: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  getExperiences: (...args: unknown[]) => listRecords(...args),
  getExperienceStats: vi.fn().mockResolvedValue({
    data: { total_experiences: 7, success_rate: 0.5, avg_proficiency: 0, top_categories: [] },
  }),
  createExperience: vi.fn(),
  deleteExperience: vi.fn(),
  getExperienceRanking: (...args: unknown[]) => listRanking(...args),
  setExperienceDisposition: (...args: unknown[]) => setExperienceDisposition(...args),
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'default' }, currentAgent: { value: null } }),
}))

import ExperienceKnowledgePage from '@/pages/ExperienceKnowledgePage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

async function mountRecordsTab(record = RECORD): Promise<VueWrapper> {
  listRecords.mockResolvedValue({ data: { items: [record], total: 1 } })
  listRanking.mockResolvedValue({ data: { items: [record], total: 1 } })
  setExperienceDisposition.mockResolvedValue({ data: { ...record, operator_disposition: 'demoted' } })
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(ExperienceKnowledgePage, {
    global: { plugins: [i18n, pinia, Antd] },
    attachTo: document.body,
  })
  await flushPromises()
  ;(wrapper.vm as any).activeTab = 'records'
  await flushPromises()
  return wrapper
}

/** vue-i18n 的 `t` 带字面量键的深递归推导，整包语言包喂给它会 TS2589；窄化成一个查表函数。 */
const tr = (key: string) =>
  (i18n.global as unknown as { t: (k: string) => string }).t(key)

/** 处置动作按钮的文案来自语言包，测试从同一处取值，防"改文案即改契约"混进断言。 */
const labels = () => ({
  approve: tr('experience.approve'),
  demote: tr('experience.demote'),
  suppress: tr('experience.suppress'),
  restore: tr('experience.restore'),
})

function buttonByText(wrapper: VueWrapper, text: string) {
  return wrapper.findAll('button').filter((b) => b.text().trim() === text)
}

describe('ExperienceKnowledgePage 处置入口', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('未处置行给出审核/降权/隐藏三个动作', async () => {
    const wrapper = await mountRecordsTab()
    const l = labels()
    expect(buttonByText(wrapper, l.approve).length).toBeGreaterThan(0)
    expect(buttonByText(wrapper, l.demote).length).toBeGreaterThan(0)
    expect(buttonByText(wrapper, l.suppress).length).toBeGreaterThan(0)
    expect(buttonByText(wrapper, l.restore)).toHaveLength(0)
  })

  it('已处置行给出恢复动作', async () => {
    const wrapper = await mountRecordsTab({ ...RECORD, operator_disposition: 'demoted' })
    expect(buttonByText(wrapper, labels().restore).length).toBeGreaterThan(0)
  })

  it('点降权打到处置端点并刷新列表', async () => {
    const wrapper = await mountRecordsTab()
    listRecords.mockClear()
    await buttonByText(wrapper, labels().demote)[0].trigger('click')
    await flushPromises()
    expect(setExperienceDisposition).toHaveBeenCalledWith('7', 'demoted')
    expect(listRecords).toHaveBeenCalled()
  })

  it('恢复动作传 null（后端只认三态加 null）', async () => {
    const wrapper = await mountRecordsTab({ ...RECORD, operator_disposition: 'suppressed' })
    await buttonByText(wrapper, labels().restore)[0].trigger('click')
    await flushPromises()
    expect(setExperienceDisposition).toHaveBeenCalledWith('7', null)
  })

  it('经验数逐行显示服务端给的聚合值，不是同一个常数', async () => {
    // 后端硬编码 1 的根因已在 API 层修掉；这里锁的是"界面不自己写死"——
    // 两行给不同数字就必须显示两个不同数字
    const wrapper = await mountRecordsTab()
    listRanking.mockResolvedValue({
      data: {
        items: [
          { ...RECORD, id: '7', experience_count: 9 },
          { ...RECORD, id: '8', skill_name: 'file_write', task_type: 'file_write', experience_count: 2 },
        ],
        total: 2,
      },
    })
    await (wrapper.vm as any).fetchRanking()
    await flushPromises()
    const cells = wrapper.findAll('.ant-tag').map((t) => t.text().trim())
    expect(cells).toContain('9')
    expect(cells).toContain('2')
  })

  it('采纳证据与处置态在列表里可见', async () => {
    const wrapper = await mountRecordsTab()
    const text = wrapper.text()
    expect(text).toContain(tr('experience.adoptionEvidence'))
    expect(text).toContain('failure')
    expect(text).toContain(tr('experience.unaddressed'))
  })

  it('处置动作全部走 i18n：zh-CN 下出现的是本地化标签而非裸英文', async () => {
    const wrapper = await mountRecordsTab()
    const l = labels()
    const texts = wrapper.findAll('button').map((b) => b.text().trim())
    // 存在性先断言，否则"没有任何按钮"会让下面这条裸英文检查空过
    for (const label of [l.approve, l.demote, l.suppress]) {
      expect(texts, `缺少处置按钮 ${label}`).toContain(label)
    }
    for (const bare of ['Demote', 'Approve', 'Suppress', 'Restore']) {
      expect(texts, `按钮出现未绑定的英文字面量 ${bare}`).not.toContain(bare)
    }
  })
})
