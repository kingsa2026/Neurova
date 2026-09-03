/**
 * BenchmarkPage — 套件列表解包防回归测试（2026-09-03）
 *
 * 实测根因：fetchSuites 取 res?.data —— 该值已是 data 对象
 * {suites, total}，v-for 遍历得到 2 个无名称幽灵卡片，套件名（Logical
 * Reasoning 等）丢失。
 *
 * 契约（防回归）：res.data.suites 才是套件数组。
 *
 * Agent 层契约（2026-09-03）：POST /benchmark/run 必带 agent_id（后端
 * BenchmarkRunRequest 必填，Agent 层隔离），此前只发 {suite_id} → 422；
 * /benchmark/results 返回 data.items（/runs 别名），此前取 data.results → 恒空。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: 'admin' } }),
}))

vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({
    agents: [
      { id: 'a1', name: 'Nova' },
      { id: 'a2', name: 'Atlas' },
    ],
    currentAgentId: 'a1',
    isolationContext: { agent_id: null },
    agentOptions: [
      { label: 'Nova', value: 'a1', isWorkflow: false },
      { label: 'Atlas', value: 'a2', isWorkflow: false },
    ],
  }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { request } from '@/api'
import BenchmarkPage from '@/pages/BenchmarkPage.vue'

const requestMock = request as unknown as {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { error: '错误', success: '成功', status: '状态', noData: '暂无数据', open: '打开' },
      system: { benchmark: '基准测试' },
      workflow: { execute: '执行' },
      benchmark: { execute: '执行', idle: '空闲', open: '打开', resultsComparison: '结果对比', perAgentResults: '按智能体结果', agent: '智能体', test: '测试', score: '分数', duration: '耗时', testsRun: '测试次数', passed: '通过', failed: '失败', avgScore: '平均分', pass: '通过', fail: '失败', lastRun: '上次: ', tests: '测试' },
    },
  },
})

const suitesEnvelope = {
  code: 0,
  message: 'success',
  data: {
    suites: [
      { id: 'reasoning-v1', name: 'Logical Reasoning', tasks: 50 },
      { id: 'coding-v1', name: 'Code Generation', tasks: 30 },
    ],
    total: 2,
  },
}

const mountPage = () =>
  mount(BenchmarkPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-select': { props: ['value'], template: '<div class="stub-select">{{ value }}</div>' },
        // 以 JSON 渲染 dataSource，断言表格拿到的是后端契约的字段
        'a-table': { props: ['dataSource'], template: '<div class="stub-table">{{ JSON.stringify(dataSource) }}</div>' },
      },
    },
  })

describe('BenchmarkPage 套件列表解包', () => {
  beforeEach(() => {
    requestMock.get.mockReset()
    requestMock.post.mockReset()
    requestMock.get.mockResolvedValue(suitesEnvelope)
  })

  it('从 res.data.suites 渲染套件名称', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('Logical Reasoning')
    expect(text).toContain('Code Generation')
  })

  it('空套件列表渲染暂无数据且无幽灵卡片', async () => {
    requestMock.get.mockResolvedValue({ code: 0, data: { suites: [], total: 0 } })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无数据')
    const openCount = wrapper.findAll('button').filter((b) => b.text().includes('打开')).length
    expect(openCount).toBe(0)
  })
})

// ── Agent 层契约（422 根因：POST 缺 agent_id）─────────────────────────────

const runsEnvelope = {
  code: 0,
  message: 'success',
  data: {
    items: [
      {
        run_id: 'r1',
        suite_id: 'reasoning-v1',
        suite_name: 'Logical Reasoning',
        agent_id: 'a1',
        status: 'completed',
        score: 72.5,
        tasks_total: 50,
        tasks_correct: 36,
        avg_latency_ms: 123.4,
      },
      {
        run_id: 'r2',
        suite_id: 'coding-v1',
        suite_name: 'Code Generation',
        agent_id: 'a2',
        status: 'completed',
        score: 90,
        tasks_total: 30,
        tasks_correct: 27,
        avg_latency_ms: 210,
      },
    ],
    total: 2,
    page: 1,
    size: 20,
  },
}

describe('BenchmarkPage Agent 层契约', () => {
  beforeEach(() => {
    requestMock.get.mockReset()
    requestMock.post.mockReset()
    requestMock.get.mockResolvedValue(suitesEnvelope)
  })

  it('套件卡片执行 POST 携带 agent_id（当前智能体）', async () => {
    requestMock.post.mockResolvedValue({ code: 0, data: {} })
    const wrapper = mountPage()
    await flushPromises()
    const runBtn = wrapper.findAll('.suite-actions button').find((b) => b.text().includes('执行'))
    expect(runBtn).toBeTruthy()
    await runBtn!.trigger('click')
    await flushPromises()
    expect(requestMock.post).toHaveBeenCalledWith('/benchmark/run', {
      suite_id: 'reasoning-v1',
      agent_id: 'a1',
    })
  })

  it('未选择套件时头部执行按钮禁用且不发请求', async () => {
    requestMock.post.mockResolvedValue({ code: 0, data: {} })
    const wrapper = mountPage()
    await flushPromises()
    const headerRun = wrapper.findAll('button').filter((b) => b.text().includes('执行'))[0]
    expect(headerRun).toBeTruthy()
    expect(headerRun.attributes('disabled')).toBeDefined()
    await headerRun.trigger('click')
    await flushPromises()
    expect(requestMock.post).not.toHaveBeenCalled()
  })

  it('结果表从 data.items 渲染运行记录并做每智能体聚合', async () => {
    requestMock.get.mockResolvedValue(runsEnvelope)
    const wrapper = mountPage()
    await flushPromises()
    const tables = wrapper.findAll('.stub-table')
    expect(tables.length).toBe(2)
    const runRows = tables[0].text()
    expect(runRows).toContain('r1')
    expect(runRows).toContain('Logical Reasoning')
    expect(runRows).toContain('72.5')
    expect(runRows).toContain('a1')
    // 每智能体聚合表：agent 名从 store 反查
    const agentRows = tables[1].text()
    expect(agentRows).toContain('Nova')
    expect(agentRows).toContain('Atlas')
  })
})
