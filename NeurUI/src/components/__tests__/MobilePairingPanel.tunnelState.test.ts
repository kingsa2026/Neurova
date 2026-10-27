/**
 * 配对面板的**通道态**那一格（设计方案 §5.2／§6.1，S0.5 批）。
 *
 * 面板原先只有「等待扫码 / 已确认 / 已过期」三态，缺的正是"服务端根本不在这台手机
 * 够得着的地址上"——无固定 IP 时那是常态。用户对着永远等不到的二维码干耗满 300 秒，
 * 就是 AGENTS §2 说的"把故障渲染成进行中"。
 *
 * 判据钉四件事：
 * 1. 配了中继又没注册上 ⇒ 发码按钮 disable，且屏上**不得**出现"等待扫码"；
 * 2. 没配中继时**照常能发码**（局域网/自建反代那两条路已被批 25-29 交付，闸门不许把它们杀掉）；
 * 3. `scanned` 是新的一格（已扫未确认），不能仍显示"等待扫码"；
 * 4. `revoked` 与 `expired` 分文案——"有人解除了设备"与"码放久了"处置不同。
 * 另加通道读数取不到时的诚实形态（不许画成"直连"）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const generatePairing = vi.fn()
const getPairingStatus = vi.fn()
const getPairedDevices = vi.fn()
const revokePairing = vi.fn()
const getPairingQrcodeBlob = vi.fn()
const getTunnelStatus = vi.fn()
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

import MobilePairingPanel from '../MobilePairingPanel.vue'
import zhCN from '@/i18n/locales/zh-CN'

const CODE = {
  code: '248160',
  ref: 'aB3dE5fG7hJ9kL1mN2pQ4rS',
  qr_code_url: 'http://x/api/v1/mobile/pairing/qrcode/248160',
  expires_in: 300,
  pairing_id: 'pair-1',
}

function tunnel(over: Record<string, unknown> = {}) {
  return {
    data: {
      state: 'via_relay', configured: true, route_id: 'abc123def456', instance_id: 'nv-1',
      last_heartbeat_at: 1, last_rtt_ms: 42, active_streams: 0, address_source: 'via_relay',
      last_error: '', ...over,
    },
  }
}

function mountPanel() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(MobilePairingPanel, { global: { plugins: [i18n], stubs: {
    'a-tag': { template: '<span class="tag"><slot/></span>' },
    GlassButton: {
      props: ['disabled'], emits: ['click'],
      template: '<button class="gb" :disabled="disabled" @click="$emit(\'click\')"><slot/></button>',
    },
  } } })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  ;(URL as unknown as Record<string, unknown>).createObjectURL = vi.fn(() => 'blob:pairing-qr')
  ;(URL as unknown as Record<string, unknown>).revokeObjectURL = vi.fn()
  getPairedDevices.mockResolvedValue({ devices: [] })
  getTunnelStatus.mockResolvedValue(tunnel())
  getPairingQrcodeBlob.mockResolvedValue(new Blob(['x'], { type: 'image/png' }))
})

afterEach(() => {
  vi.useRealTimers()
})

async function opened() {
  const w = mountPanel()
  await flushPromises()
  return w
}

describe('MobilePairingPanel — 通道阻断态', () => {
  it('配了中继却没注册上：发码按钮 disabled，且屏上不出现"等待扫码"', async () => {
    getTunnelStatus.mockResolvedValue(tunnel({ state: 'relay_down', route_id: null }))
    const w = await opened()

    const generate = w.find('[data-testid="pairing-generate"]')
    expect(generate.attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="pairing-blocked"]').exists()).toBe(true)
    expect(w.text()).not.toContain('等待扫码')
    expect(w.text()).toContain('中继失联')
  })

  it('后端以 503 tunnel_not_ready 拒发码时，照它点名原因，不改写成"操作失败"', async () => {
    // 面板 disable 只是 UX；这一格钉的是"服务端那句原因有没有被原样读出来"——
    // 把它压成"配对操作失败"就丢掉了"该去看中继"这条唯一的处置线索。
    getTunnelStatus.mockRejectedValue({ response: {
      status: 503, data: { detail: { code: 'tunnel_not_ready', message: '中继未注册' } },
    } })
    const w = mountPanel()
    await flushPromises()

    expect(w.find('[data-testid="tunnel-error"]').text()).toContain('服务端拒绝发码')
    expect(w.find('[data-testid="tunnel-error"]').text()).toContain('中继未注册')
    expect(w.text()).not.toContain('配对操作失败')
    expect(w.text()).not.toContain('无权')
  })

  it('没配中继时照常能发码：闸门不许把局域网/自建反代一起关掉', async () => {
    getTunnelStatus.mockResolvedValue(tunnel({
      state: 'disabled', configured: false, route_id: null, address_source: 'direct',
    }))
    const w = await opened()
    const generate = w.find('[data-testid="pairing-generate"]')
    expect(generate.attributes('disabled')).toBeUndefined()

    generatePairing.mockResolvedValue(CODE)
    await generate.trigger('click')
    await flushPromises()
    expect(generatePairing).toHaveBeenCalledTimes(1)
  })

  it('经中继时徽标带上 routeId 与 RTT（读数是具体的，不是一个"已连接"）', async () => {
    const w = await opened()
    expect(w.find('[data-testid="tunnel-state"]').text()).toContain('经中继')
    expect(w.find('[data-testid="tunnel-badge"]').text()).toContain('abc123def456')
    expect(w.find('[data-testid="tunnel-badge"]').text()).toContain('42 ms')
  })

  it('通道读数取不到：徽标退回直连文案之前必须先把错误说出来，不静默画成正常', async () => {
    getTunnelStatus.mockRejectedValue({ response: { status: 500 } })
    const w = mountPanel()
    await flushPromises()
    expect(w.find('[data-testid="tunnel-error"]').exists(),
      '通道读失败必须看得见，不能被设备列表的成功抹掉').toBe(true)
  })
})

describe('MobilePairingPanel — 已扫码/终态分格', () => {
  it('scanned 显示"已扫码"，并给出撤回这张码的动作', async () => {
    generatePairing.mockResolvedValue(CODE)
    getPairingStatus.mockResolvedValue({ code: CODE.code, status: 'scanned' })
    const w = await opened()
    await w.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(2100)
    await flushPromises()

    expect(w.find('[data-testid="pairing-status"]').text()).toContain('已扫码')
    expect(w.find('[data-testid="pairing-cancel"]').exists()).toBe(true)
  })

  it('revoked 与 expired 文案不同（一个要查是谁，一个什么都不用做）', async () => {
    generatePairing.mockResolvedValue(CODE)
    for (const [state, expectText] of [['revoked', '已被解除'], ['expired', '已过期']] as const) {
      getPairingStatus.mockResolvedValue({ code: CODE.code, status: state })
      const w = await opened()
      await w.find('[data-testid="pairing-generate"]').trigger('click')
      await flushPromises()
      vi.advanceTimersByTime(2100)
      await flushPromises()
      expect(w.text()).toContain(expectText)
    }
  })

  it('点撤回真的调 cancel 并把二维码撤下（不等 300 秒）', async () => {
    generatePairing.mockResolvedValue(CODE)
    getPairingStatus.mockResolvedValue({ code: CODE.code, status: 'pending' })
    cancelPairing.mockResolvedValue({ status: 'aborted' })
    const w = await opened()
    await w.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()

    await w.find('[data-testid="pairing-cancel"]').trigger('click')
    await flushPromises()
    expect(cancelPairing).toHaveBeenCalledWith(CODE.code)
    expect(w.find('[data-testid="pairing-active"]').exists()).toBe(false)
  })

  it('在册设备给出「最近连接时间」与 30 天提醒位（长期在册、不代删）', async () => {
    getPairedDevices.mockResolvedValue({ devices: [{
      pairing_id: 'pair-old', device_name: '周末手机', device_type: 'mobile',
      paired_at: 1, last_active: (Date.now() - 35 * 86400000) / 1000,
      is_online: false, state: 'dormant', dormant: true,
    }] })
    const w = await opened()
    const item = w.find('[data-testid="pairing-device"]')
    expect(item.exists()).toBe(true)
    expect(item.find('[data-testid="pairing-device-dormant"]').text()).toContain('30 天')
    expect(item.find('[data-testid="pairing-device-last"]').text()).toContain('35 天前连接')
  })
})
