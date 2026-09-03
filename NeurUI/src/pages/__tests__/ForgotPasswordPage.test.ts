/**
 * ForgotPasswordPage（忘记密码/取回密码）TDD 测试（2026-09-03）
 *
 * 用户契约：
 * 1. 双条件缺一不可：管理员账号 + 最高权重密码都必须输入，才能进入第二步；
 * 2. 第二步设置新密码（新密码 + 确认）后提交；
 * 3. 提交载荷 username/master_password/new_password/confirm_password 走
 *    POST /auth/recover-password（服务端做真实双条件校验 + 限流）；
 * 4. 成功 → 跳转登录页并提示；失败 → 展示服务端 detail 或统一文案。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
  useRoute: () => ({ query: {} }),
}))

const recoverMock = vi.fn()

vi.mock('@/api/auth', () => ({
  authAPI: {
    recoverPassword: (...args: unknown[]) => recoverMock(...args),
  },
}))

vi.mock('@/stores/app', () => ({
  useAppStore: () => ({ isDark: false }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/components/StarBackground.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/GlassPanel.vue', () => ({ default: { template: '<div><slot /></div>' } }))
vi.mock('@/components/GlassButton.vue', () => ({
  default: {
    props: ['variant', 'size', 'loading', 'disabled'],
    template: '<button :disabled="disabled" :class="\'stub-btn\'"><slot /></button>',
  },
}))
vi.mock('@/components/GlassInput.vue', () => ({
  default: {
    props: ['modelValue', 'type', 'placeholder'],
    emits: ['update:modelValue'],
    template: "<input :placeholder=\"placeholder\" @input=\"$emit('update:modelValue', $event.target.value)\" />",
  },
}))

import ForgotPasswordPage from '@/pages/ForgotPasswordPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      auth: {
        recoverTitle: '取回密码',
        recoverSubtitle: '找回管理员密码',
        recoverStep1: '第一步 · 身份验证',
        recoverStep2: '第二步 · 设置新密码',
        recoverAdminPh: '管理员账号',
        recoverMasterPh: '最高权重密码',
        recoverMasterHint: '最高权重密码提示',
        recoverNext: '下一步',
        recoverNewPh: '新密码',
        recoverConfirmPh: '确认新密码',
        recoverSubmit: '重置密码',
        recoverSuccess: '密码已重置',
        recoverFailed: '管理员账号或最高权重密码不正确',
        recoverBothRequired: '请输入管理员账号和最高权重密码',
        recoverBackLogin: '返回登录',
      },
      validation: { required: '必填' },
    },
  },
})

const mountPage = () =>
  mount(ForgotPasswordPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-form': { template: '<form><slot /></form>' },
        'a-form-item': { template: '<div><slot /></div>' },
        'a-alert': { props: ['message'], template: '<div class="stub-alert">{{ message }}</div>' },
      },
    },
  })

const inputs = (wrapper: ReturnType<typeof mountPage>) => wrapper.findAll('input')

describe('ForgotPasswordPage 双条件取回', () => {
  beforeEach(() => {
    recoverMock.mockReset()
    pushMock.mockReset()
  })

  it('双条件缺一不可：任一为空时下一步按钮禁用', async () => {
    const wrapper = mountPage()
    const nextBtn = wrapper.findAll('button').find((b) => b.text().includes('下一步'))
    expect(nextBtn!.attributes('disabled')).toBeDefined()

    // 只填管理员账号 → 仍禁用
    const [adminInput, masterInput] = inputs(wrapper)
    await adminInput.setValue('admin1')
    expect(wrapper.findAll('button').find((b) => b.text().includes('下一步'))!.attributes('disabled')).toBeDefined()

    // 补上最高权重密码 → 可用
    await masterInput.setValue('master-secret')
    expect(wrapper.findAll('button').find((b) => b.text().includes('下一步'))!.attributes('disabled')).toBeUndefined()
  })

  it('两条件输入后进入第二步（新密码表单）', async () => {
    const wrapper = mountPage()
    const [adminInput, masterInput] = inputs(wrapper)
    await adminInput.setValue('admin1')
    await masterInput.setValue('master-secret')
    await wrapper.findAll('button').find((b) => b.text().includes('下一步'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第二步')
    expect(wrapper.text()).toContain('新密码')
  })

  it('提交载荷含 username/master_password/new_password/confirm_password', async () => {
    recoverMock.mockResolvedValue({ code: 0, data: { username: 'admin1' } })
    const wrapper = mountPage()
    const [adminInput, masterInput] = inputs(wrapper)
    await adminInput.setValue('admin1')
    await masterInput.setValue('master-secret')
    await wrapper.findAll('button').find((b) => b.text().includes('下一步'))!.trigger('click')
    await flushPromises()

    const stepInputs = inputs(wrapper)
    const [newPwd, confirmPwd] = stepInputs
    // step2 表单字段：新密码 + 确认密码
    await newPwd.setValue('Reset#2026abc')
    await confirmPwd.setValue('Reset#2026abc')
    await wrapper.findAll('button').find((b) => b.text().includes('重置密码'))!.trigger('click')
    await flushPromises()

    expect(recoverMock).toHaveBeenCalledWith({
      username: 'admin1',
      master_password: 'master-secret',
      new_password: 'Reset#2026abc',
      confirm_password: 'Reset#2026abc',
    })
    expect(pushMock).toHaveBeenCalledWith('/login')
  })

  it('服务端校验失败显示统一错误文案', async () => {
    recoverMock.mockRejectedValue({ response: { data: { detail: '管理员账号或最高权重密码不正确，请核对后重试' } } })
    const wrapper = mountPage()
    const [adminInput, masterInput] = inputs(wrapper)
    await adminInput.setValue('ghost')
    await masterInput.setValue('wrong-master')
    await wrapper.findAll('button').find((b) => b.text().includes('下一步'))!.trigger('click')
    await flushPromises()
    const [newPwd, confirmPwd] = inputs(wrapper)
    await newPwd.setValue('Reset#2026abc')
    await confirmPwd.setValue('Reset#2026abc')
    await wrapper.findAll('button').find((b) => b.text().includes('重置密码'))!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.stub-alert').text()).toContain('管理员账号或最高权重密码不正确')
    expect(pushMock).not.toHaveBeenCalled()
  })
})
