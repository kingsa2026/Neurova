/**
 * StudioTermsSection — 术语写面选定实现的行为契约（教义第 7 条「选定那一份」）。
 *
 * 背景：术语 CRUD 原本两页两口径（图谱工作台自带一份窄口径 id/kind/label/basis）。
 * 比后合的结论是 Studio 全面胜出，但它有一处**真比旧页弱**：后端 400/409 的拒因
 * 被降级成通用文案——`deleteOntologyTerm` 的 catch 直接吞掉 detail，用户看不到
 * 「被谁引用」。这一档把旧页那条唯一可取之处接进选定实现。
 *
 * 判据面：
 * - 保存失败：后端 detail 是字符串 ⇒ 逐字回显，不降级；
 * - 删除被拒：后端 detail 是 {message, impact} ⇒ 原话＋四计数（事实／类型主体／子术语／引用规则）；
 * - 引用规则计数不能漏（旧页只显三条，`referencing_rules` 是后端 `_fullImpact` 补的第四条）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const listTermsMock = vi.fn()
const createTermMock = vi.fn()
const updateTermMock = vi.fn()
const deleteTermMock = vi.fn()

vi.mock('@/api/modules/ontology', () => ({
  listOntologyTerms: (...args: unknown[]) => listTermsMock(...args),
  createOntologyTerm: (...args: unknown[]) => createTermMock(...args),
  updateOntologyTerm: (...args: unknown[]) => updateTermMock(...args),
  deleteOntologyTerm: (...args: unknown[]) => deleteTermMock(...args),
}))

import StudioTermsSection from '@/pages/ontology-studio/StudioTermsSection.vue'
import { ontologySection } from '@/i18n/locales/_ontologySection'
import { message } from 'ant-design-vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ontology: ontologySection('zh-CN') } },
})

const TERMS = [
  { term_id: 'RiskOrder', kind: 'concept', label: '风险订单', version: 'v1', aliases: [] },
]

const mountSection = () =>
  mount(StudioTermsSection, {
    props: { isAdmin: true },
    global: {
      plugins: [i18n],
      stubs: {
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-input': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-input-search': {
          props: ['value'],
          emits: ['update:value', 'search'],
          template: '<input class="stub-search" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-input-number': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-num" :value="value" @input="$emit(\'update:value\', Number($event.target.value))" />',
        },
        'a-select': { props: ['value'], emits: ['update:value'], template: '<select class="stub-select"><slot /></select>' },
        'a-select-option': { props: ['value'], template: '<option :value="value"><slot /></option>' },
        'a-checkbox': { props: ['checked'], emits: ['update:checked'], template: '<input type="checkbox" />' },
        'a-popconfirm': {
          props: ['title'],
          emits: ['confirm'],
          template: '<span class="stub-popconfirm"><button data-testid="popconfirm-ok" @click="$emit(\'confirm\')"><slot /></button></span>',
        },
        'a-button': { template: '<button class="stub-btn" @click="$emit(\'click\')"><slot /></button>' },
      },
    },
  })

beforeEach(() => {
  listTermsMock.mockReset()
  createTermMock.mockReset()
  updateTermMock.mockReset()
  deleteTermMock.mockReset()
  ;(message.error as ReturnType<typeof vi.fn>).mockReset()
  listTermsMock.mockResolvedValue({ data: { items: TERMS } })
})

describe('StudioTermsSection 拒因回显（从旧工作台口径并进来的那条长板）', () => {
  it('保存失败：后端 detail 原话逐字回显，不降级成通用报错文案', async () => {
    createTermMock.mockRejectedValue({ response: { data: { detail: '定义域术语未登记：Order' } } })
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="terms-new"]').trigger('click')
    await wrapper.find('[data-testid="term-term-id"]').setValue('RiskOrder2')
    await wrapper.find('[data-testid="term-save"]').trigger('click')
    await flushPromises()
    expect(message.error).toHaveBeenCalledWith('定义域术语未登记：Order')
  })

  it('删除被拒：后端 message 逐字＋impact 四计数，引用规则那条不能漏', async () => {
    deleteTermMock.mockRejectedValue({
      response: {
        data: {
          detail: {
            message: '术语被引用，先清引用再删',
            impact: {
              fact_count: 3,
              typed_subject_count: 2,
              child_terms: ['SubA', 'SubB'],
              referencing_rules: ['is_a_transitive'],
            },
          },
        },
      },
    })
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="term-delete"]').trigger('click')
    await flushPromises()
    const shown = String((message.error as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] ?? '')
    expect(shown).toContain('术语被引用，先清引用再删')
    expect(shown).toContain('3')
    expect(shown).toContain('2')
    expect(shown).toContain('1')
  })

  it('删除被拒但后端只给字符串 detail：仍逐字回显，不编造计数', async () => {
    deleteTermMock.mockRejectedValue({ response: { data: { detail: '术语不存在' } } })
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="term-delete"]').trigger('click')
    await flushPromises()
    const shown = String((message.error as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] ?? '')
    expect(shown).toBe('术语不存在')
  })
})
