/**
 * 3.6-12 审计收口（R5）：Escape 监听组件卸载残留——panelOpen=true 挂
 * document keydown 监听后，组件卸载（watch 的 false 分支不再走）监听残留，
 * 闭包引用已卸载组件。修后 onUnmounted 摘除。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({
    agents: [{ id: 'a1', name: 'Alpha' }],
    currentAgent: { id: 'a1', name: 'Alpha' },
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

import AgentSwitcher from '../../components/AgentSwitcher.vue'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, fallbackWarn: false, messages: { 'zh-CN': { agent: { selectAgent: '选择 Agent' } } } })

describe('AgentSwitcher — 3.6-12 Escape 监听卸载清理', () => {
  let removeSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    removeSpy = vi.spyOn(document, 'removeEventListener')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('面板开着时卸载组件 → keydown 监听被摘除（旧实现残留）', async () => {
    const wrapper = mount(AgentSwitcher, {
      global: { plugins: [i18n] },
      attachTo: document.body,
    })
    // 开面板（watch 挂监听）
    await wrapper.find('.nr-as-trigger').trigger('click')
    removeSpy.mockClear()
    wrapper.unmount()
    expect(removeSpy).toHaveBeenCalledWith('keydown', expect.any(Function))
  })
})
