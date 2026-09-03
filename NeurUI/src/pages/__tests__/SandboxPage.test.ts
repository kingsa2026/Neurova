/**
 * SandboxPage — 信封解包防回归测试（2026-09-03）
 *
 * 实测根因：listSandboxes 返回后端点信封 {code, data:{sandboxes, total}}，
 * 页面 `sandboxes.value = res ?? []` 把信封对象当数组 v-for →
 * 渲染出 code/message/data 三张无名称幽灵卡片。
 *
 * 契约（防回归）：res.data.sandboxes 才是列表；空列表渲染「暂无数据」；
 * 有数据时卡片显示 name/id。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules', () => ({
  sandboxApi: {
    listSandboxes: vi.fn(),
    getSandbox: vi.fn(),
    createSandbox: vi.fn(),
    executeInSandbox: vi.fn(),
    commitSandbox: vi.fn(),
    deleteSandbox: vi.fn(),
  },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'u1', username: 'tester', role: 'admin' } }),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  Modal: { confirm: vi.fn() },
}))

import { sandboxApi } from '@/api/modules'
import SandboxPage from '@/pages/SandboxPage.vue'

const listMock = sandboxApi.listSandboxes as unknown as ReturnType<typeof vi.fn>

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      common: { create: '创建', open: '打开', noData: '暂无数据', error: '错误', success: '成功', name: '名称', confirm: '确认' },
      system: { sandbox: '沙箱' },
      sandbox: { created: '创建于: ', steps: '步骤数: ', commit: '提交', destroy: '销毁', image: '镜像: ' },
      tool: { execute: '执行' },
    },
  },
})

const mountPage = () =>
  mount(SandboxPage, {
    global: {
      plugins: [i18n],
      stubs: {
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-spin': { template: '<div><slot /></div>' },
        'a-form': { template: '<div><slot /></div>' },
        'a-form-item': { template: '<div><slot /></div>' },
        'a-input': { template: '<input />' },
        'a-input-number': { template: '<input />' },
        'a-select': { template: '<select><slot /></select>' },
      },
    },
  })

describe('SandboxPage 信封解包', () => {
  beforeEach(() => {
    listMock.mockReset()
  })

  it('后端信封 {code,data:{sandboxes}} 渲染出卡片名称（而非幽灵卡片）', async () => {
    listMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: { sandboxes: [{ id: 'sb1', name: '测试沙箱', status: 'running', steps_count: 3 }], total: 1 },
    })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('测试沙箱')
    expect(wrapper.text()).not.toContain('success')
  })

  it('空列表不渲染幽灵卡片，展示暂无数据', async () => {
    listMock.mockResolvedValue({ code: 0, message: 'success', data: { sandboxes: [], total: 0 } })
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无数据')
    // v-for 遍历信封对象会渲染 3 个空卡 — 防回归：卡片区域不应出现两次以上「打开」
    const openCount = wrapper.findAll('button').filter((b) => b.text().includes('打开')).length
    expect(openCount).toBe(0)
  })
})
