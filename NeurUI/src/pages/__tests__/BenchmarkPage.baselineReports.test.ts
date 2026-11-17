/**
 * S1-1E BenchmarkPage 多 agent 基线报告视图（只读）。
 *
 * 后端 GET /benchmark/baseline-reports(/{id}) 已存在而页面此前没有该视图——
 * 报告落盘后前端无处可看（usage/轨迹列只在 Markdown 报告里）。本档钉住：
 * 1. 挂载即拉报告清单（GET /benchmark/baseline-reports）；
 * 2. 清单行渲染 report_id 与 swarm 聚合列；
 * 3. 点"详情"按 reportId 取回全文，逐任务表渲染 usage 与轨迹列。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api', () => {
  const request = { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { request, default: request }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: 'admin' } }),
}))

vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({
    agents: [{ id: 'a1', name: 'Nova' }],
    currentAgentId: 'a1',
    isolationContext: { agent_id: null },
    agentOptions: [{ label: 'Nova', value: 'a1', isWorkflow: false }],
  }),
}))

vi.mock('ant-design-vue', async () => {
  // 组件注册走 main.ts 的 app.use(Antd)；测试里同款注册，仅 message 换桩
  const actual = await vi.importActual<any>('ant-design-vue')
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() } }
})

import Antd from 'ant-design-vue'
import { request } from '@/api'
import BenchmarkPage from '@/pages/BenchmarkPage.vue'

const requestMock = request as unknown as {
  get: ReturnType<typeof vi.fn>
}

const REPORT_ITEM = {
  report_id: 'bench-A',
  generated_at: '2026-11-17T12:00:00+00:00',
  task_isolated_memory: true,
  task_count: 1,
  metrics: {
    swarm: { task_count: 1, passed_count: 1, success_rate: 1, total_tokens: 4580, total_steps: 3, total_tool_calls: 2 },
    solo: { task_count: 1, passed_count: 0, success_rate: 0, total_tokens: 900, total_steps: 1, total_tool_calls: 0 },
  },
  comparison: { available: true, token_multiplier: 5.089 },
}

const REPORT_DETAIL = {
  generated_at: '2026-11-17T12:00:00+00:00',
  task_isolated_memory: true,
  metrics: REPORT_ITEM.metrics,
  comparison: {},
  tasks: [
    {
      task_id: 'T2-handoff',
      mode: 'swarm',
      passed: true,
      score: 1,
      elapsed_seconds: 12.4,
      usage: { promptTokens: 4200, completionTokens: 380, totalTokens: 4580, elapsedSeconds: 12.4, steps: 3, toolCalls: 2 },
      trajectory: { toolsUsed: ['memory_search', 'handoff'], source: 'tool_messages' },
    },
  ],
}

function routeGet(url: string) {
  if (url === '/benchmark/baseline-reports') {
    return Promise.resolve({ code: 0, message: 'success', data: { items: [REPORT_ITEM], total: 1 } })
  }
  if (url === '/benchmark/baseline-reports/bench-A') {
    return Promise.resolve({ code: 0, message: 'success', data: REPORT_DETAIL })
  }
  if (String(url).startsWith('/benchmark/suites')) {
    return Promise.resolve({ code: 0, data: { suites: [] } })
  }
  if (String(url).startsWith('/benchmark/results')) {
    return Promise.resolve({ code: 0, data: { items: [] } })
  }
  return Promise.resolve({ code: 0, data: {} })
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { error: '错误', success: '成功', noData: '暂无数据', open: '打开' },
      system: { benchmark: '基准测试' },
      workflow: { execute: '执行' },
      benchmark: {
        agent: '智能体', test: '测试', score: '分数', duration: '耗时',
        idle: '空闲', tests: '测试', lastRun: '上次: ', pass: '通过',
        resultsComparison: '结果对比', perAgentResults: '按智能体结果',
        testsRun: '测试次数', passed: '通过', failed: '失败', avgScore: '平均分',
        baselineReports: '多 Agent 基线报告', baselineDetail: '详情',
        isolatedOn: '隔离', isolatedOff: '未隔离',
        colSwarmSuccess: 'Swarm 成功率', colSwarmTokens: 'Swarm 总 Token',
        colSwarmSteps: 'Swarm 步数', colSwarmTools: 'Swarm 工具数',
        taskId: '任务', mode: '模式', colPrompt: 'Prompt',
        colCompletion: 'Completion', colTotalTokens: '总 Token',
        colSteps: '步数', colToolCalls: '工具数', colTrajectory: '轨迹(工具)',
        suites: {},
      },
    },
  },
})

const mountPage = () => mount(BenchmarkPage, { global: { plugins: [i18n, Antd] } })

beforeEach(() => {
  vi.clearAllMocks()
  requestMock.get.mockImplementation(routeGet)
})

describe('基线报告视图', () => {
  it('挂载即拉报告清单（GET /benchmark/baseline-reports）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const urls = requestMock.get.mock.calls.map((c) => String(c[0]))
    expect(urls).toContain('/benchmark/baseline-reports')
    wrapper.unmount()
  })

  it('清单渲染 report_id 与 swarm 聚合列读数', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const html = wrapper.html()
    expect(html).toContain('bench-A')
    expect(html).toContain('4580')
    expect(html).toContain('100%')
    wrapper.unmount()
  })

  it('点详情按 reportId 取回全文，逐任务表渲染 usage 与轨迹列', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const detailBtn = wrapper.find('[data-testid="baseline-detail-btn"]')
    expect(detailBtn.exists()).toBe(true)
    await detailBtn.trigger('click')
    await flushPromises()
    expect(requestMock.get).toHaveBeenCalledWith('/benchmark/baseline-reports/bench-A')
    const html = wrapper.html()
    expect(html).toContain('T2-handoff')
    expect(html).toContain('4200')
    expect(html).toContain('380')
    expect(html).toContain('memory_search')
    wrapper.unmount()
  })
})
