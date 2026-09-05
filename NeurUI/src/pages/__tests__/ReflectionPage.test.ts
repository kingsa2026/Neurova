import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// 成长域 API mock（反思日志）
const growthMocks = vi.hoisted(() => ({
  getReflections: vi.fn(),
  createReflection: vi.fn(),
}))
// 元认知域 API mock（反思：触发/洞察/时间线，从 MetacognitionPage 迁入）
const metacogMocks = vi.hoisted(() => ({
  getLessons: vi.fn(),
  getReflectionHistory: vi.fn(),
  triggerReflection: vi.fn(),
}))

vi.mock('@/api/modules/growth', () => growthMocks)
vi.mock('@/api/modules/metacognition', () => metacogMocks)
vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'a1' }, currentAgent: { value: { name: 'Test' } } }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import ReflectionPage from '../ReflectionPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      nav: { reflection: '反思', agentreflection: '反思' },
      growth: {
        reflection: '反思日志', general: '通用', insight: '洞察', lesson: '经验',
        mistake: '错误', quality: '质量', insights: '见解', avgQuality: '平均质量',
      },
      reflection: { quality: '质量', keyTakeaways: '关键收获...' },
      metacognition: {
        triggerReflect: '触发反思', reflectDoneWith: '反思完成，产出 {n} 条洞察',
        reflectDoneClean: '反思完成，暂无显著异常', insights: '结构化洞察',
        templateSource: '确定性编译（零 LLM）', reflectionHistory: '反思时间线',
        trigger: '触发器', confidence: '置信度',
      },
      common: {
        refresh: '刷新', create: '创建', total: '总计', type: '类型', description: '描述',
        createdAt: '时间', actions: '操作', open: '查看', search: '搜索', noData: '暂无',
        success: '成功', error: '失败', delete: '删除',
      },
      validation: { required: '必填' },
    },
  },
})

const LESSON = {
  subject: 'bad_tool', operator: 'drift', condition: 'tool=bad_tool', finding: '90% -> 0%',
  recommendation: 'avoid_tool', text: '工具 bad_tool 成功率崩塌', evidence: {},
  source: 'template', confidence: 0.9,
}
const HISTORY = { created_at: '2026-09-05T01:00:00Z', confidence: 0.9, trigger: 'manual', summary: '1 条洞察' }

function contractMocks() {
  growthMocks.getReflections.mockResolvedValue({
    code: 0,
    data: {
      items: [{ id: 'r1', content: '反思日志内容X', category: 'insight', quality_score: 4, insights: ['要点'], created_at: '2026-09-05T00:00:00Z' }],
      total: 1,
    },
  })
  metacogMocks.getLessons.mockResolvedValue({ code: 0, data: { items: [LESSON], total: 1 } })
  metacogMocks.getReflectionHistory.mockResolvedValue({ code: 0, data: { items: [HISTORY], total: 1 } })
  metacogMocks.triggerReflection.mockResolvedValue({
    code: 0,
    data: { trigger: 'manual', lessons: [LESSON], observations: [], confidence: 0.9, summary: 'ok' },
  })
}

// ant-tabs 轻 stub：tab 标签文本必须真实渲染（data-tab 透传），断言才有意义
// GlassCard stub 渲染 title（卡片标题断言需要）；a-table 未注册，数据走 vm 断言
const globalStubs = {
  GlassCard: { props: ['title'], template: '<div class="glass-card-stub"><span class="card-title">{{ title }}</span><slot name="extra"/><slot/></div>' },
  GlassButton: { template: '<button><slot/></button>' },
  'a-tabs': { template: '<div class="ant-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
}

describe('ReflectionPage 反思|反思日志 双页签契约', () => {
  beforeEach(() => {
    contractMocks()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  const mountPage = async () => {
    const wrapper = mount(ReflectionPage, {
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await flushPromises()
    return wrapper
  }

  it('页面渲染两个页签：反思 | 反思日志', async () => {
    const wrapper = await mountPage()
    const tabNames = wrapper.findAll('.ant-tab-pane').map((p) => p.attributes('data-tab'))
    expect(tabNames).toContain('反思')
    expect(tabNames).toContain('反思日志')
  })

  it('不再渲染成对页签（元认知回归独立页面，页面内自洽）', async () => {
    const wrapper = await mountPage()
    expect(wrapper.find('.nr-page-tabs').exists()).toBe(false)
  })

  it('反思页签承载反思行为：触发反思按钮 + 结构化洞察 + 反思时间线', async () => {
    const wrapper = await mountPage()
    const reflectPane = wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === '反思')!
    expect(reflectPane.text()).toContain('触发反思')
    expect(reflectPane.text()).toContain('结构化洞察')
    expect(reflectPane.text()).toContain('反思时间线')
    // 洞察与时间线真数据渲染
    expect(reflectPane.text()).toContain('工具 bad_tool 成功率崩塌')
    const vm = wrapper.vm as any
    expect(vm.history).toHaveLength(1)
    expect(vm.history[0].trigger).toBe('manual')
    expect(vm.lessons).toHaveLength(1)
  })

  it('反思日志页签承载 /growth/reflection 日志列表', async () => {
    const wrapper = await mountPage()
    const logPane = wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === '反思日志')!
    expect(logPane.text()).toContain('创建')
    // a-table 未注册（bodyCell 交给 antd），日志数据经 vm 断言
    const vm = wrapper.vm as any
    expect(vm.reflections).toHaveLength(1)
    expect(vm.reflections[0].content).toBe('反思日志内容X')
    expect(vm.total).toBe(1)
    expect(growthMocks.getReflections).toHaveBeenCalledWith('a1', expect.objectContaining({ page: 1 }))
  })

  it('手动触发反思调用 triggerReflection 并刷新洞察/时间线', async () => {
    const wrapper = await mountPage()
    metacogMocks.getLessons.mockClear()
    metacogMocks.getReflectionHistory.mockClear()
    const reflectBtn = wrapper.findAll('button').find((b) => b.text().includes('触发反思'))!
    await reflectBtn.trigger('click')
    await flushPromises()
    expect(metacogMocks.triggerReflection).toHaveBeenCalledWith('a1')
    expect(metacogMocks.getLessons).toHaveBeenCalled()
    expect(metacogMocks.getReflectionHistory).toHaveBeenCalled()
  })
})
