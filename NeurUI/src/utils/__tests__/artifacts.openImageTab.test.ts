/**
 * openImageTab 去重键与 URL 归属契约（台账 #18/#11，2026-09-11）。
 *
 * #18：附件预览每次点击 fetch 自建新 blob URL，若按 url 去重则同附件重复
 * 点击生成新 tab 不回焦——dedupeKey 用稳定标识（fileId/消息 preview）后，
 * 同附件回焦既有 tab。
 * #11/#12 契约：不传 createdBy → data.createdBy 为 undefined（外来 URL，
 * 面板不 revoke，内联图 img.src 路径锁存）；传 createdBy:'panel' → 透传，
 * 面板按所有权释放。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { openImageTab, shortHash } from '@/utils/artifacts'
import { useRightDockStore } from '@/stores/rightDock'

describe('openImageTab 去重键与归属（#18/#11/#12）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('同 dedupeKey 不同自建 url：不新增 tab，回焦并更新 data.url', () => {
    const dock = useRightDockStore()
    const id = `img:${shortHash('file-f1')}`
    openImageTab('blob:made-1', 'a.png', { dedupeKey: 'file-f1' })
    dock.activate('other')
    openImageTab('blob:made-2', 'a.png', { dedupeKey: 'file-f1' })

    expect(dock.tabs).toHaveLength(1)
    expect(dock.tabs[0]!.id).toBe(id)
    expect(dock.activeTabId).toBe(id)
    expect(dock.tabs[0]!.data.url).toBe('blob:made-2')
  })

  it('不同 dedupeKey：各开一个 tab', () => {
    const dock = useRightDockStore()
    openImageTab('blob:made-1', 'a.png', { dedupeKey: 'file-f1' })
    openImageTab('blob:made-2', 'b.png', { dedupeKey: 'file-f2' })
    expect(dock.tabs).toHaveLength(2)
  })

  it('不传 dedupeKey 保持按 url 去重（内联图服务端 URL 稳定键）', () => {
    const dock = useRightDockStore()
    openImageTab('https://srv.example/x.png', 'x')
    openImageTab('https://srv.example/x.png', 'x')
    expect(dock.tabs).toHaveLength(1)
  })

  it('不传 createdBy：data 无归属标记（#12 内联图外来 URL 锁存）', () => {
    const dock = useRightDockStore()
    openImageTab('https://srv.example/x.png', 'x')
    expect(dock.tabs[0]!.data.createdBy).toBeUndefined()
  })

  it("createdBy:'panel' 透传到 tab.data（#11 所有权转移契约）", () => {
    const dock = useRightDockStore()
    openImageTab('blob:made-1', 'a.png', { dedupeKey: 'file-f1', createdBy: 'panel' })
    expect(dock.tabs[0]!.data.createdBy).toBe('panel')
  })
})
