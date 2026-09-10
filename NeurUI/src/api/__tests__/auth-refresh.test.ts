/**
 * F-05 回归测试：401 单飞刷新（api/index.ts 响应拦截器）。
 *
 * 锁定契约：
 * 1. 401（非 auth 端点）且有 refresh_token → 刷新一次并重放原请求（带新 token）；
 * 2. 并发 401 共享同一刷新 Promise（single-flight，只发一次 /auth/refresh）；
 * 3. 刷新成功 → 新 access/refresh token 落盘 secureStorage；
 * 4. 刷新失败 / 无 refresh_token / auth 端点自身 401 → 清凭证、不重放；
 * 5. 重放后仍 401 → 不二次刷新（防循环），清凭证。
 *
 * 用假 adapter 模拟后端（不依赖网络），模式沿用 error-log.test.ts。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { AxiosError, type AxiosResponse } from 'axios'

vi.mock('@/utils/logger', () => ({
  default: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))
vi.mock('@/utils/security', () => ({
  secureStorage: { get: vi.fn(() => null), set: vi.fn(), remove: vi.fn() },
}))

import { secureStorage } from '@/utils/security'
import { request } from '../index'

const secureGet = vi.mocked(secureStorage.get)
const secureSet = vi.mocked(secureStorage.set)
const secureRemove = vi.mocked(secureStorage.remove)

/** adapter 观测状态 */
let refreshCalls = 0
let refreshShouldFail = false
let dataCalls = 0
let dataAlwaysFail = false
const dataAuthHeaders: string[] = []

function makeStatusError(status: number, cfg: unknown): AxiosError {
  return new AxiosError(
    `Request failed with status code ${status}`,
    AxiosError.ERR_BAD_REQUEST,
    cfg as never,
    null,
    { status, config: cfg, data: null, headers: {} } as unknown as AxiosResponse,
  )
}

function makeResponse(status: number, data: unknown, cfg: unknown): AxiosResponse {
  return {
    data,
    status,
    statusText: 'OK',
    config: cfg as never,
    headers: {},
  } as unknown as AxiosResponse
}

function readAuthHeader(cfg: { headers?: unknown }): string {
  const h = cfg.headers as { Authorization?: string; get?: (k: string) => string } | undefined
  return String(h?.Authorization ?? h?.get?.('Authorization') ?? '')
}

function installAdapter(): void {
  request.defaults.adapter = async (cfg) => {
    const url = cfg.url || ''
    if (url.includes('/auth/refresh')) {
      refreshCalls += 1
      if (refreshShouldFail) throw makeStatusError(401, cfg)
      return makeResponse(200, { access_token: 'new-access', refresh_token: 'new-refresh' }, cfg)
    }
    dataCalls += 1
    const auth = readAuthHeader(cfg)
    dataAuthHeaders.push(auth)
    if (dataAlwaysFail || auth !== 'Bearer new-access') throw makeStatusError(401, cfg)
    return makeResponse(200, { ok: true }, cfg)
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  refreshCalls = 0
  refreshShouldFail = false
  dataCalls = 0
  dataAlwaysFail = false
  dataAuthHeaders.length = 0
  secureGet.mockImplementation((k: string) => (k === 'refresh_token' ? 'rt-old' : null))
  installAdapter()
})

describe('401 单飞刷新（F-05）', () => {
  it('刷新成功 → 重放原请求一次并带新 token，新 token 落盘', async () => {
    const res = await request.get('/console/chat/sessions')
    expect(res).toEqual({ ok: true })
    expect(refreshCalls).toBe(1)
    expect(dataCalls).toBe(2) // 原始 401 + 重放成功
    expect(dataAuthHeaders[1]).toBe('Bearer new-access')
    expect(secureSet).toHaveBeenCalledWith('auth_token', 'new-access')
    expect(secureSet).toHaveBeenCalledWith('refresh_token', 'new-refresh')
    expect(secureRemove).not.toHaveBeenCalled()
  })

  it('并发 401 共享同一刷新 Promise（只发一次 /auth/refresh）', async () => {
    const [a, b] = await Promise.all([
      request.get('/data/one'),
      request.get('/data/two'),
    ])
    expect(a).toEqual({ ok: true })
    expect(b).toEqual({ ok: true })
    expect(refreshCalls).toBe(1)
    expect(dataCalls).toBe(4) // 2 原始 401 + 2 重放
  })

  it('刷新失败 → 清凭证、不重放、原请求 reject', async () => {
    refreshShouldFail = true
    await expect(request.get('/data/x')).rejects.toBeTruthy()
    expect(refreshCalls).toBe(1)
    expect(dataCalls).toBe(1) // 无重放
    expect(secureRemove).toHaveBeenCalledWith('auth_token')
    expect(secureRemove).toHaveBeenCalledWith('refresh_token')
    expect(secureRemove).toHaveBeenCalledWith('user')
  })

  it('无 refresh_token → 直接清凭证（旧行为兜底），不刷新', async () => {
    secureGet.mockReturnValue(null)
    await expect(request.get('/data/x')).rejects.toBeTruthy()
    expect(refreshCalls).toBe(0)
    expect(dataCalls).toBe(1)
    expect(secureRemove).toHaveBeenCalledWith('auth_token')
  })

  it('auth 端点自身 401（登录/刷新）→ 不触发刷新', async () => {
    await expect(request.post('/auth/login', { username: 'u', password: 'p' })).rejects.toBeTruthy()
    expect(refreshCalls).toBe(0)
    expect(secureRemove).toHaveBeenCalledWith('auth_token')
  })

  it('重放后仍 401 → 不二次刷新（防循环），清凭证', async () => {
    dataAlwaysFail = true
    await expect(request.get('/data/x')).rejects.toBeTruthy()
    expect(refreshCalls).toBe(1)
    expect(dataCalls).toBe(2) // 原始 + 一次重放，无二次刷新
    expect(secureRemove).toHaveBeenCalledWith('auth_token')
  })
})
