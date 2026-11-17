import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

/**
 * N3 真执行器前端适配（用户拍板 2026-11-17：PC+移动都做）——
 * POST /benchmark/run 自"同步返回结果"变为"后台执行+状态查询"：
 * 响应 data.status='running'、score=null，终态要经 GET /runs/{run_id} 轮询。
 *
 * 本档钉住 PC 端轮询契约：
 * 1. run 返回 running 后必须轮询 GET /benchmark/runs/{run_id}（旧实现零轮询——
 *    用户只看到"后台执行中"，永远等不到分数）；
 * 2. 终态（completed/failed）后停止轮询并刷新结果列表；
 * 3. 组件卸载后不再轮询（定时器泄漏）。
 */

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

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
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
      benchmark: {
        execute: '执行', idle: '空闲', open: '打开', resultsComparison: '结果对比',
        perAgentResults: '按智能体结果', agent: '智能体', test: '测试', score: '分数',
        duration: '耗时', testsRun: '测试次数', passed: '通过', failed: '失败',
        avgScore: '平均分', pass: '通过', fail: '失败', lastRun: '上次: ', tests: '测试',
        suites: {
          'reasoning-v1': { name: '逻辑推理', description: '测试逻辑推演与问题求解' },
        },
      },
    },
  },
  globalInjection: true,
})

const suitesEnvelope = {
  code: 0,
  data: {
    suites: [{ id: 'reasoning-v1', name: 'Logical Reasoning', tasks: 50 }],
    total: 1,
  },
}

const resultsEnvelope = {
  code: 0,
  data: { items: [{ run_id: 'r1', status: 'running', score: null }] },
}

const completedEnvelope = {
  code: 0,
  data: { run_id: 'r1', status: 'completed', score: 0.9, tasks_total: 50, tasks_correct: 45 },
}

const runningEnvelope = {
  code: 0,
  data: { run_id: 'r1', status: 'running', score: null },
}

const globalStubs = {
  // GlassCard 须渲染 footer 具名插槽——套件卡的「执行」按钮在 footer 里
  GlassCard: { template: '<div class="glass-card"><slot/><slot name="footer"/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading', 'disabled'],
    emits: ['click'],
    template: '<button class="nr-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot/></button>',
  },
  'a-tag': { template: '<span class="stub-tag"><slot/></span>' },
  'a-table': { template: '<div class="stub-table"/>' },
  'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
}

function mountPage() {
  return mount(BenchmarkPage, {
    global: { plugins: [i18n], stubs: globalStubs },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  let runsCalls = 0
  requestMock.get.mockImplementation((url: string) => {
    if (url.includes('/benchmark/suites')) return Promise.resolve(suitesEnvelope)
    if (url.includes('/benchmark/results')) return Promise.resolve(resultsEnvelope)
    if (url.includes('/benchmark/runs/r1')) {
      runsCalls += 1
      // 首查仍 running，再查终态——验证轮询推进与停止
      return Promise.resolve(runsCalls === 1 ? runningEnvelope : completedEnvelope)
    }
    return Promise.resolve({})
  })
  requestMock.post.mockResolvedValue({
    code: 0,
    message: 'Benchmark run started — 后台执行中',
    data: { run_id: 'r1', status: 'running', simulated: false, score: null },
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('BenchmarkPage — 真执行器轮询适配（N3）', () => {
  const findRunnableExecuteButton = (wrapper: ReturnType<typeof mountPage>) => {
    // 头部按钮在未选套件时 disabled（HTML 布尔属性渲染为空串，attributes 判真不可靠）；
    // 套件卡按钮在 DOM 尾部且无 disabled——取最后一个匹配避开头部按钮。
    const buttons = wrapper.findAll('button').filter((b) => b.text().includes('执行'))
    expect(buttons.length, '应有执行按钮（头部+套件卡）').toBeGreaterThan(0)
    return buttons[buttons.length - 1]
  }

  it('run 返回 running 后轮询 runs/{run_id} 直到终态并刷新结果', async () => {
    const wrapper = mountPage()
    await flushPromises()

    findRunnableExecuteButton(wrapper).trigger('click')
    await flushPromises()

    // POST /run 后应立即首查一次 runs/{run_id}（旧实现零轮询——此处红）
    const runsCalls = () =>
      requestMock.get.mock.calls.filter((call) => String(call[0]).includes('/benchmark/runs/r1')).length
    expect(runsCalls()).toBeGreaterThanOrEqual(1)

    // 推进轮询定时器 → 第二查返回 completed → 停止轮询并刷新结果
    await vi.advanceTimersByTimeAsync(2100)
    await flushPromises()
    expect(runsCalls()).toBeGreaterThanOrEqual(2)
    const callsAfterSettle = runsCalls()
    await vi.advanceTimersByTimeAsync(6000)
    await flushPromises()
    expect(runsCalls(), '终态后必须停止轮询').toBe(callsAfterSettle)
  })

  it('组件卸载后停止轮询（定时器不泄漏）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    findRunnableExecuteButton(wrapper).trigger('click')
    await flushPromises()

    wrapper.unmount()
    const callsAtUnmount = requestMock.get.mock.calls.filter((call) =>
      String(call[0]).includes('/benchmark/runs/r1'),
    ).length
    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()
    const callsAfter = requestMock.get.mock.calls.filter((call) =>
      String(call[0]).includes('/benchmark/runs/r1'),
    ).length
    expect(callsAfter, '卸载后不得继续轮询').toBe(callsAtUnmount)
  })
})
