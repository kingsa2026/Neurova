/**
 * BenchmarkPage — 套件列表解包防回归测试（2026-09-03）
 *
 * 实测根因：fetchSuites 取 res?.data —— 该值已是 data 对象
 * {suites, total}，v-for 遍历得到 2 个无名称幽灵卡片，套件名（Logical
 * Reasoning 等）丢失。
 *
 * 契约（防回归）：res.data.suites 才是套件数组。
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
      common: { error: '错误', success: '成功', status: '状态', noData: '暂无数据' },
      system: { benchmark: '基准测试' },
      benchmark: { execute: '执行', idle: '空闲', open: '打开', resultsComparison: '结果对比', perAgentResults: '按智能体结果', agent: '智能体', test: '测试', score: '分数', duration: '耗时', testsRun: '测试次数', passed: '通过', failed: '失败', avgScore: '平均分' },
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
        'a-table': { template: '<div><slot /></div>' },
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
