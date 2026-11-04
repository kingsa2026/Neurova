/**
 * KnowledgeEvalPage — C6 评测控制台页契约测试。
 *
 * 契约面：
 * - 信封解包：getEvaluationBaseline 返回 {code,message,data}，data 即基线对象；
 * - 诚实态：measure_state=unevidenced → 渲染未冻结块（含 missing_reason），
 *   不伪造 0 值读数（与后端契约对称：未冻结不回 0）；
 * - 角色面：快照与 A/B 对照面板仅管理员可见（与后端 403 门对称）；
 * - 对照入参：min_cases 缺省 30 透传。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// 角色可变的用户态（vi.mock 工厂被提升，经 globalThis 中转）
const authUser: { id: string; username: string; role: string } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
;(globalThis as Record<string, unknown>).__knowledgeEvalAuthUser = authUser

vi.mock('@/api/modules/knowledgeEval', () => ({
  getEvaluationBaseline: vi.fn(),
  compareEvaluationRuns: vi.fn(),
  getRetrievalMetricsSnapshot: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__knowledgeEvalAuthUser
    },
  }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { message } from 'ant-design-vue'
import {
  compareEvaluationRuns,
  getEvaluationBaseline,
  getRetrievalMetricsSnapshot,
} from '@/api/modules/knowledgeEval'
import KnowledgeEvalPage from '@/pages/KnowledgeEvalPage.vue'
import { knowledgeEvalSection } from '@/i18n/locales/_knowledgeEvalSection'

const baselineMock = getEvaluationBaseline as unknown as ReturnType<typeof vi.fn>
const compareMock = compareEvaluationRuns as unknown as ReturnType<typeof vi.fn>
const snapshotMock = getRetrievalMetricsSnapshot as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { knowledgeEval: knowledgeEvalSection('zh-CN') } },
})

const mountPage = () =>
  mount(KnowledgeEvalPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-spin': { template: '<div><slot /></div>' },
        'a-descriptions': { template: '<div><slot /></div>' },
        'a-descriptions-item': {
          props: ['label'],
          template: '<div class="stub-desc">{{ label }}: <slot /></div>',
        },
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-input': {
          props: ['value'],
          emits: ['update:value'],
          template:
            '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-input-number': {
          props: ['value'],
          emits: ['update:value'],
          template:
            '<input class="stub-num" :value="value" @input="$emit(\'update:value\', Number($event.target.value))" />',
        },
      },
    },
  })

beforeEach(() => {
  baselineMock.mockReset()
  compareMock.mockReset()
  snapshotMock.mockReset()
  authUser.role = 'admin'
})

describe('KnowledgeEvalPage 信封解包与诚实态', () => {
  it('unevidenced → 渲染未冻结块与缺因说明，不渲染读数表', async () => {
    baselineMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        measure_state: 'unevidenced',
        missing_reason: '尚未冻结基线：先跑 seedFromRepository + run + freezeBaseline',
        case_count: 0,
        readings: null,
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="baseline-unevidenced"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('seedFromRepository')
    expect(wrapper.find('[data-testid="baseline-readings"]').exists()).toBe(false)
  })

  it('frozen → 渲染读数（recall/MRR/未命中率来自 data 契约字段）', async () => {
    baselineMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        measure_state: 'frozen',
        frozen_at: '2026-11-05T00:00:00Z',
        case_count: 42,
        top_k: 5,
        readings: { recall_at_k: 0.75, mrr: 0.5, unhit_rate: 0.1 },
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="baseline-readings"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="baseline-unevidenced"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('0.75')
  })

  it('读取失败 → message.error（不静默吞）', async () => {
    baselineMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    expect(message.error).toHaveBeenCalled()
  })
})

describe('KnowledgeEvalPage 角色面', () => {
  it('管理员可见在线快照并拉取', async () => {
    baselineMock.mockResolvedValue({
      code: 0,
      data: { measure_state: 'unevidenced', readings: null },
    })
    snapshotMock.mockResolvedValue({ code: 0, data: { retrieval: { x: 1 } } })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="snapshot-pre"]').exists()).toBe(true)
    expect(snapshotMock).toHaveBeenCalledTimes(1)
  })

  it('非管理员不渲染快照与对照面板，也不发快照请求', async () => {
    authUser.role = 'user'
    baselineMock.mockResolvedValue({
      code: 0,
      data: { measure_state: 'unevidenced', readings: null },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="snapshot-pre"]').exists()).toBe(false)
    expect(snapshotMock).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="compare-btn"]').exists()).toBe(false)
  })
})

describe('KnowledgeEvalPage A/B 对照', () => {
  it('填入两个 run 标识后对照，min_cases 缺省 30 透传', async () => {
    baselineMock.mockResolvedValue({
      code: 0,
      data: { measure_state: 'unevidenced', readings: null },
    })
    compareMock.mockResolvedValue({ code: 0, data: { decision: 'tie', cases: 30 } })
    const wrapper = mountPage()
    await flushPromises()
    const inputs = wrapper.findAll('input.stub-input')
    await inputs[0].setValue('run-a-id')
    await inputs[1].setValue('run-b-id')
    await wrapper.find('[data-testid="compare-btn"]').trigger('click')
    await flushPromises()
    expect(compareMock).toHaveBeenCalledWith({ run_a: 'run-a-id', run_b: 'run-b-id', min_cases: 30 })
    expect(wrapper.find('[data-testid="compare-result"]').exists()).toBe(true)
  })

  it('未填标识时按钮禁用，不发对照请求', async () => {
    baselineMock.mockResolvedValue({
      code: 0,
      data: { measure_state: 'unevidenced', readings: null },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="compare-btn"]').attributes('disabled')).toBeDefined()
    expect(compareMock).not.toHaveBeenCalled()
  })
})
