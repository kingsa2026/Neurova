/**
 * 移动端配对面板（工单 2026-10-13 批 29，用户裁定「建配对面板」）。
 *
 * 这块的新事实只有三条，判据就钉这三条（其余是渲染，不值一格）：
 * 1. **取图走带凭证的 blob**，不是 `<img :src="qr_code_url">`——那一口在 §6-172 批 28 上了
 *    登录门，而资源标签发不出 Authorization 头；把 URL 直挂 img 会得到一张 401 的空图，
 *    而"码在屏幕上、图却空白"比直接报错更难归因。
 * 2. **自建 object URL 归本面板持有并释放**：换码、确认、过期、卸载四个出口都得 revoke。
 *    那张图的内容是一个认证凭据，屏幕关掉还留着 blob 就等于留了一把钥匙。
 * 3. **确认即收摊**：轮询到 `confirmed` 必须停轮询、撤下二维码并重取设备列表——
 *    凭据已经用掉了，还挂着它就是纯暴露面。
 *
 * 外加面板的一条既有纪律（与渠道身份面板同源）：401/403 说"无权"，不退化成"还没有设备"。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

const generatePairing = vi.fn()
const getPairingStatus = vi.fn()
const getPairedDevices = vi.fn()
const revokePairing = vi.fn()
const getPairingQrcodeBlob = vi.fn()

vi.mock('@/api/modules/mobile', () => ({
  generatePairing: (...a: unknown[]) => generatePairing(...a),
  getPairingStatus: (...a: unknown[]) => getPairingStatus(...a),
  getPairedDevices: (...a: unknown[]) => getPairedDevices(...a),
  revokePairing: (...a: unknown[]) => revokePairing(...a),
  getPairingQrcodeBlob: (...a: unknown[]) => getPairingQrcodeBlob(...a),
}))

import MobilePairingPanel from '../MobilePairingPanel.vue'
import zhCN from '@/i18n/locales/zh-CN'

const createObjectURL = vi.fn(() => 'blob:pairing-qr')
const revokeObjectURL = vi.fn()

const CODE = { code: '248160', qr_code_url: 'http://x/api/v1/mobile/pairing/qrcode/248160',
  expires_in: 300, pairing_id: 'pair-1' }
const DEVICE = { pairing_id: 'pair-9', device_name: 'Pixel 8', device_type: 'mobile',
  paired_at: 1, is_online: true }

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
  // jsdom 不实现 object URL；本仓既有档同一写法（dockPanels.revoke / audioUrl）
  ;(URL as unknown as Record<string, unknown>).createObjectURL = createObjectURL
  ;(URL as unknown as Record<string, unknown>).revokeObjectURL = revokeObjectURL
  getPairedDevices.mockResolvedValue({ devices: [DEVICE], total: 1 })
  getPairingQrcodeBlob.mockResolvedValue(new Blob(['qr'], { type: 'image/png' }))
  generatePairing.mockResolvedValue(CODE)
  getPairingStatus.mockResolvedValue({ code: CODE.code, status: 'pending' })
})
afterEach(() => { vi.useRealTimers() })

describe('MobilePairingPanel — 取图与所有权', () => {
  it('首屏取设备列表，空态与权限态各说各话', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(getPairedDevices).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('[data-testid="pairing-device"]')).toHaveLength(1)
    expect(wrapper.find('[data-testid="pairing-idle"]').text()).toContain('还没有生成配对码')
  })

  it('点生成 ⇒ 走带凭证的 blob 取图，img 拿到的是自建 object URL', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()

    expect(getPairingQrcodeBlob).toHaveBeenCalledWith(CODE.code)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const img = wrapper.find('[data-testid="pairing-qr"]')
    expect(img.exists(), '取到了 blob 却没上图——用户看到的还是一张空白').toBe(true)
    expect(img.attributes('src')).toBe('blob:pairing-qr')
    expect(wrapper.find('[data-testid="pairing-code"]').text()).toBe(CODE.code)
  })

  it('面板不替设备指定归属：generate 的入参里不许出现 user_id', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()

    const arg = generatePairing.mock.calls[0][0] as Record<string, unknown>
    expect(Object.keys(arg)).not.toContain('user_id')
  })

  it('卸载即释放自建 URL（屏幕没了，凭据的图也不该留着）', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()

    wrapper.unmount()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:pairing-qr')
    expect(vi.getTimerCount(), '屏幕都关了还在轮询').toBe(0)
  })
})

describe('MobilePairingPanel — 确认即收摊', () => {
  it('轮询到 confirmed：停轮询、撤下二维码、重取设备列表', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="pairing-qr"]').exists()).toBe(true)

    getPairedDevices.mockResolvedValue({ devices: [DEVICE, { ...DEVICE, pairing_id: 'pair-new' }], total: 2 })
    getPairingStatus.mockResolvedValue({ code: CODE.code, status: 'confirmed', confirmed_at: 2 })
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(revokeObjectURL).toHaveBeenCalledWith('blob:pairing-qr')
    expect(wrapper.find('[data-testid="pairing-active"]').exists(),
      '已经配好了还挂着凭据图＝纯暴露面').toBe(false)
    expect(wrapper.findAll('[data-testid="pairing-device"]')).toHaveLength(2)
    // 「不再调用」不能只数调用次数：`tick` 首行 `if (!pairing.value) return` 会让一只
    // 没停的定时器**永远不发调用**——那样变异"漏掉 stopPolling"就红不了。
    // 要断的是**定时器本身没了**。
    expect(vi.getTimerCount()).toBe(0)
  })

  it('过期同样停轮询并释放图（过期码不再有机会被扫）', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()

    getPairingStatus.mockResolvedValue({ code: CODE.code, status: 'expired' })
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(revokeObjectURL).toHaveBeenCalledWith('blob:pairing-qr')
    expect(wrapper.find('[data-testid="pairing-status"]').text()).toBe('已过期')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('读不到状态要说"失败"，不能继续挂着"等待扫码"骗人', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('[data-testid="pairing-generate"]').trigger('click')
    await flushPromises()

    getPairingStatus.mockRejectedValue({ response: { status: 403 } })
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(wrapper.find('[data-testid="pairing-error"]').text()).toContain('无权')
    expect(wrapper.find('[data-testid="pairing-status"]').exists(),
      '读不到还挂着状态标签＝把权限问题扮成进行中').toBe(false)
  })
})

describe('MobilePairingPanel — 设备面与权限态', () => {
  it('解绑带上 pairing_id 并重取列表（屏幕状态回到服务端那一份）', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="pairing-revoke-pair-9"]').trigger('click')
    await flushPromises()

    expect(revokePairing).toHaveBeenCalledWith('pair-9')
    expect(getPairedDevices).toHaveBeenCalledTimes(2)
  })

  it('403 说"无权"，不退化成"还没有已配对的设备"', async () => {
    getPairedDevices.mockRejectedValue({ response: { status: 403 } })
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('[data-testid="pairing-error"]').text()).toContain('无权')
    expect(wrapper.find('[data-testid="pairing-devices-empty"]').exists(),
      '把权限问题伪装成空数据，用户永远想不到去登录/要权限').toBe(false)
  })

  it('真没有设备才给空态，且不出错误条', async () => {
    getPairedDevices.mockResolvedValue({ devices: [], total: 0 })
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.find('[data-testid="pairing-devices-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="pairing-error"]').exists()).toBe(false)
  })
})
