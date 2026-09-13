/**
 * AgentMediaPage 搜索后端化防回归（台账 2026-09-11 第七节 ③）。
 *
 * 原缺陷：搜索为纯前端过滤（filteredMedia 本地 includes），只覆盖已加载的
 * limit 页（约 50 条），数据量大时搜不到未加载条目。
 *
 * 契约锁定：
 * 1. 搜索输入经 300ms 防抖后走服务端 listMedia({ search })，连续输入合并为一次；
 * 2. 搜索变化回到第一页（与既有分页协同 offset=0）；
 * 3. 服务端结果不得被本地二次过滤误删（后端同时匹配 media_id，本地 name
 *    includes 会吞掉仅 id 命中的条目——旧实现即此根因）；
 * 4. 类型切换走服务端 media_type 并重置页码；
 * 5. 空搜索不携带 search 参数（向后兼容全量列表）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

const { listMediaMock, getMediaMock } = vi.hoisted(() => ({
  listMediaMock: vi.fn(),
  getMediaMock: vi.fn(),
}))

vi.mock('@/api/modules/media', () => ({
  listMedia: listMediaMock,
  getMedia: getMediaMock,
  getMediaInfo: vi.fn(),
  downloadMedia: vi.fn(),
  deleteMedia: vi.fn(),
  batchDeleteMedia: vi.fn(),
  saveMedia: vi.fn(),
}))

import AgentMediaPage from '@/pages/AgentMediaPage.vue'

const stubs = {
  GlassPanel: { template: '<div class="glass-panel"><slot /></div>' },
  GlassCard: { template: '<div class="glass-card"><slot /></div>' },
  GlassButton: { template: '<button class="glass-btn"><slot /></button>' },
  'a-spin': { template: '<div><slot /></div>' },
  'a-empty': { template: '<div class="a-empty"><slot /></div>' },
}

function envelope(items: { media_id: string; filename: string; media_type?: string }[]) {
  return {
    code: 0,
    message: 'ok',
    data: {
      media: items.map((m) => ({
        media_id: m.media_id,
        filename: m.filename,
        media_type: m.media_type ?? 'image',
        mime_type: 'image/png',
        size: 10,
        agent_id: 'a1',
        user_id: null,
        memory_id: null,
        storage_path: `media_storage/a1/image/${m.media_id}_${m.filename}`,
        created_at: 1760000000,
        metadata: {},
      })),
      total: items.length,
      offset: 0,
      limit: 50,
    },
  }
}

function mountPage() {
  const i18n = createI18n({
    legacy: false,
    locale: 'zh-CN',
    missingWarn: false,
    fallbackWarn: false,
    messages: { 'zh-CN': { media: {}, common: {} } },
  })
  return mount(AgentMediaPage, { props: { agentId: 'a1' }, global: { plugins: [i18n], stubs } })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
  listMediaMock.mockResolvedValue(envelope([{ media_id: 'media-1', filename: 'a.png' }]))
  getMediaMock.mockRejectedValue(new Error('no preview'))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('AgentMediaPage 搜索后端化', () => {
  it('首屏按 agent_id 拉取且不携带 search', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listMediaMock).toHaveBeenCalledWith(
      expect.objectContaining({ agent_id: 'a1', search: undefined }),
    )
    wrapper.unmount()
  })

  it('输入 300ms 防抖后以 search 走服务端；未到窗口不请求', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const initialCalls = listMediaMock.mock.calls.length

    ;(wrapper.vm as any).searchQuery = 'clip'
    await vi.advanceTimersByTimeAsync(299)
    expect(listMediaMock.mock.calls.length).toBe(initialCalls)

    await vi.advanceTimersByTimeAsync(2)
    await flushPromises()
    expect(listMediaMock).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'clip' }))
    wrapper.unmount()
  })

  it('连续输入合并为一次请求，取最新值', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const initialCalls = listMediaMock.mock.calls.length

    ;(wrapper.vm as any).searchQuery = 'c'
    await vi.advanceTimersByTimeAsync(100)
    ;(wrapper.vm as any).searchQuery = 'cl'
    await vi.advanceTimersByTimeAsync(100)
    ;(wrapper.vm as any).searchQuery = 'clip'
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()

    expect(listMediaMock.mock.calls.length).toBe(initialCalls + 1)
    expect(listMediaMock).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'clip' }))
    wrapper.unmount()
  })

  it('搜索时回到第一页（分页协同 offset=0）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    ;(wrapper.vm as any).currentPage = 3

    ;(wrapper.vm as any).searchQuery = 'q'
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect((wrapper.vm as any).currentPage).toBe(1)
    wrapper.unmount()
  })

  it('服务端命中结果不被本地二次过滤误删（如仅 media_id 命中的条目仍渲染）', async () => {
    // 后端 search 同时匹配 filename 与 media_id；返回 name 不含关键词属正常命中
    listMediaMock.mockResolvedValue(
      envelope([{ media_id: 'media-ff00aa', filename: 'unrelated-photo.png' }]),
    )
    const wrapper = mountPage()
    await flushPromises()

    ;(wrapper.vm as any).searchQuery = 'ff00'
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(wrapper.text()).toContain('unrelated-photo.png')
    wrapper.unmount()
  })

  it('类型切换走服务端 media_type 并重置页码', async () => {
    const wrapper = mountPage()
    await flushPromises()
    ;(wrapper.vm as any).currentPage = 2

    ;(wrapper.vm as any).typeFilter = 'audio'
    await flushPromises()

    expect(listMediaMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ media_type: 'audio' }),
    )
    expect((wrapper.vm as any).currentPage).toBe(1)
    wrapper.unmount()
  })
})
