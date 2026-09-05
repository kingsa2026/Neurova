import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// 成长域 API mock：反思日志相关端点必须零调用（已迁往反思页）
const growthMocks = vi.hoisted(() => ({
  getMotivation: vi.fn(),
  getPersonality: vi.fn(),
  getConstitution: vi.fn(),
  getQuestions: vi.fn(),
  getProactiveActions: vi.fn(),
  getReflections: vi.fn(),
  createReflection: vi.fn(),
}))

vi.mock('@/api/modules/growth', () => growthMocks)
vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'a1' }, currentAgent: { value: { name: 'Test' } } }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import GrowthPage from '../GrowthPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      nav: { reflection: '反思' },
      memory: { overview: '概览' },
      growth: {
        reflection: '反思日志', questions: '成长问题', proactive: '主动行为',
        constitution: '宪法', rules: '宪法规则', motivation: '动机水平', personality: '个性档案',
        moreRules: '条更多规则',
      },
      common: {
        refresh: '刷新', create: '创建', total: '总计', type: '类型', description: '描述',
        createdAt: '时间', status: '状态', actions: '操作', search: '搜索', noData: '暂无',
        success: '成功', error: '失败', delete: '删除', filter: '筛选', all: '全部',
      },
    },
  },
})

function contractMocks() {
  growthMocks.getMotivation.mockResolvedValue({ code: 0, data: { level: 0.6, factors: [], updated_at: '2026-09-05T00:00:00Z' } })
  growthMocks.getPersonality.mockResolvedValue({ code: 0, data: { traits: { curiosity: 0.7 } } })
  growthMocks.getConstitution.mockResolvedValue({ code: 0, data: [{ id: 'c1', rule: '规则A', enabled: true, priority: 1, created_at: '2026-09-05T00:00:00Z' }] })
  growthMocks.getQuestions.mockResolvedValue({ code: 0, data: [] })
  growthMocks.getProactiveActions.mockResolvedValue({ code: 0, data: [] })
}

// ant-tabs 轻 stub：tab 标签文本经 data-tab 透传，断言才有意义
const globalStubs = {
  GlassCard: { template: '<div><slot name="extra"/><slot/></div>' },
  GlassButton: { template: '<button><slot/></button>' },
  'a-tabs': { template: '<div class="ant-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
}

describe('GrowthPage 反思日志 tab 迁出契约', () => {
  beforeEach(() => {
    contractMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountPage = async () => {
    const wrapper = mount(GrowthPage, {
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await flushPromises()
    return wrapper
  }

  it('成长页不再包含反思日志 tab（已整合到反思页）', async () => {
    const wrapper = await mountPage()
    const tabNames = wrapper.findAll('.ant-tab-pane').map((p) => p.attributes('data-tab'))
    expect(tabNames).not.toContain('反思日志')
    expect(growthMocks.getReflections).not.toHaveBeenCalled()
    expect(growthMocks.createReflection).not.toHaveBeenCalled()
  })

  it('保留成长域四个页签：概览/成长问题/主动行为/宪法', async () => {
    const wrapper = await mountPage()
    const tabNames = wrapper.findAll('.ant-tab-pane').map((p) => p.attributes('data-tab'))
    expect(tabNames).toEqual(expect.arrayContaining(['概览', '成长问题', '主动行为', '宪法']))
  })
})
