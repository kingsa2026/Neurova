/**
 * rightDock store 契约测试（对话页右侧多标签 dock，2026-09-08）。
 *
 * 锁定：
 * - openTab 幂等去重（同 id 聚焦并合并 data，不新增）；
 * - singleton kind（history/archive/computer）以 kind 为 id；
 * - closeTab 关激活 tab 时右邻优先补位；关光 tab dock 收起；
 * - width clamp + localStorage 持久化 + resetWidth。
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useRightDockStore } from '../rightDock'

describe('rightDock store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('openTab 追加并激活，isOpen 为 true', () => {
    const dock = useRightDockStore()
    const id = dock.openTab({ kind: 'markdown', title: 'A', data: { content: '# a' } })
    expect(dock.tabs).toHaveLength(1)
    expect(dock.activeTabId).toBe(id)
    expect(dock.isOpen).toBe(true)
  })

  it('openTab 同 id 幂等：聚焦并合并 data，不新增', () => {
    const dock = useRightDockStore()
    const id = dock.openTab({ id: 'doc:x', kind: 'markdown', title: 'A', data: { content: 'v1' } })
    dock.openTab({ id: 'doc:y', kind: 'text', title: 'B' })
    dock.openTab({ id: 'doc:x', kind: 'markdown', title: 'A2', data: { content: 'v2' } })
    expect(dock.tabs).toHaveLength(2)
    expect(dock.activeTabId).toBe('doc:x')
    const tab = dock.tabs.find((t) => t.id === id)!
    expect(tab.title).toBe('A2')
    expect(tab.data.content).toBe('v2')
  })

  it('singleton kind 以 kind 为 id', () => {
    const dock = useRightDockStore()
    dock.openTab({ kind: 'history', title: 'H' })
    dock.openTab({ kind: 'history', title: 'H' })
    expect(dock.tabs).toHaveLength(1)
    expect(dock.tabs[0].id).toBe('history')
  })

  it('closeTab 关激活 tab 时右邻优先补位', () => {
    const dock = useRightDockStore()
    dock.openTab({ id: 'a', kind: 'text', title: 'A' })
    dock.openTab({ id: 'b', kind: 'text', title: 'B' })
    dock.openTab({ id: 'c', kind: 'text', title: 'C' })
    dock.activate('b')
    dock.closeTab('b')
    expect(dock.tabs.map((t) => t.id)).toEqual(['a', 'c'])
    expect(dock.activeTabId).toBe('c')
  })

  it('closeTab 关非激活 tab 不改变激活态', () => {
    const dock = useRightDockStore()
    dock.openTab({ id: 'a', kind: 'text', title: 'A' })
    dock.openTab({ id: 'b', kind: 'text', title: 'B' })
    dock.activate('b')
    dock.closeTab('a')
    expect(dock.activeTabId).toBe('b')
  })

  it('关光 tab 后 activeTabId 清空、isOpen false', () => {
    const dock = useRightDockStore()
    dock.openTab({ id: 'a', kind: 'text', title: 'A' })
    dock.closeTab('a')
    expect(dock.tabs).toHaveLength(0)
    expect(dock.activeTabId).toBe('')
    expect(dock.isOpen).toBe(false)
    expect(dock.activeTab).toBeNull()
  })

  it('closeAll 清空', () => {
    const dock = useRightDockStore()
    dock.openTab({ id: 'a', kind: 'text', title: 'A' })
    dock.openTab({ kind: 'history', title: 'H' })
    dock.closeAll()
    expect(dock.tabs).toHaveLength(0)
  })

  it('width clamp：低于下限取下限，高于上限取上限', () => {
    const dock = useRightDockStore()
    dock.setWidth(100)
    expect(dock.width).toBe(320)
    dock.setWidth(99999)
    expect(dock.width).toBeLessThanOrEqual(Math.round(window.innerWidth * 0.6))
    dock.setWidth(500)
    expect(dock.width).toBe(500)
  })

  it('width 持久化 localStorage，resetWidth 恢复默认', () => {
    const dock = useRightDockStore()
    dock.setWidth(560)
    expect(localStorage.getItem('neurova_dock_width')).toBe('560')
    // 新 store 实例（模拟重载）读到持久值
    setActivePinia(createPinia())
    const dock2 = useRightDockStore()
    expect(dock2.width).toBe(560)
    dock2.resetWidth()
    expect(dock2.width).toBe(420)
  })

  it('openHistory 一次性打开并聚焦历史 tab', () => {
    const dock = useRightDockStore()
    dock.openHistory()
    expect(dock.activeTab?.kind).toBe('history')
    // 已有 image tab 时聚焦历史而保留它
    dock.openTab({ id: 'img:1', kind: 'image', title: 'p' })
    dock.openHistory()
    expect(dock.tabs).toHaveLength(2)
    expect(dock.activeTabId).toBe('history')
  })

  it('openArchive 同理', () => {
    const dock = useRightDockStore()
    dock.openArchive()
    expect(dock.activeTab?.kind).toBe('archive')
  })

  it('openComputer 一次性打开并聚焦电脑 tab', () => {
    const dock = useRightDockStore()
    dock.openComputer()
    dock.openComputer()
    expect(dock.tabs).toHaveLength(1)
    expect(dock.activeTab?.kind).toBe('computer')
  })
})
