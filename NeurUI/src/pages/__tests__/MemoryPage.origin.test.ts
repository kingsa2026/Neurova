/**
 * P1-9 记忆来源信任分级 — 前端 origin 徽标防回归
 *
 * 契约：
 * 1. MemoryPage 表格渲染 origin 列，untrusted 用橙色警示 Tag；
 * 2. origin 缺失回退 agent（等价旧行为）；
 * 3. i18n 键 memory.origin* 在 zh-CN 存在（11 语言对齐由 i18n 测试兜底）。
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

const { getMemoriesMock } = vi.hoisted(() => ({
  getMemoriesMock: vi.fn(),
}))

vi.mock('@/api/modules/memory', async (importOriginal) => {
  const actual: Record<string, unknown> = await importOriginal()
  return {
    ...actual,
    getMemories: getMemoriesMock,
  }
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

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN },
})

const mountPage = () =>
  mount(MemoryPage, {
    global: { plugins: [i18n] },
  })

describe('MemoryPage origin 徽标（P1-9）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMemoriesMock.mockResolvedValue({
      data: {
        count: 3,
        memories: [
          { id: 'm1', content: '用户原话', type: 'episodic', importance: 0.5, origin: 'owner', created_at: '2026-09-04T00:00:00Z' },
          { id: 'm2', content: '外部抓取', type: 'semantic', importance: 0.5, origin: 'untrusted', created_at: '2026-09-04T00:00:00Z' },
          { id: 'm3', content: '旧记忆', type: 'episodic', importance: 0.5, created_at: '2026-09-04T00:00:00Z' },
        ],
      },
    })
  })

  const setupState = (wrapper: ReturnType<typeof mount>) =>
    (wrapper.vm.$ as unknown as { setupState: Record<string, any> }).setupState

  it('table has origin column with untrusted warning color mapping', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setupState(wrapper)
    const originCol = state.tableColumns.find((c: any) => c.key === 'origin')
    expect(originCol).toBeTruthy()
    expect(state.originColorMap.untrusted).toBe('orange')
    expect(state.originColorMap.owner).toBe('green')
    expect(state.originLabel('untrusted')).toBe('外部（不可信）')
  })

  it('falls back to agent badge when origin missing', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setupState(wrapper)
    expect(state.originLabel(undefined)).toBe('Agent')
    // memories 数据载入正常（origin 字段不破坏既有加载链）
    expect(state.memories.length).toBe(3)
  })

  it('i18n origin keys exist in zh-CN', () => {
    const msgs = (i18n.global as unknown as { messages: { value: Record<string, any> } }).messages.value['zh-CN']
    expect(msgs.memory.origin).toBe('来源')
    expect(msgs.memory.originOwner).toBe('用户')
    expect(msgs.memory.originUntrusted).toBe('外部（不可信）')
    expect(msgs.memory.originUntrustedTip).toBeTruthy()
  })
})
