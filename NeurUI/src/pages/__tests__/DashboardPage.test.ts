/**
 * DashboardPage — 核心 KPI 仪表重设计防回归测试（2026-09-01）
 *
 * 背景：Dashboard 曾全依赖 stub 接口 /home/data（硬编码 0）+ /home/trends（随机数），
 * 除智能体数量外数据全空。重设计后：6 张真实统计卡（agent/会话/token/调用/记忆/知识）、
 * 真健康徽章（health report + 调度器）、echarts 7 天趋势 + 模型 Token 分布、错误重试条。
 *
 * 契约（防回归）：
 * 1. 6 张统计卡渲染真实值（cash 后端信封/裸对象双兼容）
 * 2. 核心数据失败 → 错误提示条出现，点击重试刷新
 * 3. 健康区渲染 health checks 与调度器任务数
 * 4. 趋势数据存在时渲染 VChart；token 分布无数据时显示空态
 * 5. 反馈卡保留并走 i18n 键
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentUser: { id: 'a9', username: 'admin' },
  }),
}))

vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({
    agents: [{ id: 'a1', name: 'Nova' }],
    loadAgents: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/composables/useFeedbackStats', () => ({
  useFeedbackStats: () => ({
    summary: { like: 0, dislike: 0, totalFeedback: 0, satisfactionRate: null, hasFeedback: false, recent: [] },
    satisfactionText: '--',
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}))

vi.mock('@/api/modules/home', () => ({
  getHomeData: vi.fn(),
  getHomeTrends: vi.fn(),
}))
vi.mock('@/api/modules/stats', () => ({
  getTokenUsage: vi.fn(),
  getSystemInfo: vi.fn(),
}))
vi.mock('@/api/modules/memory', () => ({
  getMemoryStats: vi.fn(),
}))
vi.mock('@/api/modules/knowledge', () => ({
  getKnowledgeNodes: vi.fn(),
}))
vi.mock('@/api/modules/health', () => ({
  getHealthReport: vi.fn(),
}))
vi.mock('@/api/modules/scheduler', () => ({
  getSchedulerStatus: vi.fn(),
}))

import DashboardPage from '@/pages/DashboardPage.vue'
import { getHomeData } from '@/api/modules/home'

const messages = {
  common: { noData: '暂无数据' },
  dashboard: {
    welcome: '欢迎回来',
    refresh: '刷新',
    loadError: '仪表盘数据加载失败',
    retry: '重试',
    totalAgents: '智能体总数',
    totalConversations: '对话总数',
    totalTokens: 'Token 用量',
    totalCalls: 'API 调用',
    totalMemories: '记忆总数',
    totalKnowledge: '知识条目',
    quickActions: '快捷操作',
    createAgent: '创建智能体',
    startChat: '开始对话',
    manageSkills: '管理技能',
    viewAnalytics: '查看分析',
    trends7d: '7 天活跃趋势',
    trendSession: '会话',
    trendMessage: '消息',
    noTrendData: '暂无趋势数据',
    tokenDistribution: '模型 Token 分布',
    noTokenData: '暂无 Token 记录（服务启动后累计）',
    feedbackCard: '回复质量反馈',
    feedbackSatisfaction: '满意度',
    feedbackEmpty: '暂无反馈',
    feedbackLike: '点赞',
    feedbackDislike: '点踩',
    systemHealth: '系统健康',
    schedulerRunning: '调度器运行中',
    schedulerIdle: '调度器空闲',
    schedulerTasks: '任务总数 {total}',
    healthCpu: 'CPU',
    healthMemory: '内存',
    healthDisk: '磁盘',
    statusHealthy: '系统健康',
  },
}

const stubs = {
  // GlassCard 刻意不 stub：其真实模板（GlassCard.vue → GlassPanel）是毛玻璃背板的载体；
  // 曾发生过 <script setup> 漏 import GlassCard，模板退化为未知元素 <glasscard>
  // （标题只留 attribute、卡片无背板无标题），stub 会掩盖该回归。
  GlassPanel: { props: ['variant', 'padding', 'radius', 'blur'], template: '<div class="glass-panel"><div class="glass-backdrop"/><slot/></div>' },
  GlassButton: { props: ['variant', 'size', 'loading'], emits: ['click'], template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>' },
  VChart: { props: ['option'], template: '<div class="vchart-stub" :data-has-option="option ? 1 : 0" />' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-badge': { props: ['status', 'text'], template: '<span class="a-badge" :data-status="status"><slot/>{{ text }}</span>' },
  'a-progress': { props: ['percent', 'type', 'status'], template: '<div class="a-progress" :data-status="status">{{ percent }}%</div>' },
  'a-tag': { props: ['color'], template: '<span class="a-tag" :data-color="color"><slot/></span>' },
  'a-empty': { props: ['description'], template: '<div class="a-empty">{{ description }}</div>' },
  'a-tooltip': { template: '<span><slot/></span>' },
  'a-alert': { props: ['message', 'type'], template: '<div class="a-alert" :data-type="type">{{ message }}<slot/></div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(DashboardPage, { global: { plugins: [i18n], stubs } })
}

describe('DashboardPage', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked((await import('@/api/modules/home')).getHomeData).mockResolvedValue({
      code: 0,
      data: { stats: { agent_count: 3, conversation_count: 688, token_consumption: 0, llm_call_count: 0 } },
    } as never)
    vi.mocked((await import('@/api/modules/home')).getHomeTrends).mockResolvedValue({
      code: 0,
      data: {
        agent_trend: { labels: ['09-01'], data: [1] },
        conversation_trend: { labels: ['09-01'], data: [10] },
        message_trend: { labels: ['09-01'], data: [20] },
        token_trend: { labels: ['09-01'], data: [] },
        llm_trend: { labels: ['09-01'], data: [] },
      },
    } as never)
    vi.mocked((await import('@/api/modules/stats')).getTokenUsage).mockResolvedValue({
      code: 0,
      data: { total: { calls: 5, prompt_tokens: 1, completion_tokens: 1, total_tokens: 12345 }, total_cost: 0.1, by_model: [{ model: 'gpt-4o', calls: 5, prompt_tokens: 4000, completion_tokens: 3000, total_tokens: 7000 }] },
    } as never)
    vi.mocked((await import('@/api/modules/memory')).getMemoryStats).mockResolvedValue({ code: 0, data: { total_memories: 42 } } as never)
    vi.mocked((await import('@/api/modules/knowledge')).getKnowledgeNodes).mockResolvedValue({ code: 0, data: { items: [], total: 17, page: 1, size: 1 } } as never)
    vi.mocked((await import('@/api/modules/stats')).getSystemInfo).mockResolvedValue({ code: 0, data: { status: 'running', cpu: { percent: 33 }, memory: { percent: 66 }, disk: { percent: 50 } } } as never)
    vi.mocked((await import('@/api/modules/health')).getHealthReport).mockResolvedValue({ code: 0, data: { overall: 'healthy', checks: [{ name: 'database', status: 'pass' }, { name: 'llm', status: 'pass' }], timestamp: 't', version: 'v' } } as never)
    vi.mocked((await import('@/api/modules/scheduler')).getSchedulerStatus).mockResolvedValue({ code: 0, data: { running: true, total_tasks: 8, active_tasks: 2, uptime_seconds: 60 } } as never)
  })

  it('renders all six stat cards with real values', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('3')        // agents
    expect(text).toContain('688')      // conversations
    expect(text).toContain('12.3K')    // tokens formatted (12345 → 12.3K)
    expect(text).toContain('5')        // calls
    expect(text).toContain('42')       // memories
    expect(text).toContain('17')       // knowledge
    expect(text).toContain('智能体总数')
    expect(text).toContain('记忆总数')
    expect(text).toContain('知识条目')
  })

  it('renders health report checks and scheduler summary', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('系统健康')
    expect(text).toContain('database')
    expect(text).toContain('llm')
    expect(text).toContain('调度器运行中')
    expect(text).toContain('8')        // schedulerTasks total
  })

  it('renders echarts for trend and token distribution when data exists', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.findAll('.vchart-stub').length).toBeGreaterThanOrEqual(2)
    const optioned = wrapper.findAll('.vchart-stub').filter((w) => w.attributes('data-has-option') === '1')
    expect(optioned.length).toBeGreaterThanOrEqual(2)
  })

  it('shows error bar with retry when core API fails', async () => {
    vi.mocked(getHomeData).mockRejectedValueOnce(new Error('network down'))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('.nr-dashboard-error').exists()).toBe(true)
    expect(wrapper.text()).toContain('仪表盘数据加载失败')

    await wrapper.find('.glass-btn').trigger('click')
    await flushPromises()
    // 重试触发重新拉取
    expect(getHomeData).toHaveBeenCalledTimes(2)
  })

  it('keeps feedback card empty state via i18n key', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('暂无反馈')
    expect(wrapper.text()).toContain('回复质量反馈')
  })

  it('renders grid cards through the real GlassCard shell (glass backdrop regression)', async () => {
    // 回归背景（2026-09-02）：<script setup> 曾漏 import GlassCard，模板把 <GlassCard>
    // 渲染为未知元素 <glasscard>——标题只保留为 attribute，GlassPanel 毛玻璃背板整体缺失，
    // 趋势图/快捷操作等卡片裸奔（无背板、无边框、无标题）。本用例不 stub GlassCard，
    // 断言 5 张网格卡均由 GlassCard → GlassPanel 真实模板输出。
    const wrapper = mountPage()
    await flushPromises()

    const titles = wrapper.findAll('.nr-glass-card-title').map((w) => w.text())
    expect(titles).toContain('7 天活跃趋势')
    expect(titles).toContain('模型 Token 分布')
    expect(titles).toContain('快捷操作')
    expect(titles).toContain('回复质量反馈')
    expect(titles).toContain('系统健康')

    // 每张标题卡都包在 GlassPanel 外壳内（毛玻璃载体的组件边界）
    const titleEls = wrapper.findAll('.nr-glass-card-title')
    for (const t of titleEls) {
      expect(t.element.closest('.glass-panel')).not.toBeNull()
    }

    // 趋势图 canvas 容器位于 GlassPanel 内，而非裸露在页面背景上
    const wrap = wrapper.find('.nr-chart-wrap')
    expect(wrap.exists()).toBe(true)
    expect(wrap.element.closest('.glass-panel')).not.toBeNull()
  })
})
