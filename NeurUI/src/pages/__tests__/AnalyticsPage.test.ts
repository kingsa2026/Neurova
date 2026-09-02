/**
 * AnalyticsPage — 真实数据契约防回归测试（2026-09-02）
 *
 * 背景：AnalyticsPage 曾无路由（/analytics 未注册，Dashboard"查看分析"404），
 * 后端 /analytics 四端点是内存 stub + 模拟数据 + 字段契约错位。
 * 本测试锁定前端契约（与 analytics.ts 类型 + 后端新实现对齐）：
 * 1. usage tab：对话=by_agent 会话合计、Token/调用=记账器、智能体=by_agent 数、趋势=按天序列
 * 2. performance tab：平均响应/P95/吞吐/错误率 + 端点表（切换 tab 拉对应接口）
 * 3. behavior tab：top_tools 渲染，无源项（skills/patterns）走空态
 * 4. errors tab：总错误数 + by_type 表
 * 5. 时间范围切换透传 period 参数
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/analytics', () => ({
  getUsageAnalytics: vi.fn(),
  getPerformanceAnalytics: vi.fn(),
  getBehaviorAnalytics: vi.fn(),
  getErrorAnalytics: vi.fn(),
}))

import AnalyticsPage from '@/pages/AnalyticsPage.vue'
import { getUsageAnalytics, getPerformanceAnalytics, getBehaviorAnalytics, getErrorAnalytics } from '@/api/modules/analytics'

const messages = {
  common: { noData: '暂无数据', error: '加载失败' },
  dashboard: {
    totalConversations: '对话总数',
    totalTokens: 'Token 用量',
    totalCalls: 'API 调用',
    totalAgents: '智能体总数',
  },
  system: { analytics: '数据分析', usage: '用量', performance: '性能', errors: '错误' },
  analytics: {
    day: '日', week: '周', month: '月',
    usageOverTime: '使用趋势',
    avgResponse: '平均响应', p95Latency: 'P95 延迟', throughput: '吞吐量', errorRate: '错误率',
    responseTimes: '响应时间',
    behavior: '行为', popularFeatures: '热门功能', userPaths: '用户路径',
    totalErrors: '总错误数', topErrors: '常见错误',
    endpoint: '端点', avgMs: '平均 (ms)', p95Ms: 'P95 (ms)', calls: '调用次数',
    code: '状态码', errorMessage: '错误信息', count: '计数',
  },
}

const stubs = {
  GlassPanel: { props: ['variant', 'padding', 'radius'], template: '<div class="glass-panel"><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], template: '<button class="glass-btn"><slot/></button>' },
  GlassStatCard: { props: ['label', 'value'], template: '<div class="glass-stat"><span class="stat-label">{{ label }}</span><span class="stat-value">{{ value }}</span></div>' },
  GlassCard: { props: ['title', 'variant', 'radius'], template: '<div class="glass-card"><div v-if="title" class="gc-title">{{ title }}</div><slot/></div>' },
  'a-radio-group': { props: ['value'], emits: ['change', 'update:value'], template: '<div class="a-radio-group"><span class="range-sim" data-value="day" @click="$emit(\'update:value\', \'day\'); $emit(\'change\', \'day\')">day</span><slot/></div>' },
  'a-radio-button': { props: ['value'], template: '<span class="a-radio-btn">{{ value }}</span>' },
  'a-tabs': { props: ['activeKey'], emits: ['change', 'update:activeKey'], template: '<div class="a-tabs"><div class="tab-sims"><span class="tab-sim" data-tab="performance" @click="$emit(\'update:activeKey\', \'performance\'); $emit(\'change\', \'performance\')">perf</span><span class="tab-sim" data-tab="behavior" @click="$emit(\'update:activeKey\', \'behavior\'); $emit(\'change\', \'behavior\')">behav</span><span class="tab-sim" data-tab="errors" @click="$emit(\'update:activeKey\', \'errors\'); $emit(\'change\', \'errors\')">err</span></div><slot/></div>' },
  'a-tab-pane': { props: ['key', 'tab'], template: '<div class="a-tab-pane" :data-tab="key"><slot/></div>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-table': { props: ['columns', 'dataSource'], template: '<div class="a-table"><div class="a-row" v-for="(row, i) in dataSource" :key="i"><span v-for="c in columns" :key="c.key" class="a-td" :data-col="c.key">{{ row[c.dataIndex ?? c.key] ?? "" }}</span></div></div>' },
  'a-list': { props: ['dataSource'], template: '<div class="a-list"><slot/><div class="a-item" v-for="(row, i) in dataSource" :key="i">{{ row.name ?? row.path }} ({{ row.count ?? row.usage_count }})</div><div v-if="!dataSource.length" class="a-empty">暂无数据</div></div>' },
  'a-list-item': { template: '<div class="a-li"><slot/></div>' },
  'a-tag': { props: ['color'], template: '<span class="a-tag"><slot/></span>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(AnalyticsPage, { global: { plugins: [i18n], stubs } })
}

describe('AnalyticsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('usage tab renders real aggregates from backend contract', async () => {
    vi.mocked(getUsageAnalytics).mockResolvedValue({
      period: 'week',
      total_requests: 4,
      total_tokens: 150,
      avg_latency_ms: 200,
      by_agent: [
        { agent_id: 'default', name: 'default', requests: 2 },
        { agent_id: 'alt', name: 'alt', requests: 1 },
      ],
      by_model: [{ model: 'gpt-4o', requests: 3, tokens: 140 }],
      daily_trend: [
        { date: '09-01', requests: 1, tokens: 1 },
        { date: '09-02', requests: 2, tokens: 8 },
      ],
    } as never)
    const wrapper = mountPage()
    await flushPromises()

    const values = wrapper.findAll('.stat-value').map((w) => w.text())
    // 对话=by_agent 会话合计(3)、Token=150、API 调用=4、智能体=2
    expect(values[0]).toBe('3')
    expect(values[1]).toBe('150')
    expect(values[2]).toBe('4')
    expect(values[3]).toBe('2')
    expect(wrapper.text()).toContain('使用趋势')
  })

  it('switching tab fetches endpoint list and renders latency cards', async () => {
    vi.mocked(getUsageAnalytics).mockResolvedValue({ period: 'week', daily_trend: [], by_agent: [], by_model: [] } as never)
    vi.mocked(getPerformanceAnalytics).mockResolvedValue({
      period: 'week',
      avg_latency_ms: 200,
      p95_latency_ms: 300,
      throughput_rps: 0.04,
      error_rate: 25,
      by_endpoint: [{ endpoint: 'p-openai:gpt-4o', avg_ms: 200, count: 3 }],
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('.tab-sim[data-tab="performance"]').trigger('click')
    await flushPromises()

    expect(getPerformanceAnalytics).toHaveBeenCalledWith({ period: 'week' })
    const statTexts = wrapper.findAll('.stat-value').map((w) => w.text())
    expect(statTexts).toContain('200ms')
    expect(statTexts).toContain('300ms')
    expect(statTexts).toContain('25%')
    expect(wrapper.text()).toContain('p-openai:gpt-4o')
  })

  it('time range passes period param through to api', async () => {
    vi.mocked(getUsageAnalytics).mockResolvedValue({ period: 'day', daily_trend: [], by_agent: [], by_model: [] } as never)
    const wrapper = mountPage()
    await flushPromises()

    const range = wrapper.find('.range-sim')
    await range.trigger('click')
    await flushPromises()

    expect(getUsageAnalytics).toHaveBeenCalledWith({ period: 'day' })
  })

  it('behavior tab shows real tools and empty state for no-source items', async () => {
    vi.mocked(getUsageAnalytics).mockResolvedValue({ period: 'week', daily_trend: [], by_agent: [], by_model: [] } as never)
    vi.mocked(getBehaviorAnalytics).mockResolvedValue({
      period: 'week',
      top_tools: [{ name: 'web_search', usage_count: 5, success_count: 4, avg_duration_ms: 120 }],
      top_skills: [],
      conversation_patterns: [],
      peak_hours: [{ hour: 10, requests: 2 }],
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('.tab-sim[data-tab="behavior"]').trigger('click')
    await flushPromises()

    expect(getBehaviorAnalytics).toHaveBeenCalled()
    expect(wrapper.text()).toContain('web_search')
    expect(wrapper.text()).toContain('5')
  })

  it('errors tab renders total errors and by-type rows', async () => {
    vi.mocked(getUsageAnalytics).mockResolvedValue({ period: 'week', daily_trend: [], by_agent: [], by_model: [] } as never)
    vi.mocked(getErrorAnalytics).mockResolvedValue({
      period: 'week',
      total_errors: 2,
      error_rate: 50,
      by_type: [{ type: 'p-openai', count: 2 }],
      by_endpoint: [],
      recent_errors: [],
    } as never)

    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('.tab-sim[data-tab="errors"]').trigger('click')
    await flushPromises()

    expect(getErrorAnalytics).toHaveBeenCalledWith({ period: 'week' })
    expect(wrapper.text()).toContain('总错误数')
    expect(wrapper.text()).toContain('p-openai')
  })
})
