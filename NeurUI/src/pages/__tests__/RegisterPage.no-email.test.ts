/**
 * RegisterPage 无邮箱/验证码 TDD 测试
 *
 * 契约（2026-09-02 桌面版反馈：注册页直接砍掉邮箱和验证码）:
 *   - 注册表单只保留 用户名 + 密码 + 确认密码（+ 条款勾选）
 *   - 不渲染邮箱输入、验证码输入、发送验证码按钮
 *   - 提交载荷不含 email / code 字段（后端 RegisterRequest 的 email 本就可选）
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

import RegisterPage from '@/pages/RegisterPage.vue'
import { authAPI } from '@/api/auth'

const messages = {
  auth: {
    username: '用户名',
    email: '邮箱',
    verifyCode: '验证码',
    sendCode: '发送验证码',
    password: '密码',
    confirmPassword: '确认密码',
    agreeTo: '我同意',
    termsOfService: '服务条款',
    and: '和',
    privacyPolicy: '隐私政策',
    hasAccount: '已有账号',
    login: '登录',
    register: '注册',
    loginFailed: '登录失败',
    registerFailed: '注册失败',
  },
  validation: {
    required: '必填项',
    username: '用户名格式不正确',
    minLength: '长度不足',
    email: '邮箱格式不正确',
    passwordMismatch: '两次输入的密码不一致',
  },
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
    props: ['modelValue', 'type', 'placeholder'],
    emits: ['update:modelValue'],
    template:
      '<input :type="type || \'text\'" :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'router-link': { template: '<a><slot/></a>' },
  'a-form': {
    template: '<form><slot/></form>',
    methods: { validate: () => Promise.resolve(true) },
  },
  'a-form-item': {
    props: ['label'],
    template: '<div class="ant-form-item"><label class="ant-form-item-label">{{ label }}</label><slot/></div>',
  },
  'a-checkbox': {
    props: ['checked'],
    template: '<input type="checkbox" :checked="checked" @change="$emit(\'update:checked\', $event.target.checked)" />',
  },
  'a-alert': { props: ['message'], template: '<div class="ant-alert">{{ message }}</div>' },
}

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
  return mount(RegisterPage, {
    global: { plugins: [i18n, createPinia()], stubs },
  })
}

const registerSuccess = {
  code: 0,
  data: {
    tokens: { access_token: 'a', refresh_token: 'b', token_type: 'bearer', expires_in: 3600 },
    user: { id: 'u1', username: 'tester01' },
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  pushMock.mockClear()
})

describe('RegisterPage 无邮箱/验证码', () => {
  it('只渲染 用户名/密码/确认密码，无邮箱与验证码元素', () => {
    const wrapper = mountPage()

    const labels = wrapper.findAll('.ant-form-item-label').map((el: any) => el.text())
    expect(labels).to.include('用户名')
    expect(labels).to.include('密码')
    expect(labels).to.include('确认密码')
    expect(labels).not.to.include('邮箱')
    expect(labels).not.to.include('验证码')
    expect(wrapper.text()).not.to.include('发送验证码')

    // 3 个文本输入 + 1 个条款勾选框
    const inputs = wrapper.findAll('input')
    expect(inputs.length).toBe(4)
  })

  it('提交 → register 载荷不含 email / code，成功后跳转 dashboard', async () => {
    vi.mocked(authAPI.register).mockResolvedValue(registerSuccess as any)

    const wrapper = mountPage()
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('tester01')
    await inputs[1].setValue('Str0ng!Pass')
    await inputs[2].setValue('Str0ng!Pass')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('.glass-btn').trigger('click')
    await flushPromises()

    expect(authAPI.register).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(authAPI.register).mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.username).toBe('tester01')
    expect(payload.email).toBeUndefined()
    expect(payload.code).toBeUndefined()
    expect(pushMock).toHaveBeenCalledWith('/dashboard')
  })
})
