/**
 * ThemeToggle 主题切换按钮（右上角入口）
 *
 * 行为契约:
 *  - 渲染为可点击按钮
 *  - 点击后切换 app store 的主题（dark ↔ light）
 *  - 主题切换后 document root 的 data-theme 属性同步更新
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import ThemeToggle from '../ThemeToggle.vue'
import { useAppStore } from '@/stores/app'

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh-CN',
    messages: {
      'zh-CN': { theme: { dark: '深色模式', light: '浅色模式' } },
    },
  })
}

function mountToggle() {
  return mount(ThemeToggle, {
    global: {
      plugins: [createPinia(), makeI18n()],
    },
  })
}

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.classList.remove('dark', 'light')
  })

  it('渲染为按钮', () => {
    const wrapper = mountToggle()
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('点击在 dark / light 之间切换主题', async () => {
    const wrapper = mountToggle()
    const store = useAppStore()
    expect(store.theme).toBe('dark')

    await wrapper.find('button').trigger('click')
    expect(store.theme).toBe('light')

    await wrapper.find('button').trigger('click')
    expect(store.theme).toBe('dark')
  })

  it('切换后同步 document root 的 data-theme 属性', async () => {
    const wrapper = mountToggle()
    await wrapper.find('button').trigger('click')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(document.documentElement.classList.contains('light')).toBe(true)
  })
})

describe('useAppStore 主题应用到 DOM', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.classList.remove('dark', 'light')
  })

  it('setTheme 将 data-theme 与主题 class 应用到 documentElement', () => {
    const store = useAppStore()
    store.setTheme('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(document.documentElement.classList.contains('light')).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(false)

    store.setTheme('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('init 应用持久化的主题', () => {
    localStorage.setItem('app_theme', 'light')
    const store = useAppStore()
    store.init()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
