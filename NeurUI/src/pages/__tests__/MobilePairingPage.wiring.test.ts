import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

/**
 * 移动配对整页接线判据（2026-11-16 从 Agent 渠道页迁入 /tools/mobile-pairing）。
 *
 * 面板自身语义在 `components/__tests__/MobilePairingPanel.test.ts`，这一格只钉
 * "组件做对了但没接上"才会暴露的形态：新入口整页装配后，面板在页上、且首屏
 * 真的向服务端取设备列表（屏幕状态来自唯一事实源）。
 */

const getPairedDevices = vi.fn().mockResolvedValue({ devices: [], total: 0 })
const getTunnelStatus = vi.fn()
const generatePairing = vi.fn()
const getPairingStatus = vi.fn()
const revokePairing = vi.fn()
const getPairingQrcodeBlob = vi.fn()
const cancelPairing = vi.fn()

vi.mock('@/api/modules/mobile', () => ({
  generatePairing: (...a: unknown[]) => generatePairing(...a),
  getPairingStatus: (...a: unknown[]) => getPairingStatus(...a),
  getPairedDevices: (...a: unknown[]) => getPairedDevices(...a),
  revokePairing: (...a: unknown[]) => revokePairing(...a),
  getPairingQrcodeBlob: (...a: unknown[]) => getPairingQrcodeBlob(...a),
  getTunnelStatus: (...a: unknown[]) => getTunnelStatus(...a),
  cancelPairing: (...a: unknown[]) => cancelPairing(...a),
}))

import MobilePairingPage from '../MobilePairingPage.vue'
// 用真语言包：页面标题与面板文案都吃 nav.* / channel.* 真键
import zhCN from '@/i18n/locales/zh-CN'

const DEVICE = { pairing_id: 'pair-9', device_name: 'Pixel 8', device_type: 'mobile',
  paired_at: 1, is_online: true }

function mountPage() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(MobilePairingPage, { global: { plugins: [i18n], stubs: {
    'a-tag': { template: '<span class="tag"><slot/></span>' },
    GlassButton: {
      props: ['disabled'], emits: ['click'],
      template: '<button class="gb" :disabled="disabled" @click="$emit(\'click\')"><slot/></button>',
    },
  } } })
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(URL as unknown as Record<string, unknown>).createObjectURL = vi.fn(() => 'blob:pairing-qr')
  ;(URL as unknown as Record<string, unknown>).revokeObjectURL = vi.fn()
  getPairedDevices.mockResolvedValue({ devices: [DEVICE], total: 1 })
  getTunnelStatus.mockResolvedValue({ data: {
    state: 'via_relay', configured: true, route_id: 'abc', instance_id: 'nv',
    last_heartbeat_at: 1, last_rtt_ms: 10, active_streams: 0, address_source: 'via_relay',
    last_error: '',
  } })
})

afterEach(() => { document.body.innerHTML = '' })

describe('MobilePairingPage — 新入口整页接线', () => {
  it('面板在页上，且首屏向服务端取设备列表（组件对≠接上）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('[data-testid="mobile-pairing-panel"]').exists(),
      '配对面板没接进新入口整页——后端再对，用户也还是没有入口').toBe(true)
    expect(getPairedDevices, '面板首屏就该向服务端取设备列表（屏幕状态来自唯一事实源）')
      .toHaveBeenCalled()
    expect(wrapper.find('[data-testid="pairing-device-last"]').exists(),
      '已配对设备应在首屏列出').toBe(true)
  })

  it('页面标题来自真语言包 nav.mobilePairing（手写桩补了键、真包漏了照样白屏）', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('h2').text()).toBe('移动端配对')
  })
})
