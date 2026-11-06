/**
 * KnowledgeEvalPage 本体升级段（UI-3）契约测试。
 *
 * 契约面（§15.4 诚实性）：
 * - CQ 通过率卡：静态读数（9/11 implemented），标注以 CI 为准；
 * - 质量卡：真调用 GET /ontology/quality，逐条渲染缺陷＋两个可计算指标；
 *   零缺陷与读面失败两态分开（失败不降级成「零缺陷」）；
 * - 默认关矩阵：九项现值取自 `GET /knowledge/observability/default-off`（静态抄表已退役——
 *   那张表漏了 D-03，且旧断言用本地表长度自证，漏一项照样绿）；仅管理员可见，
 *   非管理员连请求都不发；读面失败显式报错，不留下旧行数冒充「全是默认态」。
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
  listDefaultOffFlags: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { getEvaluationBaseline } from '@/api/modules/knowledgeEval'
import { getOntologyQuality, listDefaultOffFlags } from '@/api/modules/ontology'
import KnowledgeEvalPage from '@/pages/KnowledgeEvalPage.vue'
import { knowledgeEvalSection } from '@/i18n/locales/_knowledgeEvalSection'
import { ontologySection } from '@/i18n/locales/_ontologySection'
import { CQ_ROWS } from '@/config/ontologyStatic'

const baselineMock = getEvaluationBaseline as unknown as ReturnType<typeof vi.fn>
const qualityMock = getOntologyQuality as unknown as ReturnType<typeof vi.fn>
const matrixMock = listDefaultOffFlags as unknown as ReturnType<typeof vi.fn>

/** 服务端名册的九行（含 D-03——前端那张抄来的表漏的正是这一行）。 */
const MATRIX_ROWS = [
  { flagId: 'D-01', envKey: 'NEUROVA_KB_QUERY_NORMALIZE', declaredDefault: 'off', mode: 'off', isDefault: true, homeModule: 'neurova.knowledge.query_normalization', readoutRef: 'normalizeMode' },
  { flagId: 'D-02', envKey: 'NEUROVA_KB_AMBIGUITY_CLARIFY', declaredDefault: 'off', mode: 'off', isDefault: true, homeModule: 'neurova.knowledge.ambiguity_clarification', readoutRef: 'ambiguityMode' },
  { flagId: 'D-03', envKey: 'NEUROVA_KB_MISS_CAPTURE', declaredDefault: 'off', mode: 'off', isDefault: true, homeModule: 'neurova.agent.knowledge_retriever_adapter', readoutRef: 'missCaptureMode' },
  { flagId: 'D-04', envKey: 'NEUROVA_KB_FACT_SURFACE', declaredDefault: 'off', mode: 'off', isDefault: true, homeModule: 'neurova.knowledge.foundation.read_surface', readoutRef: 'factSurfaceMode' },
  { flagId: 'D-06', envKey: 'NEUROVA_CONDITION_CLASSES_ROUTE', declaredDefault: 'off', mode: 'on', isDefault: false, homeModule: 'neurova.knowledge.derivation_citation', readoutRef: 'conditionClassRouteMode' },
  { flagId: 'D-08', envKey: 'NEUROVA_KB_DUAL_VECTOR', declaredDefault: 'off', mode: 'off', isDefault: true, homeModule: 'neurova.knowledge.vector_index', readoutRef: 'dualVectorMode' },
  { flagId: 'D-11', envKey: 'NEUROVA_RETRIEVAL_FUSION', declaredDefault: 'off', mode: 'off', isDefault: true, homeModule: 'neurova.agent.retrieval_fusion', readoutRef: 'fusionMode' },
  { flagId: 'D-16', envKey: 'NEUROVA_KB_EVENT_SUMMARY', declaredDefault: 'off', mode: 'off', isDefault: true, homeModule: 'neurova.api.endpoints.knowledge_common', readoutRef: 'eventSummaryMode' },
  { flagId: 'D-19', envKey: 'NEUROVA_KB_PARSER', declaredDefault: 'legacy', mode: 'legacy', isDefault: true, homeModule: 'neurova.knowledge.parser_shadow', readoutRef: 'parserMode' },
]

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
  matrixMock.mockReset()
  matrixMock.mockResolvedValue({ code: 0, message: 'ok', data: { items: MATRIX_ROWS } })
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

  it('默认关矩阵（管理员）：九行取自读数面，D-03 必须在场', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(matrixMock).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="eval-matrix-table"]').exists()).toBe(true)
    // 行数比的是**服务端给的那九行**，不是本地表的长度——旧断言写成
    // `rows.length == DEFAULT_OFF_ROWS.length`，抄表漏一项时它跟着漏，恒绿
    const ids = wrapper.findAll('[data-testid^="matrix-row-"]').map((n) => n.attributes('data-testid'))
    expect(ids.length).toBe(MATRIX_ROWS.length)
    expect(wrapper.find('[data-testid="matrix-row-D-03"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="matrix-row-D-19"]').text()).toContain('legacy')
    expect(wrapper.text()).toContain('NEUROVA_CONDITION_CLASSES_ROUTE')
  })

  it('偏离默认态的那一项显式标出，不冒充「全是默认」', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const deviated = wrapper.find('[data-testid="matrix-state-D-06"]')
    expect(deviated.text()).toContain('已偏离默认')
    expect(wrapper.find('[data-testid="matrix-state-D-01"]').text()).toContain('默认态')
  })

  it('读数面失败：显式报错，不留下上一次的行数冒充可观测', async () => {
    matrixMock.mockRejectedValue(new Error('503'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="matrix-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="eval-matrix-table"]').exists()).toBe(false)
  })

  it('权限态：非管理员既看不见面板，也不发这一枪（后端本就 403）', async () => {
    authUser.role = 'user'
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('[data-testid="eval-matrix-table"]').exists()).toBe(false)
    expect(matrixMock).not.toHaveBeenCalled()
  })

  it('反向守卫：前端不许再抄一张 D 组静态表（项名与行数只许来自读数面）', () => {
    const staticSource = resolve(process.cwd(), 'src/config/ontologyStatic.ts')
    const text = readFileSync(staticSource, 'utf-8')
    expect(text).not.toContain('DEFAULT_OFF_ROWS')
    expect(existsSync(resolve(process.cwd(), 'src/config/defaultOffRows.ts'))).toBe(false)
  })
})
