/**
 * 记忆页：身份失败与「暂无数据」不得合并成同一格
 *
 * 本仓既有纪律（`MobilePairingPanel.vue` 的「权限态与空态不合并」注释、
 * `AgentChannelPage.vue` 的 accessDenied 独立一格）早已写明：401/403 要说
 * 「未登录/无权」，不能退化成「暂无数据」——后者把登录问题伪装成空数据集。
 * 记忆面自 §6-429 起一律要凭证，这一族当时漏扫了记忆页：401 落进通用
 * `message.error`，页面渲染 `common.noData`，并把英文原文 `Request failed with
 * status code 401` 直接弹给中文用户。
 *
 * 形态说明（诚实标注）：本页夹具不注册 Antd，`a-empty` 落到 DOM 上是一个带
 * `description` 属性的原生标签，因此空态那一格可以按属性定点断言，不用整页文本
 * 包含（那会被别处的同名串撞出假绿）。
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

const { authFixture, routerPush } = vi.hoisted(() => ({
  authFixture: { role: 'admin' },
  routerPush: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: authFixture.role } }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
  // 真路径见 router 的 AgentMemory 记录：/agent/:agentId/memory（/memory 并不存在，
  // 它会被 catch-all 兜到 /dashboard——写假路径的判据等于没测深链）
  useRoute: () => ({ query: {}, path: '/agent/agent_a/memory', fullPath: '/agent/agent_a/memory?tab=stats' }),
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
  return { ...actual, ...apiSpies }
})

import { message } from 'ant-design-vue'
import MemoryPage from '@/pages/MemoryPage.vue'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

const httpError = (status: number) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { detail: 'Not authenticated' } },
  })

const emptySlot = () =>
  `a-empty[description="${zhCN.common.noData}"]`

const mountPage = async () => {
  const wrapper = mount(MemoryPage, { global: { plugins: [i18n] } })
  await flushPromises()
  return wrapper
}

const setupState = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm.$ as unknown as { setupState: Record<string, any> }).setupState

describe('记忆页身份态与空态分离', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authFixture.role = 'admin'
  })

  it('401：说「需要登录」，并且不再渲染「暂无数据」', async () => {
    apiSpies.getMemories.mockRejectedValue(httpError(401))
    apiSpies.getMemoryStats.mockRejectedValue(httpError(401))

    const wrapper = await mountPage()

    const notice = wrapper.find('[data-testid="memory-identity-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain(zhCN.memory.identityRequired)
    expect(wrapper.find(emptySlot()).exists()).toBe(false)
  })

  it('401 不把英文原文弹成红 toast', async () => {
    apiSpies.getMemories.mockRejectedValue(httpError(401))
    apiSpies.getMemoryStats.mockRejectedValue(httpError(401))

    await mountPage()

    expect(message.error).not.toHaveBeenCalled()
  })

  it('403：说「无权访问」，同样不伪装成空数据', async () => {
    apiSpies.getMemories.mockRejectedValue(httpError(403))
    apiSpies.getMemoryStats.mockRejectedValue(httpError(403))

    const wrapper = await mountPage()

    const notice = wrapper.find('[data-testid="memory-identity-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain(zhCN.memory.identityDenied)
    expect(wrapper.find(emptySlot()).exists()).toBe(false)
  })

  it('反向：500 这类真故障照旧红 toast，且不被写成「需要登录」（不许借道吞报错）', async () => {
    apiSpies.getMemories.mockRejectedValue(httpError(500))
    apiSpies.getMemoryStats.mockRejectedValue(httpError(500))

    const wrapper = await mountPage()

    expect(message.error).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="memory-identity-notice"]').exists()).toBe(false)
  })

  it('读腿恢复后身份格自己收摊（写→读→反馈闭环，不留一句过期的「请登录」）', async () => {
    apiSpies.getMemories.mockRejectedValue(httpError(401))
    apiSpies.getMemoryStats.mockRejectedValue(httpError(401))
    const wrapper = await mountPage()
    expect(wrapper.find('[data-testid="memory-identity-notice"]').exists()).toBe(true)

    apiSpies.getMemories.mockResolvedValue({ data: { count: 1, memories: [] } })
    await setupState(wrapper).fetchMemories()
    await flushPromises()

    expect(wrapper.find('[data-testid="memory-identity-notice"]').exists()).toBe(false)
  })

  it('去登录那一眼带走目的地：push 的是带 redirect 的登录位置', async () => {
    apiSpies.getMemories.mockRejectedValue(httpError(401))
    apiSpies.getMemoryStats.mockRejectedValue(httpError(401))

    const wrapper = await mountPage()
    await wrapper.find('[data-testid="memory-go-login"]').trigger('click')

    expect(routerPush).toHaveBeenCalledTimes(1)
    const target = String(routerPush.mock.calls[0][0])
    expect(target).toMatch(/^\/login\?redirect=/)
    expect(new URL(target, 'http://localhost:8100').searchParams.get('redirect')).toBe(
      '/agent/agent_a/memory?tab=stats',
    )
  })
})
