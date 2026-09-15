/**
 * LoginPage 背景层契约测试
 *
 * 背景：登录页背景从 StarBackground（2D canvas 星空）替换为 Galaxy
 * （ogl WebGL 银河星流）。保留原门控契约：仅深色主题（appStore.isDark）
 * 渲染背景层，浅色主题不渲染。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/api/auth', () => ({
  authAPI: {
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
    refreshToken: vi.fn(),
    sendCode: vi.fn(),
    verifyCode: vi.fn(),
    setupStatus: vi.fn(() => Promise.resolve({ data: { needs_setup: false } })),
    setupRegister: vi.fn(),
  },
}))

import LoginPage from '@/pages/LoginPage.vue'
import { useAppStore } from '@/stores/app'

const stubs = {
  Galaxy: { name: 'Galaxy', template: '<div class="galaxy-stub" />' },
  GlassSurface: { name: 'GlassSurface', template: '<div class="glass-surface-stub"><slot /></div>' },
  GlassPanel: { template: '<div><slot/></div>' },
  GlassButton: { template: '<button><slot/></button>' },
  GlassInput: { template: '<input />' },
  'router-link': { template: '<a><slot/></a>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { template: '<div><slot/></div>' },
  'a-checkbox': { template: '<input type="checkbox"/>' },
  'a-alert': { template: '<div/>' },
}

const mountLogin = () => {
  const i18n = createI18n({
    legacy: false,
    locale: 'zh-CN',
    missingWarn: false,
    fallbackWarn: false,
    messages: { zh: {} },
  })
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(LoginPage, { global: { plugins: [i18n, pinia], stubs } })
}

describe('LoginPage 背景层', () => {
  it('深色主题渲染 Galaxy 银河背景', async () => {
    const wrapper = mountLogin()
    useAppStore().theme = 'dark'
    await flushPromises()
    expect(wrapper.find('.galaxy-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('浅色主题不渲染 Galaxy 背景', async () => {
    const wrapper = mountLogin()
    useAppStore().theme = 'light'
    await flushPromises()
    expect(wrapper.find('.galaxy-stub').exists()).toBe(false)
    wrapper.unmount()
  })

  it('登录卡片以 GlassSurface 呈现（取代 GlassPanel）', async () => {
    const wrapper = mountLogin()
    await flushPromises()
    expect(wrapper.find('.glass-surface-stub').exists()).toBe(true)
    wrapper.unmount()
  })
})
