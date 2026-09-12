/**
 * WechatQrcodeDialog（iLink 扫码对话框）TDD 测试（F-3，2026-09-12）
 *
 * 用户契约：
 * 1. 展示二维码（qr_url）与扫码状态文案（等待扫码/已扫描/已确认/已过期）；
 * 2. 每 3s 轮询一次 status 端点；confirmed → 停止轮询并 emit('confirmed')；
 * 3. expired → 停止轮询、显示"重新生成"按钮，点击 emit('regenerate')；
 * 4. 连续 3 次查询失败 → error 态停轮询；
 * 5. 对话框关闭 / 组件卸载必须清理轮询定时器（资源纪律）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

vi.mock('@/api/modules/channel-configs', () => ({
  getWechatIlinkQrcodeStatus: vi.fn(),
}))

import { getWechatIlinkQrcodeStatus } from '@/api/modules/channel-configs'
import WechatQrcodeDialog from '@/components/WechatQrcodeDialog.vue'

const mockedPoll = vi.mocked(getWechatIlinkQrcodeStatus)

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      channel: {
        qrTitle: '微信扫码登录',
        qrHint: '请使用微信扫描二维码登录 iLink',
        qrWaiting: '等待扫码…',
        qrScanned: '已扫描，请在手机上确认',
        qrConfirmed: '登录成功',
        qrExpired: '二维码已过期',
        qrError: '查询扫码状态失败',
        qrRegenerate: '重新生成二维码',
      },
    },
  },
})

const mountDialog = (props: Record<string, unknown> = {}) =>
  mount(WechatQrcodeDialog, {
    props: {
      visible: true,
      qrUrl: 'https://qr.example/abc',
      qrId: 'qr-1',
      ...props,
    },
    global: {
      plugins: [i18n],
    },
    attachTo: document.body,
  })

beforeEach(() => {
  vi.useFakeTimers()
  mockedPoll.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

describe('WechatQrcodeDialog', () => {
  it('renders qr image and waiting status', () => {
    const wrapper = mountDialog()
    const img = wrapper.find('[data-testid="qr-image"]')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('https://qr.example/abc')
    expect(wrapper.find('[data-testid="qr-status"]').text()).toContain('等待扫码')
  })

  it('polls status endpoint every 3s while pending', async () => {
    mockedPoll.mockResolvedValue({ status: 'pending' })
    mountDialog()

    await flushPromises() // 挂载即首轮询
    expect(mockedPoll).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(3000)
    expect(mockedPoll).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(3000)
    expect(mockedPoll).toHaveBeenCalledTimes(3)
  })

  it('shows scanned status text', async () => {
    mockedPoll.mockResolvedValue({ status: 'scanned' })
    const wrapper = mountDialog()

    await flushPromises()
    expect(wrapper.find('[data-testid="qr-status"]').text()).toContain('已扫描')
    // scanned 不停止轮询
    await vi.advanceTimersByTimeAsync(3000)
    expect(mockedPoll).toHaveBeenCalledTimes(2)
  })

  it('stops polling and emits confirmed', async () => {
    mockedPoll.mockResolvedValue({ status: 'confirmed' })
    const wrapper = mountDialog()

    await flushPromises()
    expect(wrapper.emitted('confirmed')).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(9000)
    expect(mockedPoll).toHaveBeenCalledTimes(1) // 确认后停轮询
    expect(wrapper.find('[data-testid="qr-status"]').text()).toContain('登录成功')
  })

  it('stops polling on expired and offers regenerate', async () => {
    mockedPoll.mockResolvedValue({ status: 'expired' })
    const wrapper = mountDialog()

    await flushPromises()
    expect(wrapper.find('[data-testid="qr-status"]').text()).toContain('已过期')
    expect(mockedPoll).toHaveBeenCalledTimes(1)

    const btn = wrapper.find('[data-testid="qr-regenerate"]')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('regenerate')).toHaveLength(1)

    // 过期后不再自动轮询
    await vi.advanceTimersByTimeAsync(9000)
    expect(mockedPoll).toHaveBeenCalledTimes(1)
  })

  it('enters error state after 3 consecutive failures', async () => {
    mockedPoll.mockRejectedValue(new Error('network down'))
    const wrapper = mountDialog()

    await flushPromises() // 1
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises() // 2
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises() // 3
    expect(wrapper.find('[data-testid="qr-status"]').text()).toContain('失败')

    // error 态停轮询
    await vi.advanceTimersByTimeAsync(9000)
    expect(mockedPoll).toHaveBeenCalledTimes(3)
    expect(wrapper.find('[data-testid="qr-regenerate"]').exists()).toBe(true)
  })

  it('clears timer when dialog closes', async () => {
    mockedPoll.mockResolvedValue({ status: 'pending' })
    const wrapper = mountDialog()

    await flushPromises()
    await wrapper.setProps({ visible: false })
    await flushPromises()

    const callsAfterClose = mockedPoll.mock.calls.length
    await vi.advanceTimersByTimeAsync(9000)
    expect(mockedPoll.mock.calls.length).toBe(callsAfterClose)
  })

  it('clears timer on unmount', async () => {
    mockedPoll.mockResolvedValue({ status: 'pending' })
    const wrapper = mountDialog()

    await flushPromises()
    wrapper.unmount()

    const callsAfterUnmount = mockedPoll.mock.calls.length
    await vi.advanceTimersByTimeAsync(9000)
    expect(mockedPoll.mock.calls.length).toBe(callsAfterUnmount)
  })

  it('restarts polling with new qrId after regenerate', async () => {
    mockedPoll.mockResolvedValue({ status: 'pending' })
    const wrapper = mountDialog()

    await flushPromises()
    await wrapper.setProps({ qrId: 'qr-2', qrUrl: 'https://qr.example/def' })
    await flushPromises()

    expect(mockedPoll).toHaveBeenLastCalledWith('qr-2')
  })
})
