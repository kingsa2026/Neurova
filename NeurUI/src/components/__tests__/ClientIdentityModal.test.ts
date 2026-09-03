/**
 * ClientIdentityModal（设备标识弹窗）TDD 测试（2026-09-03）
 *
 * 用户契约：
 * 1. 展示客户端唯一标识（client_id UUID 等宽字体）、设备平台、上报状态；
 * 2. 复制按钮：调用 clipboard 写 client_id，成功后文案变「已复制」；
 * 3. 提示文案说明标识匿名性（不含用户名/邮箱）与用途（仅错误诊断）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      identity: {
        title: '设备标识',
        clientId: '客户端唯一标识',
        platform: '设备平台',
        reportStatus: '错误日志自动上报',
        reportOn: '已启用',
        reportOff: '未启用',
        copy: '复制',
        copied: '已复制',
        close: '关闭',
        hint: '此标识由您的客户端本地随机生成并永久保存，不包含用户名/邮箱等个人信息。',
        manualReport: '手动上报',
        manualCancel: '取消',
        manualSubmit: '提交',
        manualPlaceholder: '描述遇到的问题',
        manualSent: '反馈已提交',
        platformWeb: 'Web 浏览器',
        platformDesktopWindows: '桌面端 (Windows)',
        platformDesktopLinux: '桌面端 (Linux)',
        platformLinux: 'Linux 系统',
        platformMac: 'macOS',
        platformUnknown: '未知',
      },
    },
  },
})

import ClientIdentityModal from '@/components/ClientIdentityModal.vue'

const mountModal = (props: Record<string, unknown> = {}) =>
  mount(ClientIdentityModal, {
    props: {
      open: true,
      clientId: '1f113dc7-8389-4e04-98a2-a93bf730ee1b',
      platform: 'web',
      reportEnabled: true,
      ...props,
    },
    global: {
      plugins: [i18n],
      stubs: { teleport: true },
    },
  })

describe('ClientIdentityModal 设备标识弹窗', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    })
  })

  it('展示 client_id / 平台 / 上报状态 / 匿名性提示', () => {
    const wrapper = mountModal()
    const text = wrapper.text()
    expect(text).toContain('1f113dc7-8389-4e04-98a2-a93bf730ee1b')
    expect(text).toContain('Web 浏览器')
    expect(text).toContain('已启用')
    expect(text).toContain('此标识由您的客户端本地随机生成')
    expect(text).not.toContain('username')
  })

  it('平台映射：desktop-linux → 桌面端 (Linux)', () => {
    const wrapper = mountModal({ platform: 'desktop-linux' })
    expect(wrapper.text()).toContain('桌面端 (Linux)')
  })

  it('复制按钮写入剪贴板并显示「已复制」', async () => {
    const wrapper = mountModal()
    const copyBtn = wrapper.findAll('button').find((b) => b.text().includes('复制'))
    await copyBtn!.trigger('click')
    await flushPromises()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('1f113dc7-8389-4e04-98a2-a93bf730ee1b')
    expect(wrapper.text()).toContain('已复制')
  })

  it('关闭按钮触发 update:open=false', async () => {
    const wrapper = mountModal()
    await wrapper.findAll('button').find((b) => b.text().includes('关闭'))!.trigger('click')
    expect(wrapper.emitted('update:open')).toBeTruthy()
    expect((wrapper.emitted('update:open') as Array<[boolean]>)[0][0]).toBe(false)
  })

  it('自动上报开关：点击拨杆触发 toggle-report', async () => {
    const wrapper = mountModal()
    const sw = wrapper.findAll('button').find((b) => b.attributes('role') === 'switch')
    expect(sw).toBeTruthy()
    await sw!.trigger('click')
    expect(wrapper.emitted('toggle-report')).toBeTruthy()
  })

  it('手动上报：展开输入区、提交携带文本', async () => {
    const wrapper = mountModal()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('手动上报'))
    await btn!.trigger('click')
    const input = wrapper.find('textarea')
    expect(input.exists()).toBe(true)
    await input.setValue('我在对话页遇到一个闪退')
    await wrapper.findAll('button').find((b) => b.text().includes('提交'))!.trigger('click')
    const emitted = wrapper.emitted('submit-manual')
    expect(emitted).toBeTruthy()
    expect((emitted as Array<[string]>)[0][0]).toBe('我在对话页遇到一个闪退')
  })
})
