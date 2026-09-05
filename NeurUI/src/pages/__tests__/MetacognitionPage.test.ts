import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// API mock：五个端点返回契约 shape 的真实样例
const apiMocks = vi.hoisted(() => ({
  getMetacognitionEntries: vi.fn(),
  getMetacognitionStats: vi.fn(),
  getCognitiveState: vi.fn(),
  getReflectionHistory: vi.fn(),
  getLessons: vi.fn(),
  createMetacognition: vi.fn(),
  triggerReflection: vi.fn(),
}))

vi.mock('@/api/modules/metacognition', () => apiMocks)
vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'a1' }, currentAgent: { value: { name: 'Test' } } }),
}))
// AgentPageTabs 内部用 useRoute（router-link 渲染需要）；stub 掉组件本体
vi.mock('@/components/AgentPageTabs', () => ({
  default: { template: '<div class="nr-page-tabs-stub"/>' },
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import MetacognitionPage from '../MetacognitionPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      nav: { metacognition: '元认知' },
      common: { refresh: '刷新', create: '创建', noData: '暂无', description: '描述', createdAt: '时间', success: '成功', error: '错误' },
      memory: {},
      growth: { traits: '认知维度' },
      metacognition: {
        totalEntries: '总条目数', avgConfidence: '平均置信度', confidence: '置信度',
        high: '高', low: '低', active: '主动', idle: '空闲', normal: '正常', slow: '缓慢',
        trigger: '触发器', recentTrend: '近期趋势', entries: '条目', insights: '结构化洞察',
        templateSource: '确定性编译', reflectionHistory: '反思时间线',
        filterByType: '按类型筛选', selfAssessment: '自我评估', strategy: '策略',
        monitoring: '监控', planning: '规划', context: '上下文', createEntry: '创建条目',
        type: '类型', selectType: '选择类型', content: '内容', contentPlaceholder: '输入',
        contextPlaceholder: '输入上下文', contentRequired: '请输入内容',
        triggerReflect: '触发反思', reflectDoneWith: '完成 {n} 条', reflectDoneClean: '无异常',
        loadState: '认知负荷状态', loadLevel: '负荷级别', loadScore: '负荷分数',
        activeTasks: '活跃任务', errorRate: '错误率', responseTime: '响应耗时', updatedAt: '更新时间',
        loadFactors: '负荷四因子构成', factorTasks: '任务密度', factorMemory: '记忆规模',
        factorResponse: '响应耗时', factorError: '错误负荷',
      },
    },
  },
})

function contractMocks() {
  apiMocks.getMetacognitionEntries.mockResolvedValue({
    code: 0,
    data: {
      items: [
        { id: 'r1', type: 'self_assessment', content: '评估内容', context: 'ctx', confidence: 0.8, created_at: '2026-09-04T00:00:00Z' },
      ],
      total: 1,
    },
  })
  apiMocks.getMetacognitionStats.mockResolvedValue({
    code: 0,
    data: {
      total_entries: 1,
      by_type: [{ type: 'self_assessment', count: 1 }],
      avg_confidence: 0.8,
      recent_trend: [{ date: '2026-09-04', count: 1 }],
    },
  })
  apiMocks.getCognitiveState.mockResolvedValue({
    code: 0,
    data: {
      load_level: 'moderate',
      load_score: 0.5,
      active_tasks: 5,
      memory_usage: 0.5,
      response_time_ms: 2500,
      error_rate: 0.1,
      factors: { tasks: 0.5, memory: 0.5, response: 0.5, error: 0.1 },
      created_at: '2026-09-04T00:00:00Z',
    },
  })
  apiMocks.getReflectionHistory.mockResolvedValue({
    code: 0,
    data: { items: [{ created_at: '2026-09-04T01:00:00Z', confidence: 0.9, trigger: 'manual', summary: '1 条洞察' }], total: 1 },
  })
  apiMocks.getLessons.mockResolvedValue({
    code: 0,
    data: {
      items: [
        { subject: 'bad_tool', operator: 'drift', condition: 'tool=bad_tool', finding: '90% -> 0%', recommendation: 'avoid_tool', text: '工具 bad_tool 成功率崩塌', evidence: {}, source: 'template', confidence: 0.9 },
      ],
      total: 1,
    },
  })
}

describe('MetacognitionPage V3 真数据契约', () => {
  beforeEach(() => {
    contractMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountPage = async () => {
    const wrapper = mount(MetacognitionPage, {
      global: { plugins: [i18n], stubs: { GlassCard: { template: '<div><slot name="extra"/><slot/></div>' }, GlassButton: { template: '<button><slot/></button>' } } },
    })
    await flushPromises()
    return wrapper
  }

  it('指标卡渲染认知负荷真状态（非假字段）', async () => {
    const wrapper = await mountPage()
    const text = wrapper.text()
    expect(text).toContain('50%')
    expect(text).toContain('2500 ms')
    expect(apiMocks.getCognitiveState).toHaveBeenCalledWith('a1')
  })

  it('负荷四因子构成卡渲染 factors', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('任务密度')
    expect(wrapper.text()).toContain('记忆规模')
  })

  it('条目列表渲染 type/content 字段（契约对齐后）', async () => {
    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('评估内容')
    expect(wrapper.text()).toContain('自我评估')
  })

  it('反思性内容已迁出：触发反思/结构化洞察/反思时间线不再出现（已迁往反思页）', async () => {
    const wrapper = await mountPage()
    const text = wrapper.text()
    expect(text).not.toContain('触发反思')
    expect(text).not.toContain('结构化洞察')
    expect(text).not.toContain('反思时间线')
    expect(apiMocks.triggerReflection).not.toHaveBeenCalled()
    expect(apiMocks.getLessons).not.toHaveBeenCalled()
    expect(apiMocks.getReflectionHistory).not.toHaveBeenCalled()
  })

  it('不再渲染成对页签（元认知单独为一个页面）', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('.nr-page-tabs').exists()).toBe(false)
  })
})
