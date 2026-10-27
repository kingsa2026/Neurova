/**
 * 记忆表格对「他人用户域的行」禁用动作并标注（点单「丙」的前端半边）
 *
 * 契约三段：
 * 1. 行级判定只有一个取源 `memoryApi.rowIsActionable(record)`（读后端逐条给的 `owned`），
 *    页面不得再自己比三元组；
 * 2. 四个动作（打开 / ↑强化 / ↓遗忘 / 删除）全部按它禁用，且对 `owned=false` 的行
 *    处理函数**根本不发请求**——按钮 disabled 是给人看的，这道闸是给漏网路径兜的，
 *    两处都只问同一个谓词，不算两份判定；
 * 3. 按 id 寻址的三个调用都带上行自带的 `agent_id`（`viewMemory` 那条是本批修的断口）。
 *
 * 形态说明（诚实标注，别把它当成 DOM 级判据）：本页的表格是 `a-table`，而本仓前端夹具
 * 不注册 Antd（`vi.mock('ant-design-vue')` 只供 `message`），未知组件不渲染 `#bodyCell`
 * 插槽，所以「按钮真的带 disabled 属性」这条在进程内验不出来。先例同形态见
 * `MemoryPage.origin.test.ts`（它也是取 setupState 而不是取 DOM）。
 * 本档因此把可行为化的部分放在处理函数与谓词上，把绑定本身钉成源码形状判据（第 2 格），
 * 真链路的禁用态走活体验证。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'agent_a' } }),
}))

const { authFixture } = vi.hoisted(() => ({ authFixture: { role: 'admin' } }))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: authFixture.role } }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const { apiSpies } = vi.hoisted(() => ({
  apiSpies: {
    getMemories: vi.fn(),
    getMemory: vi.fn(),
    deleteMemory: vi.fn(),
    forgetMemory: vi.fn(),
    strengthenMemory: vi.fn(),
    getMemoryStats: vi.fn(),
  },
}))

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual: Record<string, unknown> = await importOriginal()
  return {
    ...actual,
    getMemories: apiSpies.getMemories,
    getMemory: apiSpies.getMemory,
    deleteMemory: apiSpies.deleteMemory,
    forgetMemory: apiSpies.forgetMemory,
    strengthenMemory: apiSpies.strengthenMemory,
    getMemoryStats: apiSpies.getMemoryStats,
  }
})

import MemoryPage from '@/pages/MemoryPage.vue'
import pageSource from '@/pages/MemoryPage.vue?raw'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

const OWN_ROW = { id: 'm_own', agent_id: 'agent_a', content: '自己的行', type: 'episodic', importance: 0.5, owned: true, created_at: '2026-10-26T00:00:00Z' }
const FOREIGN_ROW = { id: 'm_foreign', agent_id: 'agent_a', content: '他人的行', type: 'episodic', importance: 0.5, owned: false, created_at: '2026-10-26T00:00:00Z' }

const mountPage = async () => {
  const wrapper = mount(MemoryPage, { global: { plugins: [i18n] } })
  await flushPromises()
  return wrapper
}

const setupState = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm.$ as unknown as { setupState: Record<string, any> }).setupState

describe('MemoryPage 行作用域闸门', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiSpies.getMemories.mockResolvedValue({
      data: { count: 2, memories: [OWN_ROW, FOREIGN_ROW] },
    })
    apiSpies.getMemoryStats.mockResolvedValue({ data: { total_memories: 2 } })
    apiSpies.getMemory.mockResolvedValue({ data: { ...OWN_ROW, content: '详情里的内容' } })
    apiSpies.deleteMemory.mockResolvedValue({ data: null })
    apiSpies.forgetMemory.mockResolvedValue({ data: {} })
    apiSpies.strengthenMemory.mockResolvedValue({ data: {} })
  })

  it('他人用户域的行：四个动作一个都不发请求', async () => {
    const state = setupState(await mountPage())

    state.viewMemory(FOREIGN_ROW)
    await flushPromises()
    state.handleForget(FOREIGN_ROW)
    state.handleStrengthen(FOREIGN_ROW)
    await state.confirmDeleteMemory(FOREIGN_ROW)
    await flushPromises()

    expect(apiSpies.getMemory).not.toHaveBeenCalled()
    expect(apiSpies.forgetMemory).not.toHaveBeenCalled()
    expect(apiSpies.strengthenMemory).not.toHaveBeenCalled()
    expect(apiSpies.deleteMemory).not.toHaveBeenCalled()
  })

  it('自己的行照常能动，且按 id 寻址那一路带上行自带的 agent_id', async () => {
    const state = setupState(await mountPage())

    state.viewMemory(OWN_ROW)
    await flushPromises()
    state.handleStrengthen(OWN_ROW)
    await state.confirmDeleteMemory(OWN_ROW)
    await flushPromises()

    // 夹具默认角色是 admin ⇒ 按 id 的读走管理通道（常规路对他人行仍"视同不存在"）
    expect(apiSpies.getMemory).toHaveBeenCalledWith('m_own', 'agent_a', { management: true })
    expect(apiSpies.strengthenMemory).toHaveBeenCalled()
    expect(apiSpies.deleteMemory).toHaveBeenCalledWith('m_own', 'agent_a', { management: true })
  })

  it('非管理员一律打常规路：管理通道不许被"顺手试一下"', async () => {
    authFixture.role = 'user'
    try {
      const state = setupState(await mountPage())

      state.viewMemory(OWN_ROW)
      await state.confirmDeleteMemory(OWN_ROW)
      await flushPromises()

      expect(apiSpies.getMemory).toHaveBeenCalledWith('m_own', 'agent_a', { management: false })
      expect(apiSpies.deleteMemory).toHaveBeenCalledWith('m_own', 'agent_a', { management: false })
    } finally {
      authFixture.role = 'admin'
    }
  })

  it('动作列的四处禁用都只问 rowIsActionable（绑定钉成源码形状）', () => {
    const bound = pageSource.match(/:disabled="!rowIsActionable\(record\)"/g) ?? []

    expect(bound.length).toBe(4)
    // 反向：页面不得另起一份归属猜测（三元组只该留在后端）
    expect(pageSource).not.toContain('neuser_id')
  })

  it('owned=false 的行给出可见标注（i18n 键在 zh-CN 有文本）', () => {
    const msgs = (i18n.global as unknown as { messages: { value: Record<string, any> } }).messages.value['zh-CN']
    expect(msgs.memory.foreignScope).toBeTruthy()
    expect(msgs.memory.foreignScopeTip).toBeTruthy()
    expect(pageSource).toContain("t('memory.foreignScope')")
  })
})
