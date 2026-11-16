/**
 * 3.6-2 审计收口（R5）：isAdmin computed 零引用——W11（P9 拍板②）的
 * admin 真门只定义未接线，导出/导入按钮对所有用户可点（假门）。
 * 本档钉：非 admin 导出/Ossie 导入按钮禁用；admin 可用并可触发下载链。
 * 后端导出/导入端点（knowledge_ontology.py/knowledge_ossie.py）当前仍为
 * 登录门——后端补 require_admin 与本门前端对齐，登记移交总控。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api/modules/ontology', () => ({
  exportOntologyTtl: vi.fn(),
  exportOntologyJsonLd: vi.fn(),
  exportOntologyOwl: vi.fn(),
  exportOntologyShacl: vi.fn(),
  exportOntologyProv: vi.fn(),
  exportOntologyCsv: vi.fn(),
  exportOntologyCypher: vi.fn(),
  exportOntologyGexf: vi.fn(),
  exportOntologyGraphML: vi.fn(),
  exportOssieYaml: vi.fn(),
  importOssieYaml: vi.fn(),
  resolveOntologyIri: vi.fn(),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import { exportOntologyTtl } from '@/api/modules/ontology'
import KnowledgeInteropPage from '../KnowledgeInteropPage.vue'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const ttlMock = exportOntologyTtl as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ontology: ontologySection('zh-CN'), common: { error: '操作失败' } } },
})

const mountPage = () =>
  mount(KnowledgeInteropPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-tag': { template: '<span><slot /></span>' },
        'a-alert': { props: ['message'], template: '<div>{{ message }}</div>' },
        'a-input': { props: ['value'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
        'a-textarea': { props: ['value'], emits: ['update:value'], template: '<textarea :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
        'a-checkbox': { props: ['checked'], template: '<input type="checkbox" />' },
        'a-button': { template: '<button><slot /></button>' },
        GlassPanel: { template: '<div><slot /></div>' },
        GlassButton: {
          props: ['loading', 'disabled', 'variant'],
          emits: ['click'],
          template: '<button class="stub-glass-btn" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })

const btnDisabled = (wrapper: ReturnType<typeof mountPage>, testid: string) =>
  (wrapper.find(`[data-testid="${testid}"]`).element as HTMLButtonElement).disabled

describe('KnowledgeInteropPage — 3.6-2 admin 真门接线', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    ttlMock.mockReset()
  })

  it('非 admin：导出下载按钮禁用（旧实现假门可点）', async () => {
    useAuthStore().user = { user_id: 'u1', username: 'u', role: 'user' } as any
    const wrapper = mountPage()
    await flushPromises()
    expect(btnDisabled(wrapper, 'export-ttl-btn')).toBe(true)
    expect(btnDisabled(wrapper, 'export-jsonld-btn')).toBe(true)
    expect(btnDisabled(wrapper, 'export-ossie-btn')).toBe(true)
  })

  it('非 admin：Ossie 导入按钮禁用', async () => {
    useAuthStore().user = { user_id: 'u1', username: 'u', role: 'user' } as any
    const wrapper = mountPage()
    await flushPromises()
    expect(btnDisabled(wrapper, 'ossie-import-btn')).toBe(true)
  })

  it('admin：导出可用并触发下载链，Ossie 导入在填入文档后可用', async () => {
    useAuthStore().user = { user_id: 'a1', username: 'a', role: 'admin' } as any
    ttlMock.mockResolvedValue('@prefix kbg: <https://neurova.local/knowledge/> .')
    const wrapper = mountPage()
    await flushPromises()
    expect(btnDisabled(wrapper, 'export-ttl-btn')).toBe(false)
    await wrapper.find('[data-testid="export-ttl-btn"]').trigger('click')
    await flushPromises()
    expect(ttlMock).toHaveBeenCalledTimes(1)
    await wrapper.find('[data-testid="ossie-import-input"]').setValue('terms: []')
    expect(btnDisabled(wrapper, 'ossie-import-btn')).toBe(false)
  })
})
