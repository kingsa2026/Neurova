/**
 * RegisterPage 背景与玻璃卡契约测试（2026-09-16 与登录页对齐）。
 *
 * 需求：注册页与登录页保持一致的背景和液态玻璃效果——
 * 1. 深色主题渲染 Galaxy 银河背景（替换旧 StarBackground 2D 星空）；
 * 2. 登录卡片用 GlassSurface（真 backdrop 折射，替换 GlassPanel）；
 * 3. 页面底色 #090020 深空蓝（Galaxy 透明画布叠于其上）；
 * 4. 入场动画 fill 禁用 forwards/both（残留 transform 破坏 backdrop 采样，
 *    同 LoginPage.glassAncestor 契约）。
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

import RegisterPage from '@/pages/RegisterPage.vue'
import src from '@/pages/RegisterPage.vue?raw'
import { useAppStore } from '@/stores/app'

const stubs = {
  Galaxy: { name: 'Galaxy', template: '<div class="galaxy-stub" />' },
  GlassSurface: { name: 'GlassSurface', template: '<div class="glass-surface-stub"><slot /></div>' },
  StarBackground: { template: '<div/>' },
  GlassPanel: { template: '<div><slot/></div>' },
  GlassButton: { template: '<button><slot/></button>' },
  GlassInput: { template: '<input />' },
  'router-link': { template: '<a><slot/></a>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': { template: '<div><slot/></div>' },
  'a-checkbox': { template: '<input type="checkbox"/>' },
  'a-alert': { template: '<div/>' },
}

const mountRegister = () => {
  const i18n = createI18n({
    legacy: false,
    locale: 'zh-CN',
    missingWarn: false,
    fallbackWarn: false,
    messages: { zh: {} },
  })
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(RegisterPage, { global: { plugins: [i18n, pinia], stubs } })
}

describe('RegisterPage 背景与玻璃卡（与登录页一致）', () => {
  it('深色主题渲染 Galaxy 银河背景', async () => {
    const wrapper = mountRegister()
    useAppStore().theme = 'dark'
    await flushPromises()
    expect(wrapper.find('.galaxy-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('浅色主题不渲染 Galaxy 背景', async () => {
    const wrapper = mountRegister()
    useAppStore().theme = 'light'
    await flushPromises()
    expect(wrapper.find('.galaxy-stub').exists()).toBe(false)
    wrapper.unmount()
  })

  it('注册卡片以 GlassSurface 呈现（取代 GlassPanel）', async () => {
    const wrapper = mountRegister()
    await flushPromises()
    expect(wrapper.find('.glass-surface-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('页面底色为深空蓝 #090020（与登录页一致）', () => {
    const rule = /\.nr-auth-page\s*\{[^}]*\}/.exec(src)?.[0] ?? ''
    expect(rule).toMatch(/background:\s*#090020/)
  })

  it('入场动画不得使用 forwards/both 填充（残留 transform 破坏 backdrop 采样）', () => {
    const rule = /\.nr-auth-container\s*\{[^}]*\}/.exec(src)?.[0] ?? ''
    const animation = /animation:\s*([^;]+);/.exec(rule)?.[1] ?? ''
    expect(animation).toBeTruthy()
    expect(animation).not.toMatch(/\bboth\b/)
    expect(animation).not.toMatch(/\bforwards\b/)
  })
})
