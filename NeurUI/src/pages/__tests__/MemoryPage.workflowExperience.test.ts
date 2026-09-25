/**
 * 工单 015 · MemoryPage 的工作流经验类型面（012 登记的前端欠账）。
 *
 * 012 把 `workflow_experience` 加进了后端 MemoryType 枚举，写入方一直在用它——
 * 结果是库里存得住、按类型也检得出来，界面上却筛不出来：页签、新建下拉、色板
 * 三处各自抄了一份类型清单，一处都没跟上。
 *
 * 锁定行为：
 * 1. 类型页签里有工作流经验，且切到该页签真的把 `memory_type` 传给后端（不是只多个壳）；
 * 2. 色板认得它（未知类型会回落成默认靛蓝，跟"没登记"看起来一模一样）；
 * 3. 新建下拉的选项来自 `MEMORY_TYPES` 一份词表，不再手写第二份。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api', () => ({
  request: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('@/composables/useAgentPage', () => ({
  useAgentPage: () => ({ agentId: { value: 'default' } }),
}))

const { getMemoriesMock } = vi.hoisted(() => ({ getMemoriesMock: vi.fn() }))

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual: Record<string, unknown> = await importOriginal()
  return { ...actual, getMemories: getMemoriesMock }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: 'admin' } }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import MemoryPage from '@/pages/MemoryPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

const setupState = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm.$ as unknown as { setupState: Record<string, any> }).setupState

async function mountPage() {
  const wrapper = mount(MemoryPage, { global: { plugins: [i18n] } })
  await flushPromises()
  return wrapper
}

describe('MemoryPage 工作流经验类型面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMemoriesMock.mockResolvedValue({ data: { count: 0, memories: [] } })
  })

  it('页签面出现工作流经验（中文标签来自语言包）', async () => {
    const wrapper = await mountPage()
    expect(wrapper.html()).toContain('workflow_experience')
    expect(zhCN.memory.typeWorkflowExperience).toBe('工作流经验')
  })

  it('切到该页签真的按类型过滤（把 memory_type 传给后端）', async () => {
    const wrapper = await mountPage()
    const state = setupState(wrapper)
    state.activeTab = 'workflow_experience'
    await state.fetchMemories()
    await flushPromises()

    const lastCall = getMemoriesMock.mock.calls.at(-1) ?? []
    expect(lastCall[1]?.memory_type).toBe('workflow_experience')
  })

  it('色板认得工作流经验，而不是回落成默认色', async () => {
    const wrapper = await mountPage()
    const state = setupState(wrapper)
    expect(state.typeColor('workflow_experience')).toBe('#14b8a6')
    expect(state.typeColor('workflow_experience')).not.toBe(state.typeColor('no_such_type'))
  })

  it('新建下拉的选项数与词表一致（不再手写第二份类型清单）', async () => {
    const wrapper = await mountPage()
    const state = setupState(wrapper)
    expect(state.MEMORY_TYPES).toHaveLength(7)
    expect(state.MEMORY_TYPES.map((m: { value: string }) => m.value)).toContain('workflow_experience')
  })
})
