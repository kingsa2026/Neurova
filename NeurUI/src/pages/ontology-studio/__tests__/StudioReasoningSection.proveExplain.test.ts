/**
 * StudioReasoningSection「目标证明」（U12）与「推导解释」（U13）交互契约测试。
 *
 * - prove：三元组输入 → POST /ontology/prove（参数逐字），渲染 proved 标签、
 *   证明树（rule/fact 逐层缩进＋binding）、missing 清单；
 * - explain：fact_id 输入 → GET /ontology/explain/{fact_id}，渲染结论三元组、
 *   步骤树与中文模板 text；失败态显式报错（未知 fact_id 404 原话）。
 * 与分区既有内容并存：SPARQL/溯因面板仍在，不因新增面板缺席。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import StudioReasoningSection from '../StudioReasoningSection.vue'
import { proveGoal, explainFact, runOntologySparql, runOntologyAbduce } from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'
import type { OntologySchemaData } from '@/types/ontology'

vi.mock('@/api/modules/ontology', () => ({
  runOntologySparql: vi.fn(),
  runOntologyAbduce: vi.fn(),
  proveGoal: vi.fn(),
  explainFact: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: vi.fn(() => ({ user: { role: 'admin' } })),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ontology: ontologySection('zh-CN'), common: { yes: '是', no: '否' } } },
})

const proveMock = proveGoal as unknown as ReturnType<typeof vi.fn>
const explainMock = explainFact as unknown as ReturnType<typeof vi.fn>

const schema: OntologySchemaData = { terms: [], rules: [], schema_version: 1, tenant_scoped: true }

function mountSection() {
  return mount(StudioReasoningSection, {
    props: { schema },
    global: {
      plugins: [i18n],
      stubs: {
        'a-alert': { props: ['message'], template: '<div class="stub-alert">{{ message }}</div>' },
        'a-input': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  proveMock.mockReset()
  explainMock.mockReset()
})

describe('StudioReasoningSection 目标证明（U12）', () => {
  it('三元组输入 → POST /ontology/prove 参数逐字；已证明态渲染证明树（缩进＋binding）', async () => {
    proveMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        proved: true,
        goal: { subject: '设备0', predicate: 'risk_flag', object: 'high' },
        steps: [
          {
            kind: 'rule',
            ref: 'rule_risk_relay',
            binding: { X: '设备0' },
            sub: [{ kind: 'fact', ref: 'fact_001', binding: { X: '设备0' }, sub: [] }],
          },
        ],
        missing: [],
      },
    } as never)
    const wrapper = mountSection()
    await flushPromises()

    await wrapper.find('input[data-testid="prove-subject"]').setValue('设备0')
    await wrapper.find('input[data-testid="prove-predicate"]').setValue('risk_flag')
    await wrapper.find('input[data-testid="prove-object"]').setValue('high')
    await wrapper.find('[data-testid="prove-run"]').trigger('click')
    await flushPromises()

    expect(proveMock).toHaveBeenCalledWith({ subject: '设备0', predicate: 'risk_flag', object: 'high' })
    const result = wrapper.find('[data-testid="prove-result"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('已证明')
    expect(wrapper.find('[data-testid="prove-steps"]').exists()).toBe(true)
    const rows = wrapper.findAll('.proof-row')
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain('rule_risk_relay')
    expect(rows[0].text()).toContain('X=设备0')
    expect(rows[1].text()).toContain('fact_001')
    expect(wrapper.find('[data-testid="prove-missing"]').exists()).toBe(false)
  })

  it('未证明态：missing 清单逐条渲染（goal 三元组＋reason），不渲染证明树', async () => {
    proveMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        proved: false,
        goal: { subject: '设备0', predicate: 'risk_flag', object: 'high' },
        steps: [],
        missing: [{ goal: { subject: '设备0', predicate: 'risk_flag', object: 'high' }, reason: 'unproven' }],
      },
    } as never)
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('input[data-testid="prove-subject"]').setValue('设备0')
    await wrapper.find('input[data-testid="prove-predicate"]').setValue('risk_flag')
    await wrapper.find('input[data-testid="prove-object"]').setValue('high')
    await wrapper.find('[data-testid="prove-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="prove-result"]').text()).toContain('未证明')
    expect(wrapper.find('[data-testid="prove-steps"]').exists()).toBe(false)
    const missing = wrapper.find('[data-testid="prove-missing"]')
    expect(missing.exists()).toBe(true)
    expect(missing.text()).toContain('unproven')
    expect(missing.text()).toContain('设备0 risk_flag high')
  })

  it('失败态：prove 请求失败显式报错（后端 detail 原话优先）', async () => {
    proveMock.mockRejectedValue({ response: { data: { detail: 'subject/predicate/object 均必填' } } })
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="prove-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="prove-error"]').text()).toContain('subject/predicate/object 均必填')
    expect(wrapper.find('[data-testid="prove-result"]').exists()).toBe(false)
  })
})

describe('StudioReasoningSection 推导解释（U13）', () => {
  it('fact_id 输入 → GET /ontology/explain/{fact_id}；渲染结论、步骤树与中文模板 text', async () => {
    explainMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        conclusion: { subject: '设备0', predicate: 'risk_flag', object: 'high' },
        steps: [
          {
            kind: 'rule',
            ref: 'rule_risk_relay',
            ruleVersion: 'v1',
            triple: { subject: '设备0', predicate: 'risk_flag', object: 'high' },
            premiseIds: ['fact_001'],
            steps: [{ kind: 'fact', ref: 'fact_001', triple: { subject: '设备0', predicate: 'status', object: 'broken' }, premiseIds: [], steps: [] }],
          },
        ],
        missing: [],
        text: '结论 设备0 risk_flag high 由规则 rule_risk_relay 从前提 设备0 status broken 推出',
      },
    } as never)
    const wrapper = mountSection()
    await flushPromises()

    await wrapper.find('input[data-testid="explain-fact-id"]').setValue('fact_002')
    await wrapper.find('[data-testid="explain-run"]').trigger('click')
    await flushPromises()

    expect(explainMock).toHaveBeenCalledTimes(1)
    expect(explainMock).toHaveBeenCalledWith('fact_002')
    const result = wrapper.find('[data-testid="explain-result"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('设备0 risk_flag high')
    expect(wrapper.find('[data-testid="explain-steps"]').exists()).toBe(true)
    const rows = wrapper.findAll('.proof-row')
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain('rule_risk_relay')
    expect(rows[1].text()).toContain('设备0 status broken')
    expect(wrapper.find('[data-testid="explain-text"]').text())
      .toContain('由规则 rule_risk_relay 从前提')
  })

  it('失败态：未知 fact_id 404 原话显式显示，不静默', async () => {
    explainMock.mockRejectedValue({ response: { data: { detail: "事实 'fact_x' 不存在，无法解释推导" } } })
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('input[data-testid="explain-fact-id"]').setValue('fact_x')
    await wrapper.find('[data-testid="explain-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="explain-error"]').text()).toContain("事实 'fact_x' 不存在")
    expect(wrapper.find('[data-testid="explain-result"]').exists()).toBe(false)
  })
})
