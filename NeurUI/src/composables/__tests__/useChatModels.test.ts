/**
 * useChatModels — 动作函数组件上下文回归测试（2026-09-09 点击模型无反应）。
 *
 * 根因（ChatPage 拆分 54478927 引入）：pickModel / gotoModelsManage /
 * switchAfterRateLimit / loadChatModels 从组件 setup 迁到模块级后，函数体内
 * useI18n()/useRouter()/useAgentPage() 仍按 setup 期 API 调用——事件处理器中
 * getCurrentInstance() 为 null，useI18n() 第一行即抛
 * "Must be called at the top of a setup function"，点击级联菜单模型项
 * 毫无反应（selectedModel 未更新、菜单不关、无 toast）。
 *
 * 契约：所有动作函数必须可在组件上下文之外调用（@click / SSE 回调）：
 *   - 文案取 i18n.global.t（模块内 selectedModelLabel 已用同一模式）；
 *   - agentId 取 agentStore.currentAgentId（useAgentPage 挂载时已双向同步）；
 *   - 路由跳转用 @/router 单例。
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const { apiPut, routerPush } = vi.hoisted(() => ({
  apiPut: vi.fn(),
  routerPush: vi.fn(),
}))

vi.mock('@/api', () => ({
  api: {
    put: apiPut,
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn(),
  },
}))
vi.mock('@/router', () => ({ default: { push: routerPush } }))
vi.mock('@/api/modules/models', () => ({
  listModels: vi.fn().mockResolvedValue({
    models: [
      { id: 'm2', name: 'Model B', provider_id: 'prov1', enabled: true, connectable: true },
      { id: 'm1', name: 'Model A', provider_id: 'prov1', enabled: true, connectable: true },
    ],
  }),
}))
vi.mock('@/api/modules/providers', () => ({
  listProviders: vi.fn().mockResolvedValue([
    { provider_id: 'prov1', name: 'Provider One' },
  ]),
}))

import { useChatModels } from '../useChatModels'
import { useAgentStore } from '@/stores/agents'

describe('useChatModels — 动作函数脱离组件上下文可调用', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    apiPut.mockReset()
    routerPush.mockReset()
    const m = useChatModels()
    m.selectedModel.value = ''
    m.modelMenuOpen.value = true
    m.rateLimitBanner.value = null
  })

  it('pickModel 在事件处理器上下文外调用不抛异常且完成选型', async () => {
    const store = useAgentStore()
    store.setCurrentAgent('agent-x')
    apiPut.mockResolvedValue({
      data: { id: 'agent-x', name: 'X', model: 'm1', provider: 'prov1' },
    })

    const m = useChatModels()
    await expect(m.pickModel('m1', 'prov1')).resolves.toBeUndefined()

    expect(m.selectedModel.value).toBe('m1')
    expect(m.modelMenuOpen.value).toBe(false)
    expect(apiPut).toHaveBeenCalledWith('/agents/agent-x', {
      model: 'm1',
      provider: 'prov1',
    })
  })

  it('store 无 currentAgentId 时 pickModel 只改本地不发请求', async () => {
    const m = useChatModels()
    await m.pickModel('m1', 'prov1')
    expect(apiPut).not.toHaveBeenCalled()
    expect(m.selectedModel.value).toBe('m1')
  })

  it('gotoModelsManage 在组件上下文外调用可跳转模型管理页', () => {
    const m = useChatModels()
    expect(() => m.gotoModelsManage()).not.toThrow()
    expect(routerPush).toHaveBeenCalledWith('/models')
    expect(m.modelMenuOpen.value).toBe(false)
  })

  it('switchAfterRateLimit 在组件上下文外调用完成切换', () => {
    const m = useChatModels()
    m.rateLimitBanner.value = { model: 'old', alternatives: [] }
    expect(() => m.switchAfterRateLimit('m2')).not.toThrow()
    expect(m.selectedModel.value).toBe('m2')
    expect(m.rateLimitBanner.value).toBeNull()
  })

  it('loadChatModels 在组件上下文外调用可组装分组', async () => {
    const m = useChatModels()
    await m.loadChatModels()

    expect(m.chatModelGroups.value).toHaveLength(1)
    expect(m.chatModelGroups.value[0].provider_name).toBe('Provider One')
    // 组内按名称排序
    expect(m.chatModelGroups.value[0].models.map((x) => x.value)).toEqual(['m1', 'm2'])
    // 扁平选项首位恒为自动路由
    expect(m.chatModelOptions.value[0]).toMatchObject({ value: '', provider_id: '' })
  })
})
