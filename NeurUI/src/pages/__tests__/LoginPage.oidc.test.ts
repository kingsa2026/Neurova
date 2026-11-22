/**
 * LoginPage OIDC SSO 按钮（S7）TDD 测试
 *
 * 契约:
 *   - 挂载时查询 GET /auth/oidc/status；enabled=true → 登录表单下方出现 SSO 按钮
 *   - 点击 SSO 按钮 → 调用 authAPI.oidcAuthorize()（浏览器级跳转后端 authorize）
 *   - enabled=false（后端未配置 IdP）→ 不出现 SSO 按钮
 *   - status 查询失败（网络/后端未升级）→ 按未启用处理，不影响密码登录表单
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
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
    setupStatus: vi.fn(),
    setupRegister: vi.fn(),
    oidcStatus: vi.fn(),
    oidcAuthorize: vi.fn(),
  },
}))

import LoginPage from '@/pages/LoginPage.vue'
import { authAPI } from '@/api/auth'

const messages = {
  auth: {
    username: '用户名',
    password: '密码',
    rememberMe: '记住我',
    forgotPassword: '忘记密码',
    login: '登录',
    register: '注册',
    noAccount: '还没有账号？',
    loginFailed: '登录失败',
    setupTitle: '初始化管理员账号',
    setupHint: '这是系统的第一个账号，将拥有管理员权限',
    setupSubmit: '创建管理员账号',
    registerFailed: '注册失败',
  },
  validation: { required: '必填项', passwordMismatch: '两次输入的密码不一致' },
}

const stubs = {
  Galaxy: true,
  GlassSurface: { template: '<div><slot/></div>' },
  GlassButton: {
    props: ['variant', 'size', 'loading'],
    emits: ['click'],
    template: '<button class="glass-btn" @click="$emit(\'click\')"><slot/></button>',
  },
  GlassInput: {
    props: ['modelValue', 'type', 'placeholder', 'autocomplete'],
    emits: ['update:modelValue'],
    template:
      '<input :type="type || \'text\'" :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'router-link': { template: '<a><slot/></a>' },
  'a-form': { template: '<form><slot/></form>' },
  'a-form-item': {
    props: ['label'],
    template: '<div class="ant-form-item"><label class="ant-form-item-label">{{ label }}</label><slot/></div>',
  },
  'a-checkbox': { props: ['checked'], template: '<input type="checkbox"/>' },
  'a-alert': { props: ['message'], template: '<div class="ant-alert">{{ message }}</div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(LoginPage, {
    global: { plugins: [i18n, createPinia()], stubs },
  })
}

const setupFalse = { code: 0, message: 'ok', data: { needs_setup: false } }

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  pushMock.mockClear()
  vi.mocked(authAPI.setupStatus).mockResolvedValue(setupFalse as any)
})

describe('LoginPage OIDC SSO 按钮', () => {
  it('oidcStatus enabled=true → 渲染 SSO 按钮，点击触发 oidcAuthorize', async () => {
    vi.mocked(authAPI.oidcStatus).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { enabled: true },
    } as any)
    vi.mocked(authAPI.oidcAuthorize).mockReturnValue('/api/v1/auth/oidc/authorize')

    const wrapper = mountPage()
    await flushPromises()

    const ssoBtn = wrapper.find('[data-testid="sso-login-button"]')
    expect(ssoBtn.exists()).toBe(true)
    expect(ssoBtn.text()).to.include('SSO')

    await ssoBtn.trigger('click')
    await flushPromises()
    expect(authAPI.oidcAuthorize).toHaveBeenCalledTimes(1)
  })

  it('oidcStatus enabled=false → 不渲染 SSO 按钮', async () => {
    vi.mocked(authAPI.oidcStatus).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { enabled: false },
    } as any)

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="sso-login-button"]').exists()).toBe(false)
    expect(wrapper.text()).not.to.include('SSO')
  })

  it('oidcStatus 查询失败 → 静默按未启用处理（fail-soft），密码登录表单仍在', async () => {
    vi.mocked(authAPI.oidcStatus).mockRejectedValue(new Error('backend not ready'))

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="sso-login-button"]').exists()).toBe(false)
    // 密码登录主链路不受影响
    const btnTexts = wrapper.findAll('.glass-btn').map((el: any) => el.text())
    expect(btnTexts).to.include('登录')
  })
})
