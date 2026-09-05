import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAppStore } from '@/stores/app'

describe('useAppStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('defaults to dark theme', () => {
    const store = useAppStore()
    expect(store.theme).toBe('dark')
    expect(store.isDark).toBe(true)
  })

  it('defaults to cosmic skin (原版默认皮肤)', () => {
    const store = useAppStore()
    expect(store.skin).toBe('cosmic')
  })

  it('setSkin persists and applies data-skin to document root', () => {
    const store = useAppStore()
    store.setSkin('ios')
    expect(store.skin).toBe('ios')
    expect(document.documentElement.getAttribute('data-skin')).toBe('ios')
    expect(localStorage.setItem).toHaveBeenCalled()
  })

  it('init applies persisted skin', () => {
    const store = useAppStore()
    store.setSkin('ios')
    store.init()
    expect(document.documentElement.getAttribute('data-skin')).toBe('ios')
    // 持久化后新会话恢复 ios 皮肤
    store.setSkin('cosmic')
    expect(store.skin).toBe('cosmic')
  })

  it('setTheme persists and updates', () => {
    const store = useAppStore()
    store.setTheme('light')
    expect(store.theme).toBe('light')
    expect(store.isDark).toBe(false)
    expect(localStorage.setItem).toHaveBeenCalled()
  })

  it('toggleTheme switches theme', () => {
    const store = useAppStore()
    const initial = store.theme
    store.toggleTheme()
    expect(store.theme).toBe(initial === 'dark' ? 'light' : 'dark')
  })

  it('defaults to zh-CN locale', () => {
    const store = useAppStore()
    expect(store.locale).toBe('zh-CN')
  })

  it('setLocale persists and updates', () => {
    const store = useAppStore()
    store.setLocale('en-US')
    expect(store.locale).toBe('en-US')
  })

  it('detects RTL locales', () => {
    const store = useAppStore()
    store.setLocale('ar-SA')
    expect(store.isRtl).toBe(true)
    store.setLocale('zh-CN')
    expect(store.isRtl).toBe(false)
  })

  it('toggleSidebar persists', () => {
    const store = useAppStore()
    expect(store.sidebarCollapsed).toBe(false)
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(true)
    store.toggleSidebar()
    expect(store.sidebarCollapsed).toBe(false)
  })

  it('setCurrentAgentId updates state', () => {
    const store = useAppStore()
    expect(store.currentAgentId).toBe(null)
    store.setCurrentAgentId('agent-123')
    expect(store.currentAgentId).toBe('agent-123')
  })

  it('setGlobalLoading updates state', () => {
    const store = useAppStore()
    expect(store.globalLoading).toBe(false)
    store.setGlobalLoading(true, 'Loading...')
    expect(store.globalLoading).toBe(true)
    expect(store.loadingText).toBe('Loading...')
    store.setGlobalLoading(false)
    expect(store.globalLoading).toBe(false)
  })
})
