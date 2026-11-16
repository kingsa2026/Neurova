/**
 * 3.6-7 审计收口（R5）：GROUPS 常量内 agent 深链在 setup 期用 agentId.value
 * 固化——组件存续期间切换 Agent，卡片链接仍指旧 agent。
 * 旧测试（DataHubPage.test.ts）在 mount 前设 currentAgentId，只验证
 * 「mount 时取值」，测不到运行期响应性（假绿）。
 * 修后 to 为函数 (agentId) => string，渲染期取当前 agentId，切 Agent 后
 * 链接跟着走。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick, reactive } from 'vue'

const authUser = { id: 'u1', username: 'tester', role: 'admin' }
const agentState = reactive({ currentAgentId: 'agentX' })

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: authUser }),
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

import DataHubPage from '../DataHubPage.vue'
import zhCN from '@/i18n/locales/zh-CN'
import { ontologySection } from '@/i18n/locales/_ontologySection'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': { ...zhCN, ontology: ontologySection('zh-CN') } },
})

const mountPage = () =>
  mount(DataHubPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-alert': { props: ['message'], template: '<div>{{ message }}</div>' },
        'a-empty': { props: ['description'], template: '<div>{{ description }}</div>' },
        GlassCard: { template: '<div class="stub-card"><slot /></div>' },
      },
    },
  })

const agentCardIds = ['ontology-studio', 'graph-workbench', 'facts']

const hrefs = (wrapper: ReturnType<typeof mount>) =>
  Object.fromEntries(
    agentCardIds.map((id) => [
      id,
      wrapper.find(`[data-testid="hub-card-${id}"]`).find('a').attributes('href'),
    ]),
  )

describe('DataHubPage — 3.6-7 Agent 深链运行期跟随', () => {
  it('mount 后切换 Agent：三张 Agent 级卡片链接跟着走（旧实现固化 setup 期取值）', async () => {
    agentState.currentAgentId = 'agentX'
    const wrapper = mountPage()
    const before = hrefs(wrapper)
    for (const id of agentCardIds) {
      expect(before[id], id).toContain('/agent/agentX/')
    }
    agentState.currentAgentId = 'agentY'
    await nextTick()
    const after = hrefs(wrapper)
    for (const id of agentCardIds) {
      expect(after[id], id).toContain('/agent/agentY/')
      expect(after[id], id).not.toContain('/agent/agentX/')
    }
    agentState.currentAgentId = 'agentX'
  })

  it('点击入口以当前 agentId router.push（非固化值）', async () => {
    agentState.currentAgentId = 'agentX'
    const wrapper = mountPage()
    await wrapper.find('[data-testid="hub-card-ontology-studio"] a').trigger('click')
    expect(pushMock).toHaveBeenCalledWith(expect.stringContaining('/agent/agentX/ontology-studio'))
    agentState.currentAgentId = 'agentY'
    await nextTick()
    await wrapper.find('[data-testid="hub-card-ontology-studio"] a').trigger('click')
    expect(pushMock).toHaveBeenLastCalledWith(expect.stringContaining('/agent/agentY/ontology-studio'))
    agentState.currentAgentId = 'agentX'
  })
})
