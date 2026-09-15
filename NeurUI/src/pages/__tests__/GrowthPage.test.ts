import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// 成长域 API mock：反思日志相关端点必须零调用（已迁往反思页）
const growthMocks = vi.hoisted(() => ({
  getMotivation: vi.fn(),
  getPersonality: vi.fn(),
  getConstitution: vi.fn(),
  getQuestions: vi.fn(),
  getCapabilities: vi.fn(),
  getProactiveActions: vi.fn(),
  getReflections: vi.fn(),
  createReflection: vi.fn(),
  createQuestion: vi.fn(),
  answerQuestion: vi.fn(),
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
        capabilities: '能力成长', overallScore: '综合评分', totalRecords: '条成长记录',
        responded: '已回应', notResponded: '待回应',
        dimensionCognitive: '认知', dimensionMemory: '记忆', dimensionReasoning: '推理', dimensionLearning: '学习',
        dimensionAdaptation: '适应', dimensionCreativity: '创造', dimensionSocial: '社交', dimensionEmotional: '情绪',
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
  growthMocks.getConstitution.mockResolvedValue([{ rule_id: 'c1', agent_id: 'a1', rule_type: 'behavior', content: '规则A', enabled: true, priority: 1, timestamp: 1789000000 }])
  growthMocks.getQuestions.mockResolvedValue([])
  growthMocks.getCapabilities.mockResolvedValue({
    code: 0,
    data: {
      overall_score: 40,
      overall_status: 'learning',
      total_records: 12,
      dimension_statuses: {
        learning: { score: 42, status: 'learning' },
        cognitive: { score: 8, status: 'initial' },
      },
    },
  })
  growthMocks.createQuestion.mockResolvedValue({ data: {} })
  growthMocks.answerQuestion.mockResolvedValue({ data: {} })
  growthMocks.getProactiveActions.mockResolvedValue([])
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

  // 2026-09-15 反思/成长链路修复：GrowthAnalyzer 数据读链打通 + asked 态问题可见
  it('概览渲染能力成长卡片（真实 analyzer 分数）', async () => {
    const wrapper = await mountPage()
    expect(growthMocks.getCapabilities).toHaveBeenCalledWith('a1')
    // GlassCard 轻 stub 不渲染 title prop，断言卡片体真实内容
    const text = wrapper.text()
    expect(text).toContain('综合评分')
    expect(text).toContain('42/100')
    expect(text).toContain('认知')
  })

  it('analyzer 未装配（data=null）时能力卡片走空态分支不报错', async () => {
    growthMocks.getCapabilities.mockResolvedValue({ code: 0, data: null })
    const wrapper = await mountPage()
    expect(growthMocks.getCapabilities).toHaveBeenCalledWith('a1')
    // a-empty 轻 stub 不渲染 slot 文本，用 capabilities prop 透传验证分支：
    // GlassCard 轻 stub 收到 title 但 capabilities 为 null → 不渲染任何分数
    expect(wrapper.text()).not.toContain('42/100')
    expect(wrapper.text()).not.toContain('综合评分')
  })

  it('问题列表渲染 asked 条目（修复前 BE 只回 pending、FE 取 res.data 双恒空）', async () => {
    growthMocks.getQuestions.mockResolvedValue([
      { id: 'q1', question_id: 'q1', agent_id: 'a1', question: '已提问问题?', status: 'asked', answered: false, created_at: 1789000000 },
    ])
    const wrapper = await mountPage()
    expect(growthMocks.getQuestions).toHaveBeenCalledWith('a1', { limit: 50 })
    expect(wrapper.text()).toContain('已提问问题?')
  })

  it('主动行为页签渲染真实动作（engine 条目含 response_received 回流态）', async () => {
    growthMocks.getProactiveActions.mockResolvedValue([
      {
        action_id: 'act-1', agent_id: 'a1', timestamp: 1789000000, action_type: 'communication',
        trigger: 'proactive_question:q1', content: '主动提问内容A', success: true, response_received: true,
      },
    ])
    const wrapper = await mountPage()
    expect(growthMocks.getProactiveActions).toHaveBeenCalledWith('a1')
    const vm = wrapper.vm as any
    expect(vm.actions).toHaveLength(1)
    expect(vm.actions[0].action_id).toBe('act-1')
  })
})
