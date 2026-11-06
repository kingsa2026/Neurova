/**
 * DataHubPage — 数据中台总览契约测试。
 *
 * 契约面（§15.4 诚实性 ＋ 2026-11-06 导航重构）：
 * - 卡片按模块目录逐张判可见性：无权项**不渲染**（而不是渲染成禁用/空卡）；
 * - 全部无权时落到显式空态说明，不铺一排空卡片；
 * - Agent 级页面链接必须带当前 agentId（不带就等于把用户丢进 default 的错觉）；
 * - 图谱工作台是一级卡片（与本体工作台并列），不再降格成某张卡上的兼容链接；
 * - 描述文案复用各页自己的 subtitle，本页不另抄一份（同句两处即漂移起点）。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const authUser: { id: string; username: string; role: string; allowed_modules?: string[] } = {
  id: 'u1',
  username: 'tester',
  role: 'admin',
}
;(globalThis as Record<string, unknown>).__dataHubAuthUser = authUser

const agentState: { currentAgentId: string } = { currentAgentId: 'agentX' }

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    get user() {
      return (globalThis as Record<string, unknown>).__dataHubAuthUser
    },
  }),
}))

vi.mock('@/stores/agents', () => ({
  useAgentStore: () => agentState,
}))

const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import DataHubPage from '@/pages/DataHubPage.vue'
import zhCN from '@/i18n/locales/zh-CN'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ...zhCN,
      ontology: ontologySection('zh-CN'),
    },
  },
})

const mountPage = () =>
  mount(DataHubPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-alert': { props: ['message'], template: '<div class="stub-alert">{{ message }}</div>' },
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        GlassCard: { template: '<div class="stub-card"><slot /></div>' },
      },
    },
  })

const CARD_IDS = [
  'knowledge', 'enterprise-sources', 'ontology-studio', 'graph-workbench', 'facts',
  'interop', 'knowledge-eval',
]

describe('DataHubPage（数据中台总览）', () => {
  it('管理员：七个能力卡全渲染，分组标题齐，页面说明可见', () => {
    authUser.role = 'admin'
    delete authUser.allowed_modules
    const wrapper = mountPage()
    for (const id of CARD_IDS) {
      expect(wrapper.find(`[data-testid="hub-card-${id}"]`).exists(), id).toBe(true)
    }
    for (const group of ['knowledge', 'semantic', 'interop']) {
      expect(wrapper.find(`[data-testid="hub-group-${group}"]`).exists()).toBe(true)
    }
    expect(wrapper.find('[data-testid="hub-hint"]').text()).toContain('不新造第二套数据页')
    expect(wrapper.find('[data-testid="hub-empty"]').exists()).toBe(false)
  })

  it('Agent 级卡片链接带当前 agentId；切 agent 后链接跟着走', () => {
    agentState.currentAgentId = 'agentY'
    const wrapper = mountPage()
    for (const id of ['ontology-studio', 'graph-workbench', 'facts']) {
      const href = wrapper.find(`[data-testid="hub-card-${id}"]`).find('a').attributes('href')
      expect(href, id).toContain(`/agent/agentY/${id}`)
    }
    agentState.currentAgentId = 'agentX'
  })

  it('受限用户组：只渲染授权命中的卡片，其余分组整组不出现（不铺空卡）', () => {
    authUser.role = 'user'
    authUser.allowed_modules = ['/knowledge']
    const wrapper = mountPage()
    expect(wrapper.find('[data-testid="hub-card-knowledge"]').exists()).toBe(true)
    // /knowledge 目录键前缀命中 /knowledge/interop，分组语义上属互通——但企业源/评测仍应缺席
    expect(wrapper.find('[data-testid="hub-card-knowledge-eval"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="hub-card-ontology-studio"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="hub-card-graph-workbench"]').exists()).toBe(false)
    expect(wrapper.find(`[data-testid="hub-group-semantic"]`).exists()).toBe(false)
    authUser.role = 'admin'
    delete authUser.allowed_modules
  })

  it('全无授权：显式空态，不渲染任何卡片', () => {
    authUser.role = 'user'
    authUser.allowed_modules = ['/analytics']
    const wrapper = mountPage()
    for (const id of CARD_IDS) {
      expect(wrapper.find(`[data-testid="hub-card-${id}"]`).exists(), id).toBe(false)
    }
    const empty = wrapper.find('[data-testid="hub-empty"]')
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toContain('没有中台内任何模块的授权')
    authUser.role = 'admin'
    delete authUser.allowed_modules
  })

  it('点击卡片入口走 router.push（不是裸 href 跳转，SPA 内导航不丢状态）', async () => {
    pushMock.mockClear()
    const wrapper = mountPage()
    await wrapper.find('[data-testid="hub-card-interop"] a').trigger('click')
    expect(pushMock).toHaveBeenCalledWith('/knowledge/interop')
  })

  it('描述文案复用目标页自己的 subtitle（同句两处即漂移起点）', () => {
    const wrapper = mountPage()
    const desc = wrapper.find('[data-testid="hub-card-ontology-studio"] .card-desc').text()
    // zh-CN 的本体工作台副标题原文（改文案只需改一处，本页跟着变）
    expect(desc).toBe((ontologySection('zh-CN') as Record<string, string>).studioSubtitle)
  })
})
