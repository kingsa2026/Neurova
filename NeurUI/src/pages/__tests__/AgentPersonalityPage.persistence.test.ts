/**
 * AgentPersonalityPage 个性档案——保存回读校验 + 特质空态引导（2026-09-16）
 *
 * 背景：BE /growth/personality 已收口为 {code,message,data} envelope（envelope
 * 契约见 api/modules/__tests__/personality-envelope-contract.test.ts）。本文件钉两条
 * 新契约：
 *  1. 保存后以 PUT 响应 envelope.data.traits 回读逐键校验——一致才报成功，否则
 *     谎报成功掩盖落盘失败（旧实现恒 message.success）；
 *  2. 服务端从未持久化 traits（traits 空对象）时，个性页签显示空态 + "写入默认
 *     特质"引导，一键 PUT 六维中性默认值——旧实现用内置默认值（70/60/...）冒充
 *     服务端档案。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({
    agentId: ref('a1'),
    currentAgent: ref({ name: 'N' }),
    agentLoading: ref(false),
  }),
}))

vi.mock('@/api/modules/memory', () => ({
  getEmotionSummary: vi.fn(),
}))

vi.mock('@/api/modules/growth', () => ({
  getMotivation: vi.fn().mockResolvedValue({ code: 0, data: null }),
  getPersonality: vi.fn().mockResolvedValue({ code: 0, data: null }),
}))

vi.mock('@/api', () => ({
  request: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import AgentPersonalityPage from '@/pages/AgentPersonalityPage.vue'
import { message } from 'ant-design-vue'
import { request } from '@/api'

const zhMessages = {
  nav: { persona: '人格', emotion: '情绪', personality: '个性' },
  common: { refresh: '刷新', edit: '编辑', cancel: '取消', save: '保存', success: '操作成功', error: '操作失败', noData: '暂无数据', updated: '更新于' },
  emotion: { title: '情绪', analysis: '情绪分析', share: '占比 ', entries: '条', neutral: '中性', joy: '开心' },
  growth: { motivation: '动力状态', personality: '个性档案', traits: '特质', evolve: '进化' },
  personality: {
    openness: '开放性', conscientiousness: '尽责性', extraversion: '外向性',
    agreeableness: '宜人性', neuroticism: '神经质', creativity: '创造力',
    emptyHint: '尚未建立个性档案', emptyAction: '写入默认特质', savingDefaults: '写入中...',
    verifyMismatch: '保存已提交，但回读值与写入值不一致，请刷新重试', verifyFailed: '保存失败：服务端未返回回读值',
  },
}

const globalStubs = {
  GlassPanel: { props: ['variant'], template: '<div class="glass-panel"><slot/></div>' },
  GlassCard: { props: ['title'], template: '<div class="glass-card"><h4>{{title}}</h4><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  GlassStatCard: { props: ['label', 'value', 'emoji'], template: '<div class="glass-stat"></div>' },
  'a-tabs': { template: '<div><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{description}}</div>' },
  'a-progress': { props: ['percent'], template: '<div/>' },
  'a-tag': { props: ['color'], template: '<span><slot/></span>' },
  'a-slider': { props: ['value'], template: '<div class="slider-stub"/>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhMessages } })
  return mount(AgentPersonalityPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

/** 进个性页签的编辑态并点保存 */
async function clickSave(wrapper: ReturnType<typeof mount>) {
  const editBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '编辑')
  await editBtn!.trigger('click')
  const saveBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '保存')
  expect(saveBtn, '编辑态应有保存按钮').toBeTruthy()
  vi.mocked(request.put).mockClear()
  await saveBtn!.trigger('click')
  await flushPromises()
}

describe('AgentPersonalityPage 保存回读校验', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 前置：服务端已有档案（编辑流程存在的前提）；值与滑杆初始一致避免噪声
    vi.mocked(request.get).mockResolvedValue({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: { openness: 0.7, conscientiousness: 0.6, extraversion: 0.5, agreeableness: 0.8, neuroticism: 0.3, creativity: 0.65 }, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)
    vi.mocked(request.post).mockResolvedValue({ data: {} } as any)
  })

  it('PUT 回读 envelope.data.traits 与写入一致 → 成功提示并退出编辑态', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const sent = { openness: 0.7, conscientiousness: 0.6, extraversion: 0.5, agreeableness: 0.8, neuroticism: 0.3, creativity: 0.65 }
    vi.mocked(request.put).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: sent, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)

    await clickSave(wrapper)

    const put = vi.mocked(request.put).mock.calls.find((c) => c[0] === '/growth/personality')
    expect(put, '保存应 PUT /growth/personality').toBeTruthy()
    expect(put![1]).toEqual({ traits: sent })
    expect(message.success, '回读一致才报成功').toHaveBeenCalledWith('操作成功')
    expect(message.error).not.toHaveBeenCalled()
  })

  it('PUT 回读与写入不一致 → 报错 + 展示校验提示条，不谎报成功', async () => {
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(request.put).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: { openness: 0.1 }, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)

    await clickSave(wrapper)

    expect(message.success).not.toHaveBeenCalled()
    expect(message.error, '回读不一致必须报错').toHaveBeenCalledWith('操作失败')
    const pane = wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === '个性')!
    expect(pane.text(), '页面展示不一致提示').toContain('回读值与写入值不一致')
    expect(wrapper.find('.traits-verify-tip').exists()).toBe(true)
  })

  it('PUT 未返回 envelope.data（旧格式/网关截断）→ 报错提示，不谎报成功', async () => {
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(request.put).mockResolvedValueOnce({} as any)

    await clickSave(wrapper)

    expect(message.success).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalledWith('操作失败')
  })

  it('回读成功后列表以服务端值为准（PUT 响应值回刷 traitList）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const serverTraits = { openness: 0.42, conscientiousness: 0.6, extraversion: 0.5, agreeableness: 0.8, neuroticism: 0.3, creativity: 0.65 }
    vi.mocked(request.put).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: serverTraits, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)

    await clickSave(wrapper)

    const vm = wrapper.vm as any
    const openness = vm.traitList.find((t: any) => t.key === 'openness')
    expect(openness.value, '列表应回读服务端值 0.42 而非本地编辑值 0.7').toBe(0.42)
    expect(openness.percent).toBe(42)
  })
})

describe('AgentPersonalityPage 特质空态引导', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(request.post).mockResolvedValue({ data: {} } as any)
  })

  it('服务端无持久化 traits → 个性页签显示空态引导而非默认值假档案', async () => {
    vi.mocked(request.get).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: {}, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)
    const wrapper = mountPage()
    await flushPromises()

    const pane = wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === '个性')!
    expect(pane.text(), '空态提示').toContain('尚未建立个性档案')
    expect(pane.text(), '引导按钮').toContain('写入默认特质')
  })

  it('点击"写入默认特质" → PUT 六维中性默认值（0.5），成功后退出空态', async () => {
    vi.mocked(request.get).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: {}, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)
    const defaults = { openness: 0.5, conscientiousness: 0.5, extraversion: 0.5, agreeableness: 0.5, neuroticism: 0.5, creativity: 0.5 }
    vi.mocked(request.put).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: defaults, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)

    const wrapper = mountPage()
    await flushPromises()

    const writeBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '写入默认特质')
    expect(writeBtn, '空态应有写入默认特质按钮').toBeTruthy()
    await writeBtn!.trigger('click')
    await flushPromises()

    const put = vi.mocked(request.put).mock.calls.find((c) => c[0] === '/growth/personality')
    expect(put, '应 PUT /growth/personality').toBeTruthy()
    expect(put![1]).toEqual({ traits: defaults })
    expect(put![2]).toEqual({ params: { agent_id: 'a1' } })
    expect(message.success).toHaveBeenCalledWith('操作成功')
    // 成功后空态消失（回读已非空）
    const pane = wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === '个性')!
    expect(pane.text()).not.toContain('尚未建立个性档案')
  })

  it('写入默认值回读不一致 → 报错并保持空态（不假成功）', async () => {
    vi.mocked(request.get).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: {}, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)
    vi.mocked(request.put).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: {}, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)

    const wrapper = mountPage()
    await flushPromises()

    const writeBtn = wrapper.findAll('.glass-btn').find((b) => b.text() === '写入默认特质')
    await writeBtn!.trigger('click')
    await flushPromises()

    expect(message.success).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalledWith('操作失败')
    const pane = wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === '个性')!
    expect(pane.text(), '回读仍空 → 空态保持').toContain('尚未建立个性档案')
  })

  it('服务端有持久化 traits → 无空态引导，滑杆显示服务端值', async () => {
    vi.mocked(request.get).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { agent_id: 'a1', traits: { openness: 0.8 }, values: [], communication_style: 'balanced', decision_style: 'analytical' },
    } as any)
    const wrapper = mountPage()
    await flushPromises()

    const pane = wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === '个性')!
    expect(pane.text()).not.toContain('尚未建立个性档案')
    const vm = wrapper.vm as any
    expect(vm.traitList.find((t: any) => t.key === 'openness').value).toBe(0.8)
  })
})
