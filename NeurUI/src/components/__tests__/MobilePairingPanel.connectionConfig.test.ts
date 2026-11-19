/**
 * 配对面板的**连接方式**那一格（档一：直连 / 自定义对外地址 / 自建中继）。
 *
 * 判据钉五件事：
 * 1. 非管理员（403）⇒ 整块不渲染，面板其余功能照旧——"无权改全局"不许伪装成"没配置"；
 * 2. 管理员读到配置 ⇒ 选择器与按模式展开的填写项都在（custom 出地址框、relay 出地址+令牌框）；
 * 3. 保存 ⇒ `updateConnectionConfig` 收到草稿里的选择，且通道徽标随之重读；
 * 4. 预检结果如实渲染：连不上就显示原因，不画成成功；
 * 5. 令牌只写不读：已存过令牌时占位符说"已保存"，输入新值才更换。
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
const getConnectionConfig = vi.fn()
const updateConnectionConfig = vi.fn()
const preflightConnectionConfig = vi.fn()
const remoteDeploy = vi.fn()
const getRemoteDeployStatus = vi.fn()
const remoteUndeploy = vi.fn()

vi.mock('@/api/modules/mobile', () => ({
  generatePairing: (...a: unknown[]) => generatePairing(...a),
  getPairingStatus: (...a: unknown[]) => getPairingStatus(...a),
  getPairedDevices: (...a: unknown[]) => getPairedDevices(...a),
  revokePairing: (...a: unknown[]) => revokePairing(...a),
  getPairingQrcodeBlob: (...a: unknown[]) => getPairingQrcodeBlob(...a),
  getTunnelStatus: (...a: unknown[]) => getTunnelStatus(...a),
  cancelPairing: (...a: unknown[]) => cancelPairing(...a),
  getConnectionConfig: (...a: unknown[]) => getConnectionConfig(...a),
  updateConnectionConfig: (...a: unknown[]) => updateConnectionConfig(...a),
  preflightConnectionConfig: (...a: unknown[]) => preflightConnectionConfig(...a),
  remoteDeploy: (...a: unknown[]) => remoteDeploy(...a),
  getRemoteDeployStatus: (...a: unknown[]) => getRemoteDeployStatus(...a),
  remoteUndeploy: (...a: unknown[]) => remoteUndeploy(...a),
}))

import MobilePairingPanel from '../MobilePairingPanel.vue'
import zhCN from '@/i18n/locales/zh-CN'

function tunnel(over: Record<string, unknown> = {}) {
  return {
    data: {
      state: 'disabled', configured: false, route_id: null, instance_id: 'nv-1',
      last_heartbeat_at: null, last_rtt_ms: null, active_streams: 0,
      address_source: 'direct', last_error: '', ...over,
    },
  }
}

function config(over: Record<string, unknown> = {}) {
  return {
    data: {
      mode: 'auto', custom_advertised_url: '', relay_url: '',
      relay_enrollment_token_masked: '', has_relay_enrollment_token: false,
      updated_at: '2026-11-19T12:00:00', tunnel: tunnel().data, ...over,
    },
  }
}

const inputStub = {
  props: ['value', 'placeholder'],
  emits: ['update:value'],
  template: `<input :value="value ?? ''" :placeholder="placeholder"
    @input="$emit('update:value', $event.target.value)" />`,
}

function mountPanel() {
  const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as never } })
  return mount(MobilePairingPanel, { global: { plugins: [i18n], stubs: {
    'a-tag': { template: '<span class="tag"><slot/></span>' },
    'a-radio-group': { template: '<div class="radios"><slot/></div>' },
    'a-radio': { template: '<span class="radio"><slot/></span>' },
    'a-input': inputStub,
    'a-input-password': inputStub,
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
  getConnectionConfig.mockResolvedValue(config())
  updateConnectionConfig.mockImplementation((payload: Record<string, unknown>) =>
    Promise.resolve({ data: { ...config().data, ...payload } }))
  preflightConnectionConfig.mockResolvedValue({ data: {
    ok: true, url: 'https://pair.example.com', status_code: 200, latency_ms: 12.5, error: '',
  } })
})

afterEach(() => {
  vi.useRealTimers()
})

async function opened() {
  const w = mountPanel()
  await flushPromises()
  return w
}

describe('MobilePairingPanel — 连接方式（档一）', () => {
  it('非管理员（403）：整块不渲染，发码区照常在', async () => {
    getConnectionConfig.mockRejectedValue({ response: { status: 403 } })
    const w = await opened()
    expect(w.find('[data-testid="connection-config"]').exists()).toBe(false)
    expect(w.find('[data-testid="pairing-generate"]').exists()).toBe(true)
  })

  it('管理员读到 custom 配置：选择器在，地址框带现值', async () => {
    getConnectionConfig.mockResolvedValue(config({
      mode: 'custom', custom_advertised_url: 'https://pair.example.com',
    }))
    const w = await opened()
    expect(w.find('[data-testid="connection-config"]').exists()).toBe(true)
    expect(w.find('[data-testid="connection-custom-field"]').exists()).toBe(true)
    const url = w.find('[data-testid="connection-custom-url"]')
    expect((url.element as HTMLInputElement).value).toBe('https://pair.example.com')
  })

  it('relay 模式：地址与令牌框都在，已存令牌的占位符说"已保存"', async () => {
    getConnectionConfig.mockResolvedValue(config({
      mode: 'relay', relay_url: 'wss://my-relay.example.com',
      relay_enrollment_token_masked: '••••7654', has_relay_enrollment_token: true,
    }))
    const w = await opened()
    expect(w.find('[data-testid="connection-relay-url"]').exists()).toBe(true)
    const token = w.find('[data-testid="connection-relay-token"]')
    expect((token.element as HTMLInputElement).value).toBe('')
    expect(token.attributes('placeholder')).toContain('已保存')
  })

  it('保存：把草稿交给 updateConnectionConfig，并重读通道现状', async () => {
    getConnectionConfig.mockResolvedValue(config({
      mode: 'custom', custom_advertised_url: 'https://pair.example.com',
    }))
    const w = await opened()
    await w.find('[data-testid="connection-custom-url"]').setValue('https://new.example.com')
    await w.find('[data-testid="connection-save"]').trigger('click')
    await flushPromises()
    expect(updateConnectionConfig).toHaveBeenCalledTimes(1)
    expect(updateConnectionConfig).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'custom', custom_advertised_url: 'https://new.example.com',
    }))
    // 通道徽标跟着新配置重读了一次（初载 1 次 + 保存后 1 次）
    expect(getTunnelStatus).toHaveBeenCalledTimes(2)
    expect(w.find('[data-testid="connection-notice"]').text()).toContain('已保存')
  })

  it('预检失败如实显示原因，不画成成功', async () => {
    getConnectionConfig.mockResolvedValue(config({
      mode: 'custom', custom_advertised_url: 'https://pair.example.com',
    }))
    preflightConnectionConfig.mockResolvedValue({ data: {
      ok: false, url: 'https://pair.example.com', status_code: null,
      latency_ms: null, error: 'ConnectError: refused',
    } })
    const w = await opened()
    await w.find('[data-testid="connection-preflight"]').trigger('click')
    await flushPromises()
    expect(preflightConnectionConfig).toHaveBeenCalledWith('https://pair.example.com', '/health')
    const result = w.find('[data-testid="preflight-result"]')
    expect(result.classes()).toContain('is-fail')
    expect(result.text()).toContain('refused')
  })

  it('预检成功显示延迟', async () => {
    getConnectionConfig.mockResolvedValue(config({
      mode: 'custom', custom_advertised_url: 'https://pair.example.com',
    }))
    const w = await opened()
    await w.find('[data-testid="connection-preflight"]').trigger('click')
    await flushPromises()
    const result = w.find('[data-testid="preflight-result"]')
    expect(result.classes()).toContain('is-ok')
    expect(result.text()).toContain('12.5')
  })
})

describe('MobilePairingPanel — 代部署（档三）', () => {
  async function openedRelay() {
    getConnectionConfig.mockResolvedValue(config({
      mode: 'relay', relay_url: 'http://pair.example.com:8443',
    }))
    return await opened()
  }

  it('部署：把服务器与凭据草稿交给 remoteDeploy，轮询成功后重读配置', async () => {
    remoteDeploy.mockResolvedValue({ data: { task_id: 'deploy-1' } })
    getRemoteDeployStatus.mockResolvedValue({ data: {
      task_id: 'deploy-1', state: 'success',
      steps: [{ name: '上传中继文件集', ok: true, detail: '' }],
      relay_url: 'http://pair.example.com:8443', enrollment_token_masked: '••••1234',
      error: '',
    } })
    const w = await openedRelay()
    await w.find('[data-testid="deploy-host"]').setValue('192.0.2.10')
    await w.find('[data-testid="deploy-cred-value"]').setValue('pw-1')
    await w.find('[data-testid="deploy-run"]').trigger('click')
    await flushPromises()
    expect(remoteDeploy).toHaveBeenCalledTimes(1)
    expect(remoteDeploy).toHaveBeenCalledWith(expect.objectContaining({
      host: '192.0.2.10', username: 'root', password: 'pw-1', relay_port: 8443,
    }))
    vi.advanceTimersByTime(1600)
    await flushPromises()
    expect(getRemoteDeployStatus).toHaveBeenCalledWith('deploy-1')
    expect(w.find('[data-testid="connection-notice"]').text()).toContain('pair.example.com')
    expect(getConnectionConfig).toHaveBeenCalledTimes(2)
  })

  it('部署失败：步骤如实渲染为失败，不改写配置', async () => {
    remoteDeploy.mockResolvedValue({ data: { task_id: 'deploy-2' } })
    getRemoteDeployStatus.mockResolvedValue({ data: {
      task_id: 'deploy-2', state: 'failed',
      steps: [{ name: '安装运行依赖', ok: false, detail: 'no network' }],
      relay_url: '', enrollment_token_masked: '', error: '安装依赖 失败',
    } })
    const w = await openedRelay()
    await w.find('[data-testid="deploy-host"]').setValue('192.0.2.10')
    await w.find('[data-testid="deploy-cred-value"]').setValue('pw-1')
    await w.find('[data-testid="deploy-run"]').trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(1600)
    await flushPromises()
    const steps = w.find('[data-testid="deploy-steps"]')
    expect(steps.exists()).toBe(true)
    expect(steps.text()).toContain('no network')
    expect(w.find('[data-testid="connection-config"]').text()).not.toContain('已保存')
  })

  it('代卸载：调用 remoteUndeploy 并把连接方式退回 auto', async () => {
    remoteUndeploy.mockResolvedValue({ data: {
      state: 'success',
      steps: [{ name: '停止并禁用服务', ok: true, detail: '' }],
      relay_url: '', enrollment_token_masked: '', error: '',
    } })
    const w = await openedRelay()
    await w.find('[data-testid="deploy-host"]').setValue('192.0.2.10')
    await w.find('[data-testid="deploy-cred-value"]').setValue('pw-1')
    await w.find('[data-testid="deploy-undo"]').trigger('click')
    await flushPromises()
    expect(remoteUndeploy).toHaveBeenCalledTimes(1)
    expect(getConnectionConfig).toHaveBeenCalledTimes(2)
    expect(w.find('[data-testid="connection-notice"]').text()).toContain('直连')
  })
})

describe('MobilePairingPanel — 预检在 auto 模式也可点', () => {
  it('auto 模式：预检按钮可点，空 url 交给后端探入站来源', async () => {
    preflightConnectionConfig.mockResolvedValue({ data: {
      ok: true, url: 'http://testserver', status_code: 200, latency_ms: 3, error: '',
    } })
    const w = await opened()   // 默认配置 = auto
    const btn = w.find('[data-testid="connection-preflight"]')
    expect(btn.attributes('disabled')).toBeUndefined()
    await btn.trigger('click')
    await flushPromises()
    expect(preflightConnectionConfig).toHaveBeenCalledWith('', '/health')
    const result = w.find('[data-testid="preflight-result"]')
    expect(result.classes()).toContain('is-ok')
    expect(result.text()).toContain('http://testserver')
  })
})
