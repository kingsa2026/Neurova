/**
 * UsageStatsPage — Token 持久化使用统计看板防回归测试（2026-09-03）
 *
 * 背景：token 记账原为进程内内存单例、重启归零。持久化历史（usage_history SQLite）
 * 上线后，本页从 /v1/stats/usage-overview 拉取：KPI 卡（累计/峰值/最长会话时长/
 * 连续天数）+ Token 活动热力图（echarts heatmap）+ 按模型每日趋势折线。
 *
 * 契约（防回归）：
 * 1. 5 张 KPI 卡渲染真实值（格式化友好显示）
 * 2. 热力图 + 趋势图渲染（series 数 = 模型数）
 * 3. 时间范围切换（近 7/30 日）→ 重新请求 trend_days
 * 4. 空库零态渲染空提示而非崩溃
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/stats', () => ({
  getUsageOverview: vi.fn(),
}))

import UsageStatsPage from '@/pages/UsageStatsPage.vue'
import { getUsageOverview } from '@/api/modules/stats'

const messages = {
  common: {
    noData: '暂无数据',
    error: '加载失败',
    loading: '加载中',
  },
  nav: { usageStats: '使用统计' },
  usageStats: {
    title: '使用统计',
    totalTokens: '累计 Token 数',
    peakTokens: '峰值 Token 数',
    longestSession: '最长聊天时长',
    currentStreak: '当前连续天数',
    longestStreak: '最长连续天数',
    tokenActivity: 'Token 活动',
    dailyTokenTrend: '每日 Token 趋势',
    last7Days: '近 7 日',
    last30Days: '近 30 日',
    daily: '每日',
    weekly: '每周',
    cumulative: '累计',
    allUsers: '全部用户',
    myUsage: '我的用量',
    days: '天',
    seconds: '秒',
    minutes: '分钟',
    hours: '小时',
  },
}

const stubs = {
  GlassPanel: { template: '<div class="glass-panel"><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  VChart: {
    props: ['option'],
    template:
      '<div class="vchart-stub" :data-series="option?.series?.length ?? -1" :data-has-option="option ? 1 : 0" />',
  },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
  'a-radio-group': { props: ['value'], emits: ['change'], template: '<div class="a-radio-group"><slot/></div>' },
  'a-radio-button': {
    props: ['value'],
    emits: ['click'],
    template: '<button class="a-radio-button" :data-value="value" @click="$emit(\'click\')"><slot/></button>',
  },
  'a-tabs': { template: '<div><slot/></div>' },
  'a-tab-pane': { template: '<div><slot/></div>' },
}

function mockOverview(overrides: Record<string, any> = {}) {
  const today = new Date()
  const yesterday = new Date(today.getTime() - 86400_000)
  const fmt = (d: Date) => d.toISOString().slice(0, 10)
  return {
    scope: 'user',
    summary: {
      total_tokens: 123456,
      total_calls: 30,
      peak_daily_tokens: 20000,
      peak_daily_date: fmt(yesterday),
      longest_session_seconds: 9000,
      current_streak_days: 5,
      longest_streak_days: 11,
      active_days: 20,
    },
    heatmap: [
      { date: fmt(yesterday), tokens: 20000, calls: 8 },
      { date: fmt(today), tokens: 3456, calls: 5 },
    ],
    trends: [
      { date: fmt(yesterday), model: 'm1', tokens: 15000 },
      { date: fmt(today), model: 'm1', tokens: 2000 },
      { date: fmt(today), model: 'm2', tokens: 1456 },
    ],
    by_model: [
      { model: 'm1', tokens: 17000, calls: 20 },
      { model: 'm2', tokens: 1456, calls: 10 },
    ],
    ...overrides,
  }
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(UsageStatsPage, { global: { plugins: [i18n], stubs } })
}

describe('UsageStatsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getUsageOverview).mockResolvedValue(mockOverview() as never)
  })

  it('renders five KPI cards with formatted values', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('使用统计')
    expect(text).toContain('累计 Token 数')
    expect(text).toContain('123.5K') // 123456 → K 缩写
    expect(text).toContain('峰值 Token 数')
    expect(text).toContain('20.0K') // peak daily
    expect(text).toContain('最长聊天时长')
    expect(text).toContain('2.5 小时') // 9000s formatted
    expect(text).toContain('当前连续天数')
    expect(text).toContain('5 天')
    expect(text).toContain('最长连续天数')
    expect(text).toContain('11 天')
    expect(text).toContain('我的用量') // scope=user label
  })

  it('renders heatmap chart and per-model trend series', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const charts = wrapper.findAll('.vchart-stub')
    expect(charts.length).toBeGreaterThanOrEqual(2)
    // 趋势图 series 数 = 模型数（2），热力图 1 个 series
    const seriesCounts = charts.map((w) => Number(w.attributes('data-series')))
    expect(seriesCounts).toContain(2)
  })

  it('refetches with trend_days=30 when switching range', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(getUsageOverview).toHaveBeenCalledWith(expect.objectContaining({ trend_days: 7 }))

    await wrapper.find('.a-radio-button[data-value="30"]').trigger('click')
    await flushPromises()
    expect(getUsageOverview).toHaveBeenLastCalledWith(expect.objectContaining({ trend_days: 30 }))
  })

  it('shows empty state instead of crashing on zero data', async () => {
    vi.mocked(getUsageOverview).mockResolvedValue({
      scope: 'global',
      summary: {
        total_tokens: 0,
        total_calls: 0,
        peak_daily_tokens: 0,
        peak_daily_date: null,
        longest_session_seconds: 0,
        current_streak_days: 0,
        longest_streak_days: 0,
        active_days: 0,
      },
      heatmap: [],
      trends: [],
      by_model: [],
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('全部用户') // scope=global
    expect(wrapper.find('.a-empty').exists()).toBe(true)
  })
})
