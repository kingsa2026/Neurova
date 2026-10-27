/**
 * 记忆页调用增强族时，作用域取"这一行自己的 agent_id / 当前页的 agent"
 *
 * 后端把六条腿接上 `agent_id` 之后，前端不传就等于没修：装配点仍会回落 default，
 * 而 `mem_%06d` 是每个库自己的计数器 ⇒ 在 kai 页面按 ↓ 动的可能是 default 的同 id 行。
 *
 * 口径与 §6-425 已裁的读改删腿一字相同：
 * - **行级**（↑ 强化 / ↓ 遗忘）取该行自带的 `record.agent_id`，不取页面当前值——
 *   表格里可能混着别的来源渲染出的行；
 * - **页级**（导出 / 导入）取当前 `agentId`。
 *
 * 反向一格：`owned=false` 的行照旧一个请求都不发（上一批那道闸，不许因为这批
 * 加了作用域就顺手放开）。
 *
 * 形态说明：本页夹具不注册 Antd（`vi.mock('ant-design-vue')` 只供 `message`），
 * 表格插槽不渲染，所以取 `setupState` 的处理函数来跑真调用，绑定本身钉成源码形状。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
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
  useRoute: () => ({ query: {}, path: '/agent/agent_a/memory', fullPath: '/agent/agent_a/memory' }),
}))
vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const { apiSpies } = vi.hoisted(() => ({
  apiSpies: {
    getMemories: vi.fn(),
    getMemoryStats: vi.fn(),
    strengthenMemory: vi.fn(),
    forgetMemory: vi.fn(),
    exportMemories: vi.fn(),
    importMemories: vi.fn(),
  },
}))

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual: Record<string, unknown> = await importOriginal()
  return { ...actual, ...apiSpies }
})

import MemoryPage from '@/pages/MemoryPage.vue'
import pageSource from '@/pages/MemoryPage.vue?raw'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

const OWN_ROW = {
  id: 'mem_000006',
  agent_id: 'kai',
  content: '本作用域的行',
  type: 'episodic',
  importance: 0.4,
  owned: true,
  created_at: '2026-10-26T00:00:00Z',
}
const FOREIGN_ROW = { ...OWN_ROW, id: 'mem_000099', owned: false, content: '他人用户域的行' }

const setupState = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm.$ as unknown as { setupState: Record<string, any> }).setupState

const mountPage = async () => {
  const wrapper = mount(MemoryPage, { global: { plugins: [i18n] } })
  await flushPromises()
  return wrapper
}

describe('记忆页把作用域透给增强族', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authFixture.role = 'admin'
    apiSpies.getMemories.mockResolvedValue({ data: { count: 1, memories: [OWN_ROW] } })
    apiSpies.getMemoryStats.mockResolvedValue({ data: { total_memories: 1 } })
    apiSpies.strengthenMemory.mockResolvedValue({ data: {} })
    apiSpies.forgetMemory.mockResolvedValue({ data: {} })
    apiSpies.exportMemories.mockResolvedValue({ data: { memories: [] } })
    apiSpies.importMemories.mockResolvedValue({ data: { imported: 0, skipped: 0, errors: [] } })
  })

  it('↑ 与 ↓ 带的是**这一行**的 agent_id，不是页面当前值', async () => {
    const state = setupState(await mountPage())

    state.handleStrengthen(OWN_ROW)
    await flushPromises()
    state.handleForget(OWN_ROW)
    await flushPromises()

    expect(apiSpies.strengthenMemory.mock.calls.at(-1)).toContain('kai')
    expect(apiSpies.forgetMemory.mock.calls.at(-1)).toContain('kai')
    // 页面当前 agent 是 agent_a（夹具），行是 kai ⇒ 取行的那个值
    expect(apiSpies.strengthenMemory.mock.calls.at(-1)).not.toContain('agent_a')
  })

  it('导出带当前页的 agent_id', async () => {
    const state = setupState(await mountPage())
    await state.handleExport()
    await flushPromises()

    const call = apiSpies.exportMemories.mock.calls.at(-1)
    expect(call?.[1]).toBe('agent_a')
  })

  it('导入带当前页的 agent_id', async () => {
    const state = setupState(await mountPage())
    // setupState 代理会解包 ref：写 `.value` 等于往一个字符串上挂属性，静默无效
    state.importJson = JSON.stringify([{ content: 'x', category: 'general' }])
    await state.handleImport()
    await flushPromises()

    const call = apiSpies.importMemories.mock.calls.at(-1)
    expect(call?.[2]).toBe('agent_a')
  })

  it('反向：他人用户域的行照旧一个请求都不发（这批不加闸也不放闸）', async () => {
    const state = setupState(await mountPage())

    state.handleStrengthen(FOREIGN_ROW)
    state.handleForget(FOREIGN_ROW)
    await flushPromises()

    expect(apiSpies.strengthenMemory).not.toHaveBeenCalled()
    expect(apiSpies.forgetMemory).not.toHaveBeenCalled()
  })

  it('行级两处调用都取 record.agent_id（绑定钉成源码形状，防后来人改用页面当前值）', () => {
    const src = pageSource.replace(/\r\n/g, '\n')
    expect((src.match(/strengthenMemory\(\s*record\.id,\s*[^)]*record\.agent_id\s*\)/) ?? []).length).toBe(1)
    expect((src.match(/forgetMemory\(\s*record\.id,\s*[^)]*record\.agent_id\s*\)/) ?? []).length).toBe(1)
    expect(src).toContain(zhCN.common.noData) // 空态那一格仍在（真空数据时照常出现）
  })
})
