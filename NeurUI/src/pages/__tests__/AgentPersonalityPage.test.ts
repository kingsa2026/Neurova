/**
 * AgentPersonalityPage — 人格页双页签契约（2026-09-06）
 *
 * 背景：情绪页与个性页合并为「人格」入口（菜单 nav.persona），
 * 页面改为页内双页签：情绪（AgentEmotionPage 内容迁入）| 个性（原特质雷达/滑杆）。
 * 原两页契约全部保留：
 *  - 情绪：summary 契约 { total_annotated, emotion_distribution } → dominant/占比/总量；
 *    类型映射对齐后端 EmotionType 枚举（emoji/中文标签 i18n）；空态 a-empty；失败不抛出
 *  - 个性：特质名必须走 i18n（personality.*），随 locale 切换
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({
    agentId: ref('default'),
    currentAgent: ref({ name: 'Neurova' }),
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

// 个性页签的 request（axios 包装）
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
import { getEmotionSummary } from '@/api/modules/memory'
import { request } from '@/api'

const zhMessages = {
  nav: { persona: '人格', emotion: '情绪', personality: '个性' },
  common: { refresh: '刷新', edit: '编辑', cancel: '取消', save: '保存', success: '操作成功', error: '操作失败', noData: '暂无数据', updated: '更新于' },
  emotion: {
    title: '情绪管理',
    analysis: '情绪分析',
    share: '占比 ',
    entries: '条情感标注',
    neutral: '中性',
    joy: '开心', sadness: '难过', anger: '生气', fear: '害怕', surprise: '惊讶',
    disgust: '厌恶', trust: '信任', anticipation: '期待',
  },
  growth: { motivation: '动力状态', personality: '个性档案', traits: '特质', evolve: '进化' },
  personality: {
    title: '人格特征',
    openness: '开放性',
    conscientiousness: '尽责性',
    extraversion: '外向性',
    agreeableness: '宜人性',
    neuroticism: '神经质',
    creativity: '创造力',
  },
}

const enMessages = {
  nav: { persona: 'Personality', emotion: 'Emotion', personality: 'Personality' },
  common: { refresh: 'Refresh', edit: 'Edit', cancel: 'Cancel', save: 'Save', success: 'Success', error: 'Error', noData: 'No data', updated: 'Updated' },
  emotion: { title: 'Emotion', analysis: 'Emotion Analysis', share: 'Share ', entries: 'entries', neutral: 'Neutral' },
  growth: { motivation: 'Motivation', personality: 'Personality Profile', traits: 'Traits', evolve: 'Evolve' },
  personality: {
    title: 'Personality',
    openness: 'Openness',
    conscientiousness: 'Conscientiousness',
    extraversion: 'Extraversion',
    agreeableness: 'Agreeableness',
    neuroticism: 'Neuroticism',
    creativity: 'Creativity',
  },
}

// ant-tabs 轻 stub：tab 标签经 data-tab 透传；未注册的 a-* 交给全局缺失渲染
const globalStubs = {
  GlassPanel: { props: ['variant'], template: '<div class="glass-panel"><slot/></div>' },
  GlassCard: { props: ['title'], template: '<div class="glass-card"><h4>{{title}}</h4><slot/><slot name="footer"/></div>' },
  GlassButton: { props: ['loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  GlassStatCard: { props: ['label', 'value', 'emoji'], template: '<div class="glass-stat"><span class="stat-emoji">{{emoji}}</span><span class="stat-label">{{label}}</span><span class="stat-value">{{value}}</span></div>' },
  'a-tabs': { template: '<div class="ant-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['tab'], template: '<div class="ant-tab-pane" :data-tab="tab"><slot/></div>' },
  'a-spin': { props: ['spinning'], template: '<div class="a-spin"><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{description}}</div>' },
  'a-progress': { props: ['percent'], template: '<div class="a-progress"></div>' },
  'a-tag': { props: ['color'], template: '<span class="a-tag"><slot/></span>' },
  'a-slider': { props: ['value'], template: '<div class="slider-stub"/>' },
}

function mountPage(locale = 'zh-CN', messages: Record<string, any> = zhMessages) {
  const i18n = createI18n({ legacy: false, locale, messages: { [locale]: messages } })
  return mount(AgentPersonalityPage, { global: { plugins: [i18n], stubs: globalStubs } })
}

const findPane = (wrapper: ReturnType<typeof mount>, tab: string) =>
  wrapper.findAll('.ant-tab-pane').find((p) => p.attributes('data-tab') === tab)

describe('AgentPersonalityPage 人格双页签契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(request.get).mockResolvedValue({ data: {} } as any)
    vi.mocked(getEmotionSummary).mockResolvedValue({
      code: 0,
      data: { total_annotated: 3, emotion_distribution: { joy: 2, sadness: 1 } },
      message: 'ok',
    } as any)
  })

  it('页面渲染两个页签：情绪 | 个性', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    const tabNames = wrapper.findAll('.ant-tab-pane').map((p) => p.attributes('data-tab'))
    expect(tabNames).toContain('情绪')
    expect(tabNames).toContain('个性')
  })

  it('页面标题为人格（合并入口，菜单 nav.persona 同名）', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.find('.page-title').text()).toBe('人格')
  })

  it('情绪页签按 summary 契约渲染主导情绪、占比与总量', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    const pane = findPane(wrapper, '情绪')!
    const text = pane.text()
    expect(text).toContain('开心') // dominant=joy
    expect(text).toContain('67%') // joy 2/3
    expect(text).toContain('33%') // sadness 1/3
    expect(text).toContain('3')
    expect(text).toContain('条情感标注')
  })

  it('情绪类型映射对齐后端枚举：joy→😊、sadness→😢', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    const emojis = wrapper.findAll('.glass-stat').map((s) => s.find('.stat-emoji').text())
    expect(emojis).toContain('😊')
    expect(emojis).toContain('😢')
  })

  it('情绪无数据时显示中性 + 分类区 a-empty，不渲染卡片', async () => {
    vi.mocked(getEmotionSummary).mockResolvedValue({
      code: 0,
      data: { total_annotated: 0, emotion_distribution: {} },
      message: 'ok',
    } as any)
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('中性')
    expect(wrapper.findAll('.glass-stat').length).toBe(0)
    expect(wrapper.find('.a-empty').exists()).toBe(true)
  })

  it('情绪请求失败时提示错误但不抛出', async () => {
    vi.mocked(getEmotionSummary).mockRejectedValue(new Error('network'))
    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('个性页签渲染特质名（i18n 中文）', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    const pane = findPane(wrapper, '个性')!
    const names = pane.findAll('.trait-name').map((n) => n.text())
    expect(names.join(',')).toBe('开放性,尽责性,外向性,宜人性,神经质,创造力')
    expect(names.join(',')).not.toContain('Openness')
  })

  it('en-US 下 trait 名显示英文（多语言随 locale 切换）', async () => {
    const wrapper = await mountPage('en-US', enMessages)
    await flushPromises()
    const names = wrapper.findAll('.trait-name').map((n) => n.text())
    expect(names.join(',')).toBe('Openness,Conscientiousness,Extraversion,Agreeableness,Neuroticism,Creativity')
  })

  it('个性页签两卡左右分区：radar 卡与特质卡为 personality-grid 同级子项', async () => {
    const wrapper = await mountPage()
    await flushPromises()
    const pane = findPane(wrapper, '个性')!
    const grid = pane.find('.personality-grid')
    expect(grid.exists()).toBe(true)
    const cards = grid.findAll(':scope > .glass-card')
    expect(cards).toHaveLength(2)
    // 布局：网格双列（窄屏回退单列由媒体查询负责）
    const sfc = readFileSync(resolve(process.cwd(), 'src/pages/AgentPersonalityPage.vue'), 'utf-8')
    const rule = sfc.match(/\.personality-grid\s*\{[^}]*\}/)
    expect(rule).toBeTruthy()
    expect(rule![0]).toContain('grid-template-columns')
  })
})
