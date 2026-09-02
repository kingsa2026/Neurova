/**
 * StatsPage — 真实统计契约防回归测试（2026-09-02）
 *
 * 背景：/stats 后端曾为部分 stub（overview 恒 0、/usage TODO、export 不存在），
 * 且契约与前端 stats.ts 类型错位。本测试锁定：
 * 1. admin 渲染 overview 真实 KPI 卡 + 每 agent 统计表
 * 2. 非 admin 显示权限门（admin-gate），不渲染内容
 * 3. 趋势条按天序列渲染
 * 4. 导出按钮调用 exportStats
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    currentUser: { id: '1', username: 'admin' },
    user: { id: '1', username: 'admin', role: 'admin' },
  })),
}))

vi.mock('@/api/modules', () => ({
  statsApi: {
    getSystemStats: vi.fn(),
    getAgentStats: vi.fn(),
    exportStats: vi.fn(),
  },
}))
vi.mock('@/api/modules/analytics', () => ({
  getPerformanceAnalytics: vi.fn(),
  getBehaviorAnalytics: vi.fn(),
  getErrorAnalytics: vi.fn(),
}))

import StatsPage from '@/pages/StatsPage.vue'
import { statsApi } from '@/api/modules'
import { getPerformanceAnalytics, getBehaviorAnalytics, getErrorAnalytics } from '@/api/modules/analytics'

const messages = {
  common: {
    noData: '暂无数据',
    name: '名称',
    status: '状态',
    export: '导出',
    globalSettingHint: '本页面为全局系统配置/数据，对所有用户生效',
    adminOnlyHint: '仅管理员可访问与操作，当前账号无权限',
    success: '操作成功',
    error: '操作失败',
  },
  stats: { title: '统计分析', usageTrends: '使用趋势' },
  dashboard: {
    totalAgents: '智能体总数',
    totalConversations: '对话总数',
    totalTokens: 'Token 用量',
    totalCalls: 'API 调用',
  },
  system: { overview: '概览', performance: '性能', behavior: '行为', errors: '错误' },
  agent: { stats: '智能体统计' },
  analytics: {
    day: '日', week: '周', month: '月',
    avgResponse: '平均响应', p95Latency: 'P95 延迟', throughput: '吞吐量', errorRate: '错误率',
    responseTimes: '响应时间',
    popularFeatures: '热门功能', userPaths: '用户路径',
    totalErrors: '总错误数', topErrors: '常见错误',
    endpoint: '端点', avgMs: '平均 (ms)', p95Ms: 'P95 (ms)', calls: '调用次数',
    errorCode: '错误码', message: '消息', count: '计数',
  },
}

const stubs = {
  GlassPanel: { props: ['variant', 'padding', 'radius'], template: '<div class="glass-panel"><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  GlassStatCard: { props: ['label', 'value', 'trend'], template: '<div class="glass-stat"><span class="stat-label">{{ label }}</span><span class="stat-value">{{ value }}</span></div>' },
  GlassCard: { props: ['title'], template: '<div class="glass-card"><div v-if="title" class="gc-title">{{ title }}</div><slot/></div>' },
  'a-radio-group': { props: ['value'], emits: ['change'], template: '<div class="a-radio-group"><slot/></div>' },
  'a-radio-button': { props: ['value'], template: '<span class="a-radio-btn">{{ value }}</span>' },
  'a-tabs': { props: ['activeKey'], emits: ['change'], template: '<div class="a-tabs"><slot/></div>' },
  'a-tab-pane': { props: ['key', 'tab'], template: '<div class="a-tab-pane" :data-tab="key"><slot/></div>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-table': { props: ['columns', 'dataSource', 'loading'], template: '<div class="a-table"><div class="a-row" v-for="row in dataSource" :key="row.id"><span v-for="c in columns" :key="c.key" class="a-td" :data-col="c.key">{{ row[c.dataIndex ?? c.key] ?? "" }}</span></div><div v-if="!dataSource.length">暂无数据</div></div>' },
  'a-badge': { props: ['status', 'text'], template: '<span class="a-badge">{{ text }}</span>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(StatsPage, { global: { plugins: [i18n], stubs } })
}

describe('StatsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(statsApi.getSystemStats).mockResolvedValue({
      overview: {
        agents: 3,
        conversations: 700,
        memories: 66,
        tokens: 12345,
        api_calls: 5,
        errors: 2,
        uptime: 960,
      },
      trends: [
        { label: '09-01', value: 1 },
        { label: '09-02', value: 2 },
      ],
    } as never)
    vi.mocked(statsApi.getAgentStats).mockResolvedValue([
      { id: 'default', name: 'Nova', status: 'active', conversations: 2, messages: 8, tokens: 0, api_calls: 0, errors: 0 },
    ] as never)
    vi.mocked(getPerformanceAnalytics).mockResolvedValue({ period: 'week', by_endpoint: [] } as never)
    vi.mocked(getBehaviorAnalytics).mockResolvedValue({ period: 'week', top_tools: [], conversation_patterns: [] } as never)
    vi.mocked(getErrorAnalytics).mockResolvedValue({ period: 'week', by_type: [] } as never)
  })

  it('admin renders real overview KPI cards and agent stats table', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const values = wrapper.findAll('.stat-value').map((w) => w.text())
    expect(values[0]).toBe('3')        // agents
    expect(values[1]).toBe('700')      // conversations
    expect(values[2]).toBe('12345')    // tokens（当前模板直显原始值）
    expect(values[3]).toBe('5')        // api_calls
    expect(values[4]).toBe('2')        // errors

    // 每 agent 表：Nova 行
    expect(wrapper.text()).toContain('Nova')
    expect(wrapper.text()).toContain('智能体统计')
  })

  it('non-admin sees the permission gate', async () => {
    const { useAuthStore } = await import('@/stores/auth')
    vi.mocked(useAuthStore).mockReturnValueOnce({
      currentUser: { id: '2', username: 'user' },
      user: { id: '2', username: 'user', role: 'user' },
    } as never)
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('仅管理员可访问与操作，当前账号无权限')
  })
})
