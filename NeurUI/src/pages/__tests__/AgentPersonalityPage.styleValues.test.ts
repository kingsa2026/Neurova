/**
 * AgentPersonalityPage 风格与价值观编辑卡（2026-11-20）
 *
 * 背景：PUT /growth/personality 契约早已有 communication_style/decision_style/values
 * 三字段（PersonalityUpdate），后端 compilePersonalityTraitsSection 也会把它们编译进
 * system prompt 人格段，但个性页签从未暴露编辑入口——用户改不了，字段恒为 GET 展示
 * 默认值。本文件钉住编辑卡契约：
 *  1. 服务端三字段回读展示（枚举走 personality.* 中文标签，价值观平铺 tag）；
 *  2. 保存整卡三字段齐发 PUT，回读逐字段校验，一致才报成功；
 *  3. 回读不一致 → 报错 + 校验提示 + 服务端值回刷（不谎报成功）；
 *  4. 价值观输入：空串/重复不添加，上限 12 条（对齐后端人格段编译上界）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import type { DOMWrapper } from '@vue/test-utils'
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
  getEmotionSummary: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  getEmotionTimeline: vi.fn().mockResolvedValue({ code: 0, data: { points: [] } }),
}))

vi.mock('@/api/modules/growth', () => ({
  getMotivation: vi.fn().mockResolvedValue({ code: 0, data: null }),
  getPersonality: vi.fn().mockResolvedValue({ code: 0, data: null }),
  updatePersonality: vi.fn().mockResolvedValue({ code: 0, data: null }),
  evolvePersonality: vi.fn().mockResolvedValue({ code: 0, data: null }),
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
import { getPersonality, updatePersonality } from '@/api/modules/growth'

const serverProfile = {
  agent_id: 'a1',
  traits: { openness: 0.7, conscientiousness: 0.6, extraversion: 0.5, agreeableness: 0.8, neuroticism: 0.3, creativity: 0.65 },
  values: ['诚实', '严谨'],
  communication_style: 'direct',
  decision_style: 'collaborative',
}

const zhMessages = {
  nav: { persona: '人格', emotion: '情绪', personality: '个性' },
  common: { refresh: '刷新', edit: '编辑', cancel: '取消', save: '保存', success: '操作成功', error: '操作失败', noData: '暂无数据', updated: '更新于' },
  emotion: { title: '情绪', analysis: '情绪分析', share: '占比 ', entries: '条', neutral: '中性', joy: '开心', timelineTitle: '情绪变化时间轴', timelineAxisHint: '', range24h: '', range7d: '', range30d: '', range90d: '' },
  growth: { motivation: '动力状态', personality: '个性档案', traits: '特质', evolve: '进化' },
  personality: {
    openness: '开放性', conscientiousness: '尽责性', extraversion: '外向性',
    agreeableness: '宜人性', neuroticism: '神经质', creativity: '创造力',
    emptyHint: '尚未建立个性档案', emptyAction: '写入默认特质',
    verifyFailed: '保存失败：服务端未返回回读值', verifyMismatch: '保存已提交，但回读值与写入值不一致，请刷新重试',
    styleValuesCard: '风格与价值观', communicationStyle: '沟通风格', decisionStyle: '决策风格',
    values: '价值观', valuesPlaceholder: '输入价值观后添加', valuesAdd: '添加',
    valuesMaxHint: '最多 12 条（与提示词人格段上界一致）',
    balanced: '均衡', direct: '直接', warm: '亲和', concise: '简洁', formal: '正式', humorous: '幽默',
    analytical: '分析型', intuitive: '直觉型', collaborative: '协作型', decisive: '果断型', cautious: '谨慎型',
  },
}

const globalStubs = {
  GlassPanel: { props: ['variant'], template: '<div class="glass-panel"><slot/></div>' },
  GlassCard: { props: ['title'], template: '<div class="glass-card"><h4 class="card-title">{{title}}</h4><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  GlassStatCard: { props: ['label', 'value', 'emoji'], template: '<div class="glass-stat"></div>' },
  'a-tabs': { template: '<div><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{description}}</div>' },
  'a-progress': { props: ['percent'], template: '<div/>' },
  'a-slider': { props: ['value'], template: '<div class="slider-stub"/>' },
  'a-select': {
    props: ['value', 'options', 'placeholder', 'disabled'],
    emits: ['update:value'],
    template: '<div class="select-stub"><button v-for="o in (options || [])" :key="o.value" class="select-opt" :data-value="o.value" @click="$emit(\'update:value\', o.value)">{{ o.label }}</button></div>',
  },
  'a-tag': {
    // Boolean 型声明：裸属性 closable 才会收到 true（对齐 antdv 真 Tag 的 prop 行为）
    props: { color: String, closable: Boolean, disabled: Boolean },
    emits: ['close'],
    template: '<span class="value-tag"><slot/><button v-if="closable" class="tag-close" @click="$emit(\'close\')">×</button></span>',
  },
  'a-input': {
    props: ['value', 'placeholder', 'disabled'],
    emits: ['update:value', 'pressEnter'],
    template: '<input class="values-input" :value="value" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:value\', $event.target.value)" @keydown.enter="$emit(\'pressEnter\')" />',
  },
  VChart: { props: ['option'], template: '<div class="vchart-stub"/>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhMessages } })
  return mount(AgentPersonalityPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

function styleCard(wrapper: ReturnType<typeof mount>) {
  const card = wrapper.findAll('.glass-card').find((c) => c.find('.card-title').text() === '风格与价值观')
  expect(card, '个性页签应有「风格与价值观」编辑卡').toBeTruthy()
  return card!
}

async function clickCardEdit(card: DOMWrapper<Element>) {
  const editBtn = card.findAll('.glass-btn').find((b) => b.text() === '编辑')
  expect(editBtn, '非编辑态应有编辑按钮').toBeTruthy()
  await editBtn!.trigger('click')
}

async function clickCardSave(card: DOMWrapper<Element>) {
  const saveBtn = card.findAll('.glass-btn').find((b) => b.text() === '保存')
  expect(saveBtn, '编辑态应有保存按钮').toBeTruthy()
  vi.mocked(updatePersonality).mockClear()
  await saveBtn!.trigger('click')
  await flushPromises()
}

describe('AgentPersonalityPage 风格与价值观编辑卡', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getPersonality).mockResolvedValue({
      code: 0, message: 'success', data: { ...serverProfile },
    } as any)
  })

  it('服务端 communication_style/decision_style/values 回读展示（枚举中文标签 + 价值观 tag）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const card = styleCard(wrapper)
    const text = card.text()
    expect(text, '沟通风格字段名').toContain('沟通风格')
    expect(text, '决策风格字段名').toContain('决策风格')
    expect(text, '价值观字段名').toContain('价值观')
    // 枚举以 personality.* 中文标签展示，而非后端原文
    expect(text, '沟通风格中文标签').toContain('直接')
    expect(text, '决策风格中文标签').toContain('协作型')
    expect(card.findAll('.value-tag').map((t) => t.text().replace('×', '')), '价值观平铺').toEqual(['诚实', '严谨'])
  })

  it('编辑后保存：PUT 整卡三字段齐发，回读一致 → 成功并退出编辑态', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const card = styleCard(wrapper)
    await clickCardEdit(card)

    // 改沟通风格 direct → warm；加一条价值观；删一条价值观
    const warmOpt = card.findAll('.select-opt').find((o) => o.text() === '亲和')
    expect(warmOpt, '沟通风格应提供 warm 选项').toBeTruthy()
    await warmOpt!.trigger('click')
    const input = card.find('input.values-input')
    await input.setValue('勇敢')
    await card.findAll('.glass-btn').find((b) => b.text() === '添加')!.trigger('click')
    const firstTagClose = card.findAll('.value-tag .tag-close')[0]
    await firstTagClose.trigger('click')

    const expected = { communication_style: 'warm', decision_style: 'collaborative', values: ['严谨', '勇敢'] }
    vi.mocked(updatePersonality).mockResolvedValueOnce({
      code: 0, message: 'success',
      data: { ...serverProfile, ...expected },
    } as any)

    await clickCardSave(card)

    expect(updatePersonality, '三字段整卡齐发').toHaveBeenCalledWith('a1', expected)
    expect(message.success, '回读一致才报成功').toHaveBeenCalledWith('操作成功')
    expect(message.error).not.toHaveBeenCalled()
    expect(card.findAll('.glass-btn').some((b) => b.text() === '保存'), '成功后退出编辑态').toBe(false)
  })

  it('回读与写入不一致 → 报错 + 校验提示 + 服务端值回刷，不谎报成功', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const card = styleCard(wrapper)
    await clickCardEdit(card)
    const warmOpt = card.findAll('.select-opt').find((o) => o.text() === '亲和')
    await warmOpt!.trigger('click')

    vi.mocked(updatePersonality).mockResolvedValueOnce({
      code: 0, message: 'success',
      // 服务端实际落盘仍是旧值（模拟并发覆盖/回读失真）
      data: { ...serverProfile },
    } as any)

    await clickCardSave(card)

    expect(message.success).not.toHaveBeenCalled()
    expect(message.error, '回读不一致必须报错').toHaveBeenCalledWith('操作失败')
    expect(card.text(), '页面展示不一致提示').toContain('回读值与写入值不一致')
    const vm = wrapper.vm as any
    expect(vm.communicationStyle, '应回刷服务端值 direct').toBe('direct')
    expect(vm.valueList, '价值观回刷服务端值').toEqual(['诚实', '严谨'])
  })

  it('价值观输入约束：空串/重复不添加，超 12 条警告且不添加', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const card = styleCard(wrapper)
    await clickCardEdit(card)
    const vm = wrapper.vm as any
    const input = card.find('input.values-input')
    const addBtn = () => card.findAll('.glass-btn').find((b) => b.text() === '添加')!

    await input.setValue('   ')
    await addBtn().trigger('click')
    expect(vm.valueList, '空串不添加').toEqual(['诚实', '严谨'])

    await input.setValue('诚实')
    await addBtn().trigger('click')
    expect(vm.valueList, '重复不添加').toEqual(['诚实', '严谨'])

    const extras = ['v1', 'v2', 'v3', 'v4', 'v5', 'v6', 'v7', 'v8', 'v9', 'v10', 'v11']
    for (const v of extras) {
      await input.setValue(v)
      await addBtn().trigger('click')
    }
    expect(vm.valueList.length, '到 12 条为止').toBe(12)
    vi.mocked(message.warning).mockClear()
    await input.setValue('v12')
    await addBtn().trigger('click')
    expect(vm.valueList.length, '超上限不添加').toBe(12)
    expect(message.warning, '超上限给诚实提示').toHaveBeenCalled()
  })
})
