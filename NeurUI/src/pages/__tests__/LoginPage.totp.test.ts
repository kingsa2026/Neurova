/**
 * LoginPage TOTP 两步验证二步态（S8）TDD 测试
 *
 * 契约:
 *   - 登录响应含 two_factor_required → 不跳转，切换到 6 位码输入态
 *   - 提交验证码 → authAPI.verify2fa({challenge_token, code}) → 成功后持久化
 *     token 并跳转 dashboard
 *   - 验证码错误（401）→ 显示后端错误、停留验证态
 *   - 未启用 2FA 的用户（响应直接含 access_token）→ 登录链路零影响
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
    verify2fa: vi.fn(),
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
    loginTitle: '欢迎回来',
    verifyCode: '验证码',
    recoverBackLogin: '返回登录',
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
const challengeResponse = {
  code: 0,
  message: 'ok',
  data: { two_factor_required: true, challenge_token: 'ct-1' },
}
const meResponse = {
  code: 0,
  message: 'ok',
  data: { user_id: '1', username: 'twoFaUser', role: 'user' },
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  pushMock.mockClear()
  vi.mocked(authAPI.setupStatus).mockResolvedValue(setupFalse as any)
  vi.mocked(authAPI.oidcStatus).mockRejectedValue(new Error('not configured'))
  vi.mocked(authAPI.getCurrentUser).mockResolvedValue(meResponse as any)
})

async function submitCredentials(wrapper: any) {
  const inputs = wrapper.findAll('input')
  await inputs[0].setValue('twoFaUser')
  await inputs[1].setValue('Two-Fa-Pw-0001')
  await wrapper.findAll('.glass-btn')[0].trigger('click')
  await flushPromises()
}

describe('LoginPage TOTP 两步验证', () => {
  it('响应含 two_factor_required → 切换到验证码输入态且不跳转', async () => {
    vi.mocked(authAPI.login).mockResolvedValue(challengeResponse as any)

    const wrapper = mountPage()
    await flushPromises()
    await submitCredentials(wrapper)

    expect(wrapper.text()).to.include('验证码')
    expect(pushMock).not.toHaveBeenCalled()
    expect(authAPI.verify2fa).not.toHaveBeenCalled()
  })

  it('验证码正确 → verify2fa 换取 token 并跳转 dashboard', async () => {
    vi.mocked(authAPI.login).mockResolvedValue(challengeResponse as any)
    vi.mocked(authAPI.verify2fa).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { access_token: 'at-1', refresh_token: 'rt-1', token_type: 'bearer', expires_in: 3600 },
    } as any)

    const wrapper = mountPage()
    await flushPromises()
    await submitCredentials(wrapper)

    const codeInput = wrapper.findAll('input')[0]
    await codeInput.setValue('123456')
    await wrapper.findAll('.glass-btn')[0].trigger('click')
    await flushPromises()

    expect(authAPI.verify2fa).toHaveBeenCalledTimes(1)
    expect(authAPI.verify2fa).toHaveBeenCalledWith({ challenge_token: 'ct-1', code: '123456' })
    expect(pushMock).toHaveBeenCalledWith('/dashboard')
  })

  it('验证码错误 → 显示后端错误、停留验证态', async () => {
    vi.mocked(authAPI.login).mockResolvedValue(challengeResponse as any)
    vi.mocked(authAPI.verify2fa).mockRejectedValue({
      response: { data: { detail: '验证码不正确' } },
    })

    const wrapper = mountPage()
    await flushPromises()
    await submitCredentials(wrapper)

    await wrapper.findAll('input')[0].setValue('000000')
    await wrapper.findAll('.glass-btn')[0].trigger('click')
    await flushPromises()

    expect(wrapper.find('.ant-alert').text()).to.include('验证码不正确')
    expect(pushMock).not.toHaveBeenCalled()
    // 仍停留在验证态（挑战未通过不得进入主界面）
    expect(wrapper.text()).to.include('验证码')
  })

  it('未启用 2FA 的用户 → 登录直发 token，链路零影响', async () => {
    vi.mocked(authAPI.login).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { access_token: 'at-plain', refresh_token: 'rt-plain', token_type: 'bearer', expires_in: 3600 },
    } as any)

    const wrapper = mountPage()
    await flushPromises()
    await submitCredentials(wrapper)

    expect(authAPI.verify2fa).not.toHaveBeenCalled()
    expect(wrapper.text()).not.to.include('初始化管理员账号')
    expect(pushMock).toHaveBeenCalledWith('/dashboard')
  })
})
