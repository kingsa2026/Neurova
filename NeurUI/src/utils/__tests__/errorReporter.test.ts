/**
 * errorReporter（错误日志上报）TDD 测试（2026-09-03）
 *
 * 契约：
 * 1. 用户标识唯一性：首次生成随机固定代号（nv_client_id UUID），跨会话复用；
 * 2. 平台区分：tauri 壳 → desktop-windows / desktop-linux；浏览器 → web（Linux/mac 细分）；
 * 3. 脱敏：token/Bearer/API Key/password/本地用户目录路径打码；控制字符剥除；长度封顶；
 * 4. 上报字段：error_at 精确到秒（ISO + Z）、error_code 白名单形态（非法字符转 _）；
 * 5. 去重：同一 error_code+message 30 秒窗口内只发一次（fetch 调用次数=1）；
 * 6. 队列：网络失败保留队列（fetch reject），成功排空；
 * 7. 日限额：达到上限不再发送。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  getClientId,
  detectPlatform,
  sanitizeText,
  initErrorReporter,
  isErrorReporterEnabled,
  setReportEnabledPref,
  getReportEnabledPref,
  reportManualFeedback,
  setErrorReporterInstance,
} from '@/utils/errorReporter'

describe('getClientId 用户固定代号', () => {
  beforeEach(() => localStorage.clear())

  it('首次生成 UUID 形代号并持久化', () => {
    const id = getClientId()
    expect(id).toMatch(/^[0-9a-fA-F-]{8,64}$/)
    expect(localStorage.getItem('nv_client_id')).toBe(id)
  })

  it('同一会话内多次调用返回同一代号（固定）', () => {
    expect(getClientId()).toBe(getClientId())
  })
})

describe('detectPlatform 平台区分', () => {
  beforeEach(() => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } as any)
    delete (window as any).__TAURI__
    ;(window as any).__TAURI__ = undefined
  })

  it('tauri 壳 + Windows UA → desktop-windows', () => {
    ;(window as any).__TAURI__ = { core: {} }
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Windows NT 10.0)' } as any)
    expect(detectPlatform()).toBe('desktop-windows')
  })

  it('tauri 壳 + Linux UA → desktop-linux', () => {
    ;(window as any).__TAURI__ = { core: {} }
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' } as any)
    expect(detectPlatform()).toBe('desktop-linux')
  })

  it('浏览器 + Linux UA → linux', () => {
    ;(window as any).__TAURI__ = undefined
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' } as any)
    expect(detectPlatform()).toBe('linux')
  })

  it('普通浏览器 → web', () => {
    ;(window as any).__TAURI__ = undefined
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Windows NT 10.0)' } as any)
    expect(detectPlatform()).toBe('web')
  })
})

describe('sanitizeText 脱敏', () => {
  it('打码 SK 密钥 / Bearer token / password / 用户目录', () => {
    const out = sanitizeText(
      'failed sk-abcdef0123456789xyz with Bearer abc.def.ghi and password=123456 path C:\\Users\\tony\\app',
      500,
    )
    expect(out).not.toContain('sk-abcdef0123456789xyz')
    expect(out).not.toContain('abc.def.ghi')
    expect(out).not.toContain('123456')
    expect(out).not.toContain('tony')
  })

  it('剥控制字符并封顶长度', () => {
    const out = sanitizeText('a\u0000b\u001Fc' + 'x'.repeat(1000), 50)
    expect(out).not.toContain('\u0000')
    expect(out.length).toBeLessThanOrEqual(50)
  })
})

describe('initErrorReporter 采集链路', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (X11; Linux x86_64)' } as any)
    ;(window as any).__TAURI__ = undefined
    fetchMock.mockReset()
    fetchMock.mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
  })

  it('window error → 上报字段齐全（代号/秒级时间/平台/source=window）', async () => {
    const reporter = initErrorReporter({ force: true, version: '1.0.0' })
    window.dispatchEvent(new ErrorEvent('error', { message: 'boom', filename: 'x.ts', lineno: 1 }))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.client_id).toMatch(/^[0-9a-fA-F-]{8,64}$/)
    expect(body.error_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/) // 精确到秒
    expect(body.platform).toBe('linux')
    expect(body.source).toBe('window')
    expect(body.error_code).toBe('window-error')
    expect(body.message).toContain('boom')
    expect(body.app_version).toBe('1.0.0')
    reporter.dispose()
  })

  it('unhandledrejection → source=promise', async () => {
    const reporter = initErrorReporter({ force: true })
    window.dispatchEvent(new PromiseRejectionEvent('unhandledrejection', { promise: Promise.resolve(), reason: new Error('rej') } as any))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.source).toBe('promise')
    expect(body.error_code).toBe('unhandled-promise')
    reporter.dispose()
  })

  it('30 秒窗口去重：同一错误只上报一次', async () => {
    const reporter = initErrorReporter({ force: true })
    window.dispatchEvent(new ErrorEvent('error', { message: 'same-error' }))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    window.dispatchEvent(new ErrorEvent('error', { message: 'same-error' }))
    window.dispatchEvent(new ErrorEvent('error', { message: 'same-error' }))
    await new Promise((r) => setTimeout(r, 30))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    reporter.dispose()
  })

  it('网络失败保留队列，成功后排空', async () => {
    let working = false
    fetchMock.mockImplementation(() => {
      if (!working) return Promise.reject(new TypeError('network down'))
      return Promise.resolve(new Response('{"ok":true}', { status: 200 }))
    })
    const reporter = initErrorReporter({ force: true })
    window.dispatchEvent(new ErrorEvent('error', { message: 'queued-err' }))
    await new Promise((r) => setTimeout(r, 30))
    expect(reporter.queueLength()).toBe(1) // 失败保留

    working = true
    window.dispatchEvent(new ErrorEvent('error', { message: 'other-err' }))
    await vi.waitFor(() => expect(reporter.queueLength()).toBe(0)) // 第二条触发 flush 排空
    reporter.dispose()
  })

  it('error_code 非法字符规范化（白名单形态）', async () => {
    const reporter = initErrorReporter({ force: true })
    reporter.capture('manual', 'bad code!!@', 'msg')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.error_code).toBe('bad_code___')
    reporter.dispose()
  })

  it('未启用（无 force 且未设 env）时不发送', () => {
    const reporter = initErrorReporter({ version: 'x' })
    reporter.capture('manual', 'app-error', 'msg')
    expect(fetchMock).not.toHaveBeenCalled()
    reporter.dispose()
  })


    it('429 限流响应：保留队列重试（不丢弃）', async () => {
      fetchMock.mockResolvedValueOnce(new Response('{"ok":false}', { status: 429 }))
      fetchMock.mockResolvedValueOnce(new Response('{"ok":true}', { status: 200 }))
      const reporter = initErrorReporter({ force: true })
      window.dispatchEvent(new ErrorEvent('error', { message: 'rate-limit-keep' }))
      await new Promise((r) => setTimeout(r, 30))
      expect(reporter.queueLength()).toBe(1) // 429 后保留
      // 下一次事件触发 flush 成功排空
      window.dispatchEvent(new ErrorEvent('error', { message: 'rate-limit-keep-2' }))
      await vi.waitFor(() => expect(reporter.queueLength()).toBe(0))
      reporter.dispose()
    })

    it('400 schema 拒绝：丢弃该条继续', async () => {
      fetchMock.mockResolvedValue(new Response('{"ok":false}', { status: 400 }))
      const reporter = initErrorReporter({ force: true })
      window.dispatchEvent(new ErrorEvent('error', { message: 'schema-reject' }))
      await vi.waitFor(() => expect(reporter.queueLength()).toBe(0))
      reporter.dispose()
    })

  it('pagehide 兜底：队列经 sendBeacon 发出（无 keepalive preflight 限制）', async () => {
    const beaconMock = vi.fn((_url: string, _data: string) => true)
    vi.stubGlobal('navigator', {
      userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
      sendBeacon: beaconMock,
    } as any)
    fetchMock.mockRejectedValue(new TypeError('network down'))
    const reporter = initErrorReporter({ force: true })
    window.dispatchEvent(new ErrorEvent('error', { message: 'beacon-err' }))
    await new Promise((r) => setTimeout(r, 30))
    expect(reporter.queueLength()).toBe(1)

    window.dispatchEvent(new Event('pagehide'))
    expect(beaconMock).toHaveBeenCalledTimes(1)
    const [url, payload] = beaconMock.mock.calls[0]
    expect(url).toContain('/error-report.php')
    const body = JSON.parse(String(payload))
    expect(body.message).toBe('beacon-err')
    expect(body.client_id).toMatch(/^[0-9a-fA-F-]{8,64}$/)
    reporter.dispose()
  })
})

describe('错误上报开关（用户偏好）', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    localStorage.clear()
    fetchMock.mockReset()
    fetchMock.mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
  })

  it('setReportEnabledPref 持久化 on/off，getReportEnabledPref 读取', () => {
    expect(getReportEnabledPref()).toBeNull()
    setReportEnabledPref(true)
    expect(getReportEnabledPref()).toBe(true)
    setReportEnabledPref(false)
    expect(getReportEnabledPref()).toBe(false)
    expect(localStorage.getItem('nv_err_report_enabled')).toBe('off')
  })

  it('开关关闭时 capture 不发送', async () => {
    setReportEnabledPref(false)
    const reporter = initErrorReporter({})
    window.dispatchEvent(new ErrorEvent('error', { message: 'gated-off' }))
    await new Promise((res) => setTimeout(res, 30))
    expect(fetchMock).not.toHaveBeenCalled()
    reporter.dispose()
  })

  it('开关打开后 capture 发送（用户偏好覆盖 dev 默认关闭）', async () => {
    setReportEnabledPref(true)
    const reporter = initErrorReporter({})
    window.dispatchEvent(new ErrorEvent('error', { message: 'gated-on' }))
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.message).toBe('gated-on')
    reporter.dispose()
  })

  it('手动上报 reportManualFeedback 不受开关限制', async () => {
    setReportEnabledPref(false)
    const reporter = initErrorReporter({})
    setErrorReporterInstance(reporter)
    reportManualFeedback('这是用户主动反馈的问题描述')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.source).toBe('manual')
    expect(body.error_code).toBe('user-feedback')
    expect(body.message).toBe('这是用户主动反馈的问题描述')
    expect(body.extra.manual).toBe(true)
    reporter.dispose()
  })

  it('isErrorReporterEnabled 反映偏好：on=true / off=false', () => {
    setReportEnabledPref(true)
    expect(isErrorReporterEnabled()).toBe(true)
    setReportEnabledPref(false)
    expect(isErrorReporterEnabled()).toBe(false)
  })
})
