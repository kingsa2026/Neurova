/**
 * 忘记密码页 / 法务页与登录页对齐契约测试（2026-09-16 用户拍板"一并对齐"）。
 *
 * 同 RegisterPage.background.test.ts 契约：
 * 1. 深色主题渲染 Galaxy 银河背景（替换旧 StarBackground）；
 * 2. 卡片用 GlassSurface（真 backdrop 折射，替换 GlassPanel）；
 * 3. 页面底色 #090020 深空蓝；
 * 4. 入场动画 fill 禁用 forwards/both（残留 transform 破坏 backdrop 采样）。
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
    recoverPassword: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}))

import ForgotPasswordPage from '@/pages/ForgotPasswordPage.vue'
import LegalDocPage from '@/pages/LegalDocPage.vue'
import forgotSrc from '@/pages/ForgotPasswordPage.vue?raw'
import legalSrc from '@/pages/LegalDocPage.vue?raw'
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

const mountPage = (comp: any, props?: Record<string, unknown>) => {
  const i18n = createI18n({
    legacy: false,
    locale: 'zh-CN',
    missingWarn: false,
    fallbackWarn: false,
    messages: { zh: {} },
  })
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(comp, { props, global: { plugins: [i18n, pinia], stubs } })
}

const cases = [
  { name: 'ForgotPasswordPage', comp: ForgotPasswordPage, src: forgotSrc, container: '.nr-auth-container' },
  { name: 'LegalDocPage', comp: LegalDocPage, src: legalSrc, container: '.nr-legal-container' },
] as const

describe.each(cases)('$name 与登录页对齐', ({ comp, src, container }) => {
  it('深色主题渲染 Galaxy 银河背景', async () => {
    const wrapper = mountPage(comp, comp === LegalDocPage ? { type: 'terms' } : undefined)
    useAppStore().theme = 'dark'
    await flushPromises()
    expect(wrapper.find('.galaxy-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('卡片以 GlassSurface 呈现（取代 GlassPanel）', async () => {
    const wrapper = mountPage(comp, comp === LegalDocPage ? { type: 'terms' } : undefined)
    await flushPromises()
    expect(wrapper.find('.glass-surface-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('页面底色为深空蓝 #090020（与登录页一致）', () => {
    const rule = /\.nr-auth-page\s*\{[^}]*\}/.exec(src)?.[0] ?? ''
    expect(rule).toMatch(/background:\s*#090020/)
  })

  it('入场动画不得使用 forwards/both 填充（残留 transform 破坏 backdrop 采样）', () => {
    const rule = new RegExp(`${container.replace(/[.\\]/g, '\\$&')}\\s*\\{[^}]*\\}`).exec(src)?.[0] ?? ''
    const animation = /animation:\s*([^;]+);/.exec(rule)?.[1] ?? ''
    expect(animation).toBeTruthy()
    expect(animation).not.toMatch(/\bboth\b/)
    expect(animation).not.toMatch(/\bforwards\b/)
  })
})
