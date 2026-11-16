/**
 * 3.6-14 审计收口（R5）：NeuronPage 5 处错误只进 console 无用户提示——
 * 加载（stats/entities/dependencies）失败提示 loadFailed，操作（级联推理/
 * 缺失检测）失败提示 actionFailed（console 保留供排障）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick } from 'vue'

const { apiMock } = vi.hoisted(() => {
  const apiMock = {
    get: vi.fn(),
    post: vi.fn(),
  }
  return { apiMock }
})

vi.mock('@/api', () => ({ default: apiMock, api: apiMock, request: apiMock }))

vi.mock('ant-design-vue', async () => {
  const { message } = await vi.importActual<any>('ant-design-vue')
  return { message: { ...message, error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() } }
})

import NeuronPage from '../../views/NeuronPage.vue'
import { message } from 'ant-design-vue'
import zhCN from '@/i18n/locales/zh-CN'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', missingWarn: false, fallbackWarn: false, messages: { 'zh-CN': zhCN as never } })

const passthrough = { template: '<div><slot /></div>' }
const antStubs = Object.fromEntries(
  ['a-tabs', 'a-tab-pane', 'a-input', 'a-select', 'a-select-option', 'a-input-number',
    'a-button', 'a-tag', 'a-card', 'a-spin', 'a-empty', 'a-descriptions',
    'a-descriptions-item', 'a-statistic'].map((name) => [name, passthrough]),
)

function mountPage() {
  return mount(NeuronPage, {
    global: { plugins: [i18n], stubs: { GlassPanel: passthrough, GlassButton: passthrough, GlassCard: passthrough, ...antStubs } },
  })
}

describe('NeuronPage — 3.6-14 错误用户提示', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.get.mockResolvedValue({ data: { code: 0, data: { total_entities: 0, total_edges: 0, entity_types: 0, dependency_types: 0 } } })
  })

  it('加载失败（stats/entities reject）→ message.error 提示（旧实现只进 console）', async () => {
    apiMock.get.mockRejectedValue(new Error('boom'))
    mountPage()
    await flushPromises()
    expect(message.error).toHaveBeenCalled()
  })

  it('级联推理失败 → message.error(actionFailed)', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.cascadeForm.entityId = 'e1'
    apiMock.post.mockRejectedValue(new Error('boom'))
    await vm.runCascade()
    await flushPromises()
    expect(message.error).toHaveBeenCalled()
    expect((message.error as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe('操作执行失败')
  })
})
