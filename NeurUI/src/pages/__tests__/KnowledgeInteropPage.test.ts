/**
 * KnowledgeInteropPage — UI-2 互操作与导出契约测试。
 *
 * 契约面：
 * - 导出格式卡：Turtle 可下载（走 GET /ontology/export.ttl）；
 *   五格式均有 REST 下载按钮（Turtle/JSON-LD/OWL/SHACL/PROV）；
 * - 稳定 IRI 解析：命中渲染 term 行与复制按钮；未知 IRI 显式报错（不静默）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/ontology', () => ({
  exportOntologyTtl: vi.fn(),
  exportOntologyJsonLd: vi.fn(),
  exportOntologyOwl: vi.fn(),
  exportOntologyShacl: vi.fn(),
  exportOntologyProv: vi.fn(),
  resolveOntologyIri: vi.fn(),
  accessQuery: vi.fn(),
  accessAnalyze: vi.fn(),
  accessValidate: vi.fn(),
  accessUse: vi.fn(),
  getDerivationChain: vi.fn(),
  getOntologySchema: vi.fn(),
  listOntologyTerms: vi.fn(),
  listRelationCandidates: vi.fn(),
  createOntologyTerm: vi.fn(),
  updateOntologyTerm: vi.fn(),
  deleteOntologyTerm: vi.fn(),
  approveRelationCandidate: vi.fn(),
  rejectRelationCandidate: vi.fn(),
  runOntologyPipeline: vi.fn(),
  getOntologyPipelineDiff: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import { message } from 'ant-design-vue'
import {
  exportOntologyJsonLd,
  exportOntologyTtl,
  resolveOntologyIri,
} from '@/api/modules/ontology'
import KnowledgeInteropPage from '@/pages/KnowledgeInteropPage.vue'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const exportMock = exportOntologyTtl as unknown as ReturnType<typeof vi.fn>
const jsonLdMock = exportOntologyJsonLd as unknown as ReturnType<typeof vi.fn>
const resolveMock = resolveOntologyIri as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { error: '操作失败', copied: '已复制' },
    },
  },
})

const mountPage = () =>
  mount(KnowledgeInteropPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-alert': { props: ['message'], template: '<div class="stub-alert">{{ message }}</div>' },
        'a-input': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-button': { template: '<button class="stub-a-btn"><slot /></button>' },
        GlassPanel: { template: '<div class="stub-panel"><slot /></div>' },
        GlassButton: {
          props: ['loading', 'disabled', 'variant'],
          emits: ['click'],
          template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })

beforeEach(() => {
  exportMock.mockReset()
  jsonLdMock.mockReset()
  resolveMock.mockReset()
  ;(message.success as ReturnType<typeof vi.fn>).mockClear()
  ;(message.error as ReturnType<typeof vi.fn>).mockClear()
})

describe('KnowledgeInteropPage（UI-2）', () => {
  it('导出格式卡：五格式都有下载按钮（REST 已接线）', async () => {
    const wrapper = mountPage()
    for (const key of ['ttl', 'jsonld', 'owl', 'shacl', 'prov']) {
      expect(wrapper.find(`[data-testid="export-${key}-card"]`).exists()).toBe(true)
      expect(wrapper.find(`[data-testid="export-${key}-btn"]`).exists()).toBe(true)
    }
  })

  it('JSON-LD 下载：走 GET /ontology/export.jsonld；失败显式报错不吞', async () => {
    const wrapper = mountPage()
    jsonLdMock.mockRejectedValueOnce(new Error('403'))
    await wrapper.find('[data-testid="export-jsonld-btn"]').trigger('click')
    await flushPromises()
    expect(jsonLdMock).toHaveBeenCalledTimes(1)
    expect(message.error).toHaveBeenCalled()
  })

  it('Turtle 下载：走 GET /ontology/export.ttl；失败显式报错不吞', async () => {
    const wrapper = mountPage()
    exportMock.mockRejectedValueOnce(new Error('403'))
    await wrapper.find('[data-testid="export-ttl-btn"]').trigger('click')
    await flushPromises()
    expect(exportMock).toHaveBeenCalledTimes(1)
    expect(message.error).toHaveBeenCalled()
  })

  it('IRI 解析：kbg: 命中渲染 term 行；未知 IRI 显式报错', async () => {
    resolveMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        kind: 'term',
        term_id: 'HighRiskOrder',
        term: { term_id: 'HighRiskOrder', kind: 'concept', label: '高风险订单', external_iris: {} },
      },
    })
    const wrapper = mountPage()
    await wrapper.find('[data-testid="iri-input"]').setValue('kbg:HighRiskOrder')
    await wrapper.find('[data-testid="iri-resolve-btn"]').trigger('click')
    await flushPromises()
    const result = wrapper.find('[data-testid="iri-result"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('HighRiskOrder')
    expect(result.text()).toContain('高风险订单')

    resolveMock.mockRejectedValueOnce(new Error('404'))
    await wrapper.find('[data-testid="iri-input"]').setValue('kbg:Unknown')
    await wrapper.find('[data-testid="iri-resolve-btn"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="iri-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="iri-result"]').exists()).toBe(false)
  })
})
