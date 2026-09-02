/**
 * LoginPage 首启向导（桌面壳初始化）TDD 测试
 *
 * 契约:
 *   - 挂载时查询 GET /auth/setup-status；needs_setup=true（系统中无任何用户）时
 *     登录页切换为首启向导：用户名 + 密码 + 确认密码（无邮箱、无验证码）
 *   - 两次密码不一致 → 提示且不发起注册
 *   - 校验通过 → POST /auth/register（setupRegister）→ 后端首用户即管理员
 *     → 持久化 token（store）→ 跳转 dashboard
 *   - needs_setup=false（已有用户）→ 保持普通登录表单
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
  },
}))

import LoginPage from '@/pages/LoginPage.vue'
import { authAPI } from '@/api/auth'

const messages = {
  auth: {
    username: '用户名',
    password: '密码',
    confirmPassword: '确认密码',
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
  StarBackground: true,
  GlassPanel: { template: '<div><slot/></div>' },
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

const needsSetupTrue = { code: 0, message: 'ok', data: { needs_setup: true } }
const needsSetupFalse = { code: 0, message: 'ok', data: { needs_setup: false } }

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  pushMock.mockClear()
})

async function fillWizard(wrapper: any, username: string, pw: string, confirm: string) {
  const inputs = wrapper.findAll('input')
  await inputs[0].setValue(username)
  await inputs[1].setValue(pw)
  await inputs[2].setValue(confirm)
}

describe('LoginPage 首启向导', () => {
  it('needs_setup=true → 显示向导（含确认密码字段，不显示登录按钮）', async () => {
    vi.mocked(authAPI.setupStatus).mockResolvedValue(needsSetupTrue as any)

    const wrapper = mountPage()
    await flushPromises()

    const labels = wrapper.findAll('.ant-form-item-label').map((el: any) => el.text())
    expect(labels).to.include('确认密码')
    expect(wrapper.text()).to.include('初始化管理员账号')
    expect(wrapper.text()).to.include('创建管理员账号')
    // 登录表单隐藏
    expect(wrapper.text()).not.to.include('登录失败')
    const btnTexts = wrapper.findAll('.glass-btn').map((el: any) => el.text())
    expect(btnTexts).not.to.include('登录')
  })

  it('needs_setup=false → 保持普通登录表单（无确认密码字段）', async () => {
    vi.mocked(authAPI.setupStatus).mockResolvedValue(needsSetupFalse as any)

    const wrapper = mountPage()
    await flushPromises()

    const labels = wrapper.findAll('.ant-form-item-label').map((el: any) => el.text())
    expect(labels).to.include('密码')
    expect(labels).not.to.include('确认密码')
    const btnTexts = wrapper.findAll('.glass-btn').map((el: any) => el.text())
    expect(btnTexts).to.include('登录')
  })

  it('两次密码不一致 → 提示且不发起注册', async () => {
    vi.mocked(authAPI.setupStatus).mockResolvedValue(needsSetupTrue as any)

    const wrapper = mountPage()
    await flushPromises()
    await fillWizard(wrapper, 'founder', 'Str0ng!Pass', 'Str0ng!Different')
    await wrapper.findAll('.glass-btn')[0].trigger('click')
    await flushPromises()

    expect(authAPI.setupRegister).not.toHaveBeenCalled()
    expect(wrapper.find('.ant-alert').text()).to.include('两次输入的密码不一致')
  })

  it('校验通过 → 注册持久化 token 并跳转 dashboard', async () => {
    vi.mocked(authAPI.setupStatus).mockResolvedValue(needsSetupTrue as any)
    vi.mocked(authAPI.setupRegister).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { user_id: '1', username: 'founder', access_token: 'tok', refresh_token: 'ref' },
    } as any)
    vi.mocked(authAPI.getCurrentUser).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { user_id: '1', username: 'founder', role: 'admin' },
    } as any)

    const wrapper = mountPage()
    await flushPromises()
    await fillWizard(wrapper, 'founder', 'Str0ng!Pass', 'Str0ng!Pass')
    await wrapper.findAll('.glass-btn')[0].trigger('click')
    await flushPromises()

    expect(authAPI.setupRegister).toHaveBeenCalledTimes(1)
    expect(authAPI.setupRegister).toHaveBeenCalledWith({ username: 'founder', password: 'Str0ng!Pass' })
    // token 落地 + 用户资料拉取 + 跳转
    expect(pushMock).toHaveBeenCalledWith('/dashboard')
  })

  it('注册失败 → 显示后端错误且不跳转', async () => {
    vi.mocked(authAPI.setupStatus).mockResolvedValue(needsSetupTrue as any)
    vi.mocked(authAPI.setupRegister).mockRejectedValue({
      response: { data: { message: '用户名已存在' } },
    })

    const wrapper = mountPage()
    await flushPromises()
    await fillWizard(wrapper, 'founder', 'Str0ng!Pass', 'Str0ng!Pass')
    await wrapper.findAll('.glass-btn')[0].trigger('click')
    await flushPromises()

    expect(wrapper.find('.ant-alert').text()).to.include('用户名已存在')
    expect(pushMock).not.toHaveBeenCalled()
  })
})
