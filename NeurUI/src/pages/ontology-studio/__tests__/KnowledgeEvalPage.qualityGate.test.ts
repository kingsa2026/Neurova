/**
 * KnowledgeEvalPage 质量卡增强（U6）契约测试：阈值门＋新 metrics 键。
 *
 * - 阈值门：只回传实际填了的阈值键（留空=不判该维，不硬造 0）；
 *   判定三态：passed / threshold_failures 逐条 / 请求失败显式报错（不冒充通过）；
 * - 新 metrics 键（orphanRate/missingLabelRate/inverseOneSidedCount/
 *   parentCycleCount/referenceIntegrity/coverage）：报告里有的才渲染——
 *   旧后端没有这些键时不硬造空位。
 *
 * 与既有 KnowledgeEvalPage.ontology.test.ts 分文件（A/B 纪律：不动既有断言）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const authUser: { id: string; username: string; role: string } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
;(globalThis as Record<string, unknown>).__qualityGateAuthUser = authUser

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__qualityGateAuthUser
    },
  }),
}))

vi.mock('@/api/modules/knowledgeEval', () => ({
  getEvaluationBaseline: vi.fn(),
  compareEvaluationRuns: vi.fn(),
  getRetrievalMetricsSnapshot: vi.fn(),
}))

vi.mock('@/api/modules/ontology', () => ({
  getOntologyQuality: vi.fn(),
  listDefaultOffFlags: vi.fn(),
  listCqMatrix: vi.fn(),
  qualityGate: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { getEvaluationBaseline } from '@/api/modules/knowledgeEval'
import { getOntologyQuality, qualityGate, listCqMatrix, listDefaultOffFlags } from '@/api/modules/ontology'
import KnowledgeEvalPage from '@/pages/KnowledgeEvalPage.vue'
import { knowledgeEvalSection } from '@/i18n/locales/_knowledgeEvalSection'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const baselineMock = getEvaluationBaseline as unknown as ReturnType<typeof vi.fn>
const qualityMock = getOntologyQuality as unknown as ReturnType<typeof vi.fn>
const gateMock = qualityGate as unknown as ReturnType<typeof vi.fn>
const matrixMock = listDefaultOffFlags as unknown as ReturnType<typeof vi.fn>
const cqMock = listCqMatrix as unknown as ReturnType<typeof vi.fn>

const QUALITY_BASE = {
  tenant_id: 'default',
  term_count: 5,
  findings: [{ kind: 'orphanClass', severity: 'warning', target: 'bare_term', message: '概念 bare_term 无父类' }],
}

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      knowledgeEval: knowledgeEvalSection('zh-CN'),
      ontology: ontologySection('zh-CN'),
      common: { refresh: '刷新' },
    },
  },
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
          template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-input-number': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-num" :value="value" @input="$emit(\'update:value\', $event.target.value === \'\' ? null : Number($event.target.value))" />',
        },
        GlassPanel: { template: '<div class="stub-panel"><slot /></div>' },
        GlassButton: {
          props: ['loading', 'disabled'],
          emits: ['click'],
          template: '<button class="stub-glass-btn" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })

beforeEach(() => {
  vi.clearAllMocks()
  baselineMock.mockReset()
  baselineMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { measure_state: 'unevidenced', missing_reason: '尚未冻结' },
  })
  qualityMock.mockReset()
  qualityMock.mockResolvedValue({
    code: 0,
    message: 'ok',
    data: { ...QUALITY_BASE, metrics: { consistency: 1, conciseness: 1 } },
  })
  matrixMock.mockReset()
  matrixMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [] } })
  cqMock.mockReset()
  cqMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: [] } })
  gateMock.mockReset()
  authUser.role = 'admin'
})

describe('KnowledgeEvalPage 质量门与新 metrics 键（U6）', () => {
  it('新 metrics 键：报告带了才逐项渲染，键名不硬造', async () => {
    qualityMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        ...QUALITY_BASE,
        metrics: {
          consistency: 1,
          conciseness: 1,
          orphanRate: 0.25,
          missingLabelRate: 0.2,
          inverseOneSidedCount: 1,
          parentCycleCount: 0,
          referenceIntegrity: 0.9,
          coverage: 0.8,
        },
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="eval-metric-orphanRate"]').text()).toContain('0.25')
    expect(wrapper.find('[data-testid="eval-metric-missingLabelRate"]').text()).toContain('0.2')
    expect(wrapper.find('[data-testid="eval-metric-inverseOneSidedCount"]').text()).toContain('1')
    expect(wrapper.find('[data-testid="eval-metric-parentCycleCount"]').text()).toContain('0')
    expect(wrapper.find('[data-testid="eval-metric-referenceIntegrity"]').text()).toContain('0.9')
    expect(wrapper.find('[data-testid="eval-metric-coverage"]').text()).toContain('0.8')
  })

  it('旧形状报告（无新键）：六个新键一格都不渲染，不硬造 0', async () => {
    qualityMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { ...QUALITY_BASE, metrics: { consistency: 1, conciseness: 1 } },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="eval-metric-orphanRate"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="eval-metric-missingLabelRate"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="eval-metric-inverseOneSidedCount"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="eval-metric-parentCycleCount"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="eval-metric-referenceIntegrity"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="eval-metric-coverage"]').exists()).toBe(false)
  })

  it('阈值门：只回传填了的键（min_coverage/max_findings），通过态渲染', async () => {
    gateMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { report: { ...QUALITY_BASE, metrics: {} }, gate: { passed: true, threshold_failures: [] } },
    })
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('input[data-testid="gate-min-coverage"]').setValue('0.8')
    await wrapper.find('input[data-testid="gate-max-findings"]').setValue('3')
    await wrapper.find('[data-testid="gate-run"]').trigger('click')
    await flushPromises()

    expect(gateMock).toHaveBeenCalledTimes(1)
    expect(gateMock).toHaveBeenCalledWith({ min_coverage: 0.8, max_findings: 3 })
    expect(wrapper.find('[data-testid="gate-result"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="gate-verdict"]').text()).toContain('门通过')
    expect(wrapper.find('[data-testid="gate-failures"]').exists()).toBe(false)
  })

  it('留空阈值：空门判定也照发（thresholds 空对象），不替用户硬造 0', async () => {
    gateMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { report: { ...QUALITY_BASE, metrics: {} }, gate: { passed: true, threshold_failures: [] } },
    })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="gate-run"]').trigger('click')
    await flushPromises()

    expect(gateMock).toHaveBeenCalledWith({})
    expect(wrapper.find('[data-testid="gate-verdict"]').text()).toContain('门通过')
  })

  it('未通过态：threshold_failures 逐条渲染', async () => {
    gateMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        report: { ...QUALITY_BASE, metrics: {} },
        gate: {
          passed: false,
          threshold_failures: [
            'min_coverage 未达标：覆盖率 0.6 < 阈值 0.8（覆盖率=未被任何 findings 点名的术语占比）',
            'max_findings 超限：findings 5 条 > 阈值 3',
          ],
        },
      },
    })
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('input[data-testid="gate-min-coverage"]').setValue('0.8')
    await wrapper.find('[data-testid="gate-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="gate-verdict"]').text()).toContain('门未通过')
    const failures = wrapper.findAll('[data-testid^="gate-failure-"]')
    expect(failures.length).toBe(2)
    expect(failures[0].text()).toContain('min_coverage')
    expect(failures[1].text()).toContain('max_findings')
  })

  it('失败态：判定请求失败显式报错，不冒充「门通过」', async () => {
    gateMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('input[data-testid="gate-min-coverage"]').setValue('0.8')
    await wrapper.find('[data-testid="gate-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="gate-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="gate-result"]').exists()).toBe(false)
  })
})
