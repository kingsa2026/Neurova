/**
 * MemoryLineageDrawer — 记忆世代链抽屉（T1 用户可见面）
 *
 * 契约：
 * 1. 打开即按 agent+memoryId 取世代链，展示各代内容与修订/合并依据；
 * 2. 边方向一律旧代 → 新代：superseded_by（被修订，带依据）与
 *    merged_into（合并来源）分色呈现；
 * 3. 退役行显式标注（不把"已退役"演成"还在役"）；
 * 4. 取不到链时是空态，不是装出来的弧线。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import MemoryLineageDrawer from '@/components/MemoryLineageDrawer.vue'
import zhCN from '@/i18n/locales/zh-CN'

// message.error 是挂在 document.body 的全局 toast，wrapper.text() 看不到——mock 后断言调用
const messageMock = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }))
vi.mock('ant-design-vue', async (importOriginal) => {
  const mod = await importOriginal<typeof import('ant-design-vue')>()
  return { ...mod, message: messageMock }
})

const api = vi.hoisted(() => ({
  getMemoryLineage: vi.fn(),
}))

vi.mock('@/api/modules/memory', () => api)

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })

function lineage(overrides: Record<string, unknown> = {}) {
  return {
    root_id: 'mem_000002',
    max_depth: 5,
    nodes: [
      { id: 'mem_000001', content: '用户的项目使用 PostgreSQL', lifecycle_stage: 'forgotten', created_at: '2026-11-17T00:00:00', is_root: false },
      { id: 'mem_000002', content: '用户的项目已改用 MySQL', lifecycle_stage: 'active', created_at: '2026-11-18T00:00:00', is_root: true },
    ],
    edges: [
      { from: 'mem_000001', to: 'mem_000002', relation: 'superseded_by', basis: '同一属性 database 的取值互斥', at: '2026-11-18T00:00:00' },
    ],
    ...overrides,
  }
}

const mountDrawer = () => mount(MemoryLineageDrawer, {
  props: { open: true, agentId: 'default', memoryId: 'mem_000002' },
  global: { plugins: [i18n] },
})

describe('MemoryLineageDrawer', () => {
  beforeEach(() => {
    api.getMemoryLineage.mockReset()
    messageMock.error.mockClear()
  })

  it('打开时按 agent+memoryId 拉取世代链并展示各代内容', async () => {
    api.getMemoryLineage.mockResolvedValue({ data: { data: lineage() } })
    const wrapper = mountDrawer()
    await flushPromises()
    expect(api.getMemoryLineage).toHaveBeenCalledWith('default', 'mem_000002')
    const text = wrapper.text()
    expect(text).toContain('用户的项目使用 PostgreSQL')
    expect(text).toContain('用户的项目已改用 MySQL')
    expect(text).toContain('同一属性 database 的取值互斥')
  })

  it('退役行显式标注，不把已退役演成在役', async () => {
    api.getMemoryLineage.mockResolvedValue({ data: { data: lineage() } })
    const wrapper = mountDrawer()
    await flushPromises()
    expect(wrapper.text()).toContain('已退役')
  })

  it('合并边与修订边分色呈现（relation 徽标）', async () => {
    api.getMemoryLineage.mockResolvedValue({ data: { data: lineage({
      nodes: [
        { id: 'mem_000001', content: '来源一', lifecycle_stage: 'forgotten', created_at: 't1', is_root: false },
        { id: 'mem_000003', content: '来源二', lifecycle_stage: 'forgotten', created_at: 't2', is_root: false },
        { id: 'merged_1', content: '合并产物', lifecycle_stage: 'active', created_at: 't3', is_root: true },
      ],
      edges: [
        { from: 'mem_000001', to: 'merged_1', relation: 'merged_into' },
        { from: 'mem_000003', to: 'merged_1', relation: 'merged_into' },
      ],
    }) } })
    const wrapper = mountDrawer()
    await flushPromises()
    expect(wrapper.text()).toContain('合并来源')
  })

  it('取不到链时是空态', async () => {
    api.getMemoryLineage.mockRejectedValue(new Error('404'))
    mountDrawer()
    await flushPromises()
    expect(messageMock.error).toHaveBeenCalledWith('世代链加载失败')
  })
})
