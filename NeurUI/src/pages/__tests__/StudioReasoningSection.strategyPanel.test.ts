/**
 * 3.6-13 审计收口（R5）：求值策略切换纯本地翻转（switchStrategy 只翻
 * evalStrategy ref，后端 rule_engine.setEvaluationStrategy 无 HTTP 端点）
 * ——假交互退役，策略面板改只读展示。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'a', role: 'admin' } }),
}))

vi.mock('@/api/modules/ontology', () => ({
  runOntologyAbduce: vi.fn(),
  runOntologySparql: vi.fn(),
}))

import StudioReasoningSection from '../ontology-studio/StudioReasoningSection.vue'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ontology: ontologySection('zh-CN') } },
})

const mountSection = () =>
  mount(StudioReasoningSection, {
    global: {
      plugins: [i18n],
      stubs: {
        GlassButton: { props: ['variant', 'size'], emits: ['click'], template: '<button class="gb"><slot /></button>' },
        'a-alert': { props: ['message'], template: '<div>{{ message }}</div>' },
      },
    },
    props: { schema: { rules: [] } as never },
  })

describe('StudioReasoningSection — 3.6-13 策略面板只读化', () => {
  it('策略面板不再渲染本地翻转按钮（无后端切换端点），只读展示缺省策略', () => {
    const wrapper = mountSection()
    const panel = wrapper.find('[data-testid="strategy-panel"]')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('full_replay')
    expect(panel.findAll('button').length).toBe(0)
  })
})
