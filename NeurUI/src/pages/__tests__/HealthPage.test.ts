import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import HealthPage from '@/pages/HealthPage.vue'

/**
 * P1-23（审计 2026-11-16）：HealthPage 恒 'healthy' 假绿——
 * axios 拦截器已解包信封，页面读 `res?.data` 得 undefined → checks=[] →
 * `[].every()` 恒真 → 无数据也亮绿灯（掩盖故障）。
 *
 * 修复后：mock 返回**裸 CheckResultResponse[]**（真实后端形状），
 * 聚合走 aggregateOverallStatus（与后端 get_overall_status 同像）：
 * - 空读数 → 'unknown'（不再假绿）；
 * - unhealthy 检查 → 整体 unhealthy；
 * - 单检查「刷新」打 runCheck（POST /checks/{name}/run）；
 * - 「恢复」按钮 disabled（后端 /recover 显式 501 未实现）。
 */
vi.mock('@/api/modules/health', async () => {
  // 聚合/归一保持真实现（被测对象），只 mock 网络出口
  const actual = await vi.importActual<any>('@/api/modules/health')
  return {
    ...actual,
    getHealthChecks: vi.fn(),
    getHealthReport: vi.fn(),
    runCheck: vi.fn(),
    getHealthStatus: vi.fn(),
  }
})

vi.mock('ant-design-vue', async () => {
  const actual = await vi.importActual<any>('ant-design-vue')
  return {
    ...actual,
    message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  }
})

import { getHealthChecks, getHealthReport, runCheck } from '@/api/modules/health'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': {
      system: { health: '健康' },
      common: { refresh: '刷新', error: '操作失败', success: '成功', noData: '暂无数据', type: '类型', comingSoon: '即将推出' },
      health: {
        report: '报告', reportTitle: '健康报告', allOperational: '所有系统正常运行',
        someDegraded: '部分系统性能降级', systemIssues: '检测到系统问题',
        checksSummary: '{checks} 项检查 · {healthy} 项健康 · {issues} 项问题',
        lastChecked: '上次检查: ', response: '响应: ', recover: '恢复',
      },
    },
  },
  globalInjection: true,
})

const globalStubs = {
  GlassPanel: { template: '<div><slot/></div>' },
  GlassCard: { template: '<div><slot name="header"/><slot/><slot name="footer"/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading', 'disabled'],
    emits: ['click'],
    template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot/></button>',
  },
  'a-spin': { template: '<div><slot/></div>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
  'a-tag': { template: '<span class="stub-tag"><slot/></span>' },
  'a-tooltip': { template: '<span><slot/></span>' },
  'a-modal': { props: ['open'], template: '<div v-if="open" class="stub-modal"><slot/></div>' },
}

function mountHealthPage() {
  return mount(HealthPage, {
    global: {
      plugins: [i18n],
      stubs: globalStubs,
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('HealthPage — 恒 healthy 假绿消除（P1-23）', () => {
  it('空读数（检查器无注册检查）显示 unknown，不再亮 healthy 假绿', async () => {
    // 真实后端形状：GET /checks 回裸数组；当前进程未注册任何检查 → []
    vi.mocked(getHealthChecks).mockResolvedValue([] as any)

    const wrapper = mountHealthPage()
    await flushPromises()

    const badge = wrapper.find('.overall-badge')
    expect(badge.text()).toBe('unknown')
    expect(wrapper.text()).not.toContain('healthy')
    expect(wrapper.find('.stub-empty').exists()).toBe(true)
  })

  it('unhealthy 检查项使整体转 unhealthy（不再恒绿），卡片按后端枚举着色', async () => {
    vi.mocked(getHealthChecks).mockResolvedValue([
      { name: 'db', status: 'healthy', message: '', duration: 3, check_type: 'dependency' },
      { name: 'llm', status: 'unhealthy', message: 'down', duration: 5, check_type: 'dependency' },
    ] as any)

    const wrapper = mountHealthPage()
    await flushPromises()

    expect(wrapper.find('.overall-badge').text()).toBe('unhealthy')
    expect(wrapper.text()).toContain('llm')
    expect(wrapper.text()).toContain('down')
    // 后端 duration 毫秒读数直出（此前渲染的是后端不存在的 last_check/response_time 字段）
    expect(wrapper.text()).toContain('5ms')
  })

  it('卡片「刷新」调 runCheck（POST /checks/{name}/run），不再误打 /recover', async () => {
    vi.mocked(getHealthChecks).mockResolvedValue([
      { name: 'db', status: 'degraded', message: 'slow', duration: 9, check_type: 'custom' },
    ] as any)
    vi.mocked(runCheck).mockResolvedValue({ name: 'db', status: 'healthy', message: '', duration: 1, check_type: 'custom' } as any)

    const wrapper = mountHealthPage()
    await flushPromises()

    // 页头也有「刷新」（fetchHealth），必须点卡片 footer 里那个（runSingleCheck）
    const refreshBtn = wrapper.findAll('.check-actions button').find((b) => b.text().includes('刷新'))
    expect(refreshBtn).toBeTruthy()
    await refreshBtn!.trigger('click')
    await flushPromises()

    expect(runCheck).toHaveBeenCalledWith('db')
  })

  it('「恢复」按钮对非健康检查渲染且 disabled（/recover 后端显式 501 未实现）', async () => {
    vi.mocked(getHealthChecks).mockResolvedValue([
      { name: 'llm', status: 'unhealthy', message: 'down', duration: 5, check_type: 'dependency' },
    ] as any)

    const wrapper = mountHealthPage()
    await flushPromises()

    const recoverBtn = wrapper.findAll('button').find((b) => b.text().includes('恢复'))
    expect(recoverBtn, '非健康检查应渲染恢复按钮').toBeTruthy()
    expect((recoverBtn!.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('「报告」按钮解裸 HealthReportResponse（status + checks Dict）', async () => {
    vi.mocked(getHealthReport).mockResolvedValue({
      status: 'degraded',
      checks: {
        db: { name: 'db', status: 'healthy', message: '', duration: 1, check_type: 'custom' },
        queue: { name: 'queue', status: 'degraded', message: 'lag', duration: 2, check_type: 'custom' },
      },
      total_checks: 2,
      healthy_count: 1,
      unhealthy_count: 0,
      timestamp: 1700000000,
    } as any)

    const wrapper = mountHealthPage()
    await flushPromises()

    const reportBtn = wrapper.findAll('button').find((b) => b.text().includes('报告'))
    expect(reportBtn).toBeTruthy()
    await reportBtn!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.overall-badge').text()).toBe('degraded')
    expect(wrapper.text()).toContain('queue')
  })
})
