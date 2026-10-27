/**
 * 会话键的写侧与读侧必须是同一把键（跨边界闭环，今天该绿＝回归闸）
 *
 * 这条档不 import 待建模块——本批的行为判据要能被单独跑红/绿，不能被整档
 * `Failed to resolve import` 吞掉（新单元的契约另起一份档）。
 *
 * 钉的是真实链路：`stores/auth.login()`（写侧，经 secureStorage 落 jsdom localStorage）
 * → 真 `request` 请求拦截器（读侧）→ 发出去的 `Authorization` 头。两侧一旦键名分家，
 * 这一格当场红——那正是"12 份键名出处"唯一会咬人的形态：写侧改了，读侧安静地发空头。
 *
 * 夹具形态说明：token 值从**生产写侧**拿（login 的响应体经 persistTokens 落盘），不在测试里
 * 手工 `localStorage.setItem('auth_token', ...)`——手工塞等于把键名又抄一遍进判据。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { AxiosResponse } from 'axios'

vi.mock('@/utils/logger', () => ({
  default: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))

const { authApiDouble } = vi.hoisted(() => ({
  authApiDouble: {
    login: vi.fn(async () => ({ access_token: 'SESSION-T-9', refresh_token: 'SESSION-R-9' })),
    getCurrentUser: vi.fn(async () => ({ user_id: 'u9', username: 'kingsa', role: 'user' })),
    logout: vi.fn(async () => ({ success: true })),
  },
}))

vi.mock('@/api/auth', () => ({ authAPI: authApiDouble }))

import { request } from '@/api'
import { useAuthStore } from '@/stores/auth'

let sentAuthHeaders: Array<string | undefined> = []

function installCapturingAdapter(): void {
  sentAuthHeaders = []
  request.defaults.adapter = async (cfg) => {
    const headers = cfg.headers as { Authorization?: string } | undefined
    sentAuthHeaders.push(headers?.Authorization ? String(headers.Authorization) : undefined)
    return {
      data: { ok: true },
      status: 200,
      statusText: 'OK',
      config: cfg,
      headers: {},
    } as unknown as AxiosResponse
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setActivePinia(createPinia())
  installCapturingAdapter()
})

describe('会话键写读同源', () => {
  it('login() 落盘后，真拦截器发出的就是那一个 token', async () => {
    const store = useAuthStore()
    expect(await store.login({ username: 'kingsa', password: 'correct-horse' })).toBe(true)

    await request.get('/memory?limit=1')

    expect(sentAuthHeaders).toEqual(['Bearer SESSION-T-9'])
  })

  it('反向：logout 后不再有 Authorization 头（不许留下旧值，也不许发 "Bearer null"）', async () => {
    const store = useAuthStore()
    await store.login({ username: 'kingsa', password: 'correct-horse' })
    await request.get('/memory?limit=1')
    expect(sentAuthHeaders[0]).toBe('Bearer SESSION-T-9')

    await store.logout()
    await request.get('/memory?limit=1')

    expect(sentAuthHeaders[1]).toBeUndefined()
    expect(sentAuthHeaders.some((h) => h === 'Bearer null' || h === 'Bearer undefined')).toBe(false)
  })

  it('login 的写侧确实落盘（后续格都以此为准，先把它钉住再往下比）', async () => {
    const store = useAuthStore()
    expect(await store.login({ username: 'kingsa', password: 'correct-horse' })).toBe(true)
    await request.get('/memory?limit=1')
    expect(sentAuthHeaders).toEqual(['Bearer SESSION-T-9'])
  })

  it('刷新/注册写回的 token 也走同一把键（新 token 立刻被下一个请求读出）', async () => {
    const store = useAuthStore()
    expect(await store.login({ username: 'kingsa', password: 'correct-horse' })).toBe(true)
    await request.get('/memory?limit=1')
    expect(sentAuthHeaders.length).toBe(1)

    // 生产写侧另一条腿：注册/刷新后落盘走 setTokensFromRegistration
    store.setTokensFromRegistration({ access_token: 'NEW-A', refresh_token: 'NEW-R' })

    await request.get('/memory?limit=1')
    expect(sentAuthHeaders).toEqual(['Bearer SESSION-T-9', 'Bearer NEW-A'])
  })
})
