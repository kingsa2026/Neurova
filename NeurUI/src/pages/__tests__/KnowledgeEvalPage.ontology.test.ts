/**
 * KnowledgeEvalPage 本体升级段（UI-3）契约测试。
 *
 * 契约面（§15.4 诚实性）：
 * - CQ 通过率卡：静态读数（9/11 implemented），标注以 CI 为准；
 * - 质量卡：真调用 GET /ontology/quality，逐条渲染缺陷＋两个可计算指标；
 *   零缺陷与读面失败两态分开（失败不降级成「零缺陷」）；
 * - 默认关矩阵：D-01/D-02/D-04/D-06/D-08/D-11/D-16/D-19 静态表，
 *   仅管理员可见，无写入开关，注明前端读不到服务端 env。
 *
 * 与既有 KnowledgeEvalPage.test.ts 分文件（A/B 纪律：不动既有断言）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const authUser: { id: string; username: string; role: string } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
;(globalThis as Record<string, unknown>).__knowledgeEvalOntologyAuthUser = authUser

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__knowledgeEvalOntologyAuthUser
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
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { getEvaluationBaseline } from '@/api/modules/knowledgeEval'
import { getOntologyQuality } from '@/api/modules/ontology'
import KnowledgeEvalPage from '@/pages/KnowledgeEvalPage.vue'
import { knowledgeEvalSection } from '@/i18n/locales/_knowledgeEvalSection'
import { ontologySection } from '@/i18n/locales/_ontologySection'
import { CQ_ROWS, DEFAULT_OFF_ROWS } from '@/config/ontologyStatic'

const baselineMock = getEvaluationBaseline as unknown as ReturnType<typeof vi.fn>
const qualityMock = getOntologyQuality as unknown as ReturnType<typeof vi.fn>

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
          template: '<input class="stub-num" :value="value" @input="$emit(\'update:value\', Number($event.target.value))" />',
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
    data: {
      tenant_id: 'default',
      term_count: 3,
      findings: [
        { kind: 'missingLabel', severity: 'warning', target: 'bare_term', message: '术语 bare_term 缺可读 label' },
        { kind: 'orphanClass', severity: 'warning', target: 'bare_term', message: '概念 bare_term 无父类' },
      ],
      metrics: { consistency: 1, conciseness: 1 },
    },
  })
  authUser.role = 'admin'
})

describe('KnowledgeEvalPage（UI-3 本体升级段）', () => {
  it('CQ 通过率卡：静态读数 9/11，且标注运行状态以 CI 为准', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const implemented = CQ_ROWS.filter((row) => row.status === 'implemented').length
    const rate = wrapper.find('[data-testid="eval-cq-rate"]')
    expect(rate.exists()).toBe(true)
    expect(rate.text()).toContain(`${implemented} / ${CQ_ROWS.length}`)
    expect(wrapper.text()).toContain('CI')
  })

  it('质量卡：真调用 GET /ontology/quality，逐条渲染缺陷与两个可计算指标', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(qualityMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="eval-quality-count"]').text()).toContain('3')
    expect(wrapper.find('[data-testid="eval-quality-metrics"]').text()).toContain('一致性')
    expect(wrapper.find('[data-testid="eval-quality-metrics"]').text()).toContain('简洁度')
    const rows = wrapper.findAll('[data-testid^="quality-row-"]')
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain('missingLabel')
    expect(rows[0].text()).toContain('bare_term')
    // 诚实边界：完整认证不在承诺面
    expect(wrapper.find('[data-testid="eval-quality-note"]').text()).toContain('OOPS!')
  })

  it('质量卡空态：零缺陷时显式说「没有可计算的缺陷」，不渲染空表冒充读数', async () => {
    qualityMock.mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { tenant_id: 'default', term_count: 0, findings: [], metrics: { consistency: 1, conciseness: 1 } },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="eval-quality-table"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="eval-quality-empty"]').exists()).toBe(true)
  })

  it('质量卡错误态：读面失败显式报错，不降级成「零缺陷」', async () => {
    qualityMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="eval-quality-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="eval-quality-empty"]').exists()).toBe(false)
  })

  it('默认关矩阵（管理员）：D 组 8 行静态表，注明前端读不到 env、无写入开关', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const table = wrapper.find('[data-testid="eval-matrix-table"]')
    expect(table.exists()).toBe(true)
    const rows = wrapper.findAll('[data-testid="matrix-default"]')
    expect(rows.length).toBe(DEFAULT_OFF_ROWS.length)
    for (const row of DEFAULT_OFF_ROWS) {
      expect(wrapper.find(`[data-testid="matrix-row-${row.id}"]`).exists()).toBe(true)
      expect(wrapper.text()).toContain(row.env)
    }
    expect(wrapper.find('[data-testid="eval-env-note"]').text()).toContain('不提供写入开关')
  })

  it('权限态：非管理员看不到默认关矩阵面板（§15.3 观测与开关为管理员面）', async () => {
    authUser.role = 'user'
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="eval-matrix-table"]').exists()).toBe(false)
  })
})
