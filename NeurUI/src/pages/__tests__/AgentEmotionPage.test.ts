/**
 * AgentEmotionPage — 契约对齐防回归测试（2026-09-01）
 *
 * 背景：页面此前消费后端 summary 的 current/categories/history 字段，
 * 而后端实际返回 { total_annotated, emotion_distribution, emotion_weight }
 * —— 字段级别断开，页面任何数据量下都显示"中性/0%/空白"。
 * 本次对齐：
 * 1. fetchEmotion 解析 total_annotated + emotion_distribution →
 *    dominant（数量最多类型）+ 占比 + 总量
 * 2. 类型映射对齐后端 EmotionType 枚举（joy/sadness/...），emoji/标签不再
 *    用 happy/sad 旧键（只有 angry/neutral 对得上的时代）
 * 3. 情绪类型中文名走 i18n（emotion.type.*）
 * 4. 无数据时分类区显示 a-empty（不再留白）；时间线卡移除（后端无 history 契约）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({
    agentId: ref('default'),
    currentAgent: ref({ name: 'Neurova' }),
    agentLoading: ref(false),
  }),
}))

vi.mock('@/api/modules/memory', () => ({
  getEmotionSummary: vi.fn().mockResolvedValue({
    code: 0,
    data: { total_annotated: 3, emotion_distribution: { joy: 2, sadness: 1 } },
    message: 'ok',
  }),
}))

vi.mock('@/api/modules/growth', () => ({
  getMotivation: vi.fn().mockResolvedValue({ code: 0, data: null }),
  getPersonality: vi.fn().mockResolvedValue({ code: 0, data: null }),
}))

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import AgentEmotionPage from '@/pages/AgentEmotionPage.vue'
import { getEmotionSummary } from '@/api/modules/memory'

const zhMessages = {
  common: { refresh: '刷新', error: '失败', noData: '暂无数据', updated: '更新于' },
  emotion: {
    title: '情绪管理',
    analysis: '情绪分析',
    share: '占比 ',
    entries: '条情感标注',
    neutral: '中性',
    type: {
      joy: '开心', sadness: '难过', anger: '生气', fear: '害怕', surprise: '惊讶',
      disgust: '厌恶', trust: '信任', anticipation: '期待', neutral: '中性',
    },
  },
  growth: { motivation: '动力状态', personality: '个性特质' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh: zhMessages } })
  return mount(AgentEmotionPage, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassPanel: { props: ['variant'], template: '<div class="glass-panel"><slot/></div>' },
        GlassCard: { props: ['title'], template: '<div class="glass-card"><h4>{{title}}</h4><slot/></div>' },
        GlassButton: { props: ['loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
        GlassStatCard: { props: ['label', 'value', 'emoji'], template: '<div class="glass-stat"><span class="stat-emoji">{{emoji}}</span><span class="stat-label">{{label}}</span><span class="stat-value">{{value}}</span></div>' },
        'a-spin': { props: ['spinning'], template: '<div class="a-spin"><slot/></div>' },
        'a-empty': { props: ['description'], template: '<div class="a-empty">{{description}}</div>' },
        'a-progress': { props: ['percent'], template: '<div class="a-progress"></div>' },
        'a-tag': { props: ['color'], template: '<span class="a-tag"><slot/></span>' },
      },
    },
  })
}

describe('AgentEmotionPage 契约对齐', () => {
  beforeEach(() => {
    vi.mocked(getEmotionSummary).mockClear()
    vi.mocked(getEmotionSummary).mockResolvedValue({
      code: 0,
      data: { total_annotated: 3, emotion_distribution: { joy: 2, sadness: 1 } },
      message: 'ok',
    })
  })

  it('按 total_annotated/emotion_distribution 渲染主导情绪、占比与总量', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('开心') // 主导情绪类型（dominant=joy）
    expect(text).toContain('67%') // joy 2/3 → 67%
    expect(text).toContain('33%') // sadness 1/3 → 33%
    expect(text).toContain('3')
    expect(text).toContain('条情感标注')
  })

  it('类型映射对齐后端枚举：joy→😊、sadness→😢（不再用 happy/sad 旧键）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()

    const stats = wrapper.findAll('.glass-stat')
    expect(stats.length).toBeGreaterThanOrEqual(2)
    const emojis = stats.map((s) => s.find('.stat-emoji').text())
    expect(emojis).toContain('😊')
    expect(emojis).toContain('😢')
  })

  it('无数据时显示中性 + 分类区 a-empty，不渲染卡片', async () => {
    vi.mocked(getEmotionSummary).mockResolvedValue({
      code: 0,
      data: { total_annotated: 0, emotion_distribution: {} },
      message: 'ok',
    })
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('中性')
    expect(wrapper.findAll('.glass-stat').length).toBe(0)
    expect(wrapper.find('.a-empty').exists()).toBe(true)
  })

  it('请求失败时提示错误但不抛出', async () => {
    vi.mocked(getEmotionSummary).mockRejectedValue(new Error('network'))
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })
})
