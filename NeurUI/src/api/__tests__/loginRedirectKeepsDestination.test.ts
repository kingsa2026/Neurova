/**
 * 401 跳登录必须保住目的地（§6-430 遗留的「登录前空态」根因之二）
 *
 * 实测形态（真浏览器，Playwright 独立 profile）：未登录时 boot 期的
 * `/api/v1/agents` 先 401，响应拦截器把跳转写死成裸 `/login`，于是路由守卫已经生成的
 * `?redirect=` 深链整条丢掉——用户登完落在总览，而不是原来那一页。（注：`/memory` 并不
 * 是路由，记忆页真路径是 `/agent/:agentId/memory`，写错的那条会被 catch-all 兜到
 * `/dashboard`；丢掉深链这件事对任何一条受保护路径都成立。）
 *
 * 判据三段：
 * 1. 刷新不可用的 401 → 跳 `/login?redirect=<当前 fullPath>`，路径与查询都带上；
 * 2. 已在 /login 时不再跳（避免自循环，P2-7 既有行为）；
 * 3. 跳转口径只有 `loginHref()` 一处——守卫、拦截器、页面按钮三处都问它，不许各拼一份。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, type AxiosResponse } from 'axios'

vi.mock('@/utils/logger', () => ({
  default: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))
vi.mock('@/utils/security', () => ({
  secureStorage: { get: vi.fn(() => null), set: vi.fn(), remove: vi.fn() },
}))

import { secureStorage } from '@/utils/security'
import { request, resetAuthRedirectForTest } from '../index'

const secureGet = vi.mocked(secureStorage.get)

/** jsdom 没有真实导航；把 location 换成可观察的替身，收尾还原。 */
const originalLocation = window.location
type LocationStub = {
  pathname: string
  search: string
  hash: string
  href: string
  origin: string
}

function installLocation(pathname: string, search = ''): LocationStub {
  const stub: LocationStub = {
    pathname,
    search,
    hash: '',
    href: `http://localhost:8100${pathname}${search}`,
    origin: 'http://localhost:8100',
  }
  Object.defineProperty(window, 'location', { configurable: true, writable: true, value: stub })
  return stub
}

function always401(): void {
  request.defaults.adapter = async (cfg) => {
    throw new AxiosError(
      'Request failed with status code 401',
      AxiosError.ERR_BAD_REQUEST,
      cfg as never,
      null,
      { status: 401, config: cfg, data: null, headers: {} } as unknown as AxiosResponse,
    )
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  resetAuthRedirectForTest()
  // 无 refresh_token ⇒ 刷新这条路根本走不通，只能落到「清凭证 + 跳登录」那格
  secureGet.mockReturnValue(null)
  always401()
})

describe('401 跳登录保住目的地', () => {
  it('在记忆页上撞 401 → 跳 /login 并把记忆页整条路径作为 redirect 带上', async () => {
    const loc = installLocation('/agent/default/memory')
    try {
      await expect(request.get('/memory?limit=20')).rejects.toBeTruthy()
      expect(loc.href).toMatch(/^\/login\?redirect=/)
      expect(new URL(loc.href, 'http://localhost:8100').searchParams.get('redirect')).toBe(
        '/agent/default/memory',
      )
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, writable: true, value: originalLocation })
    }
  })

  it('当前查询串一起带走：?tab=stats 回来还是那一格', async () => {
    const loc = installLocation('/agent/default/memory', '?tab=stats')
    try {
      await expect(request.get('/memory/stats')).rejects.toBeTruthy()
      expect(new URL(loc.href, 'http://localhost:8100').searchParams.get('redirect')).toBe(
        '/agent/default/memory?tab=stats',
      )
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, writable: true, value: originalLocation })
    }
  })

  it('反向：已经在 /login 上撞 401 不再跳（防自循环，P2-7 既有行为不得放宽）', async () => {
    const loc = installLocation('/login')
    try {
      await expect(request.get('/auth/me')).rejects.toBeTruthy()
      expect(loc.href).toBe('http://localhost:8100/login')
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, writable: true, value: originalLocation })
    }
  })

  it('跳转口径只有一处：api/index.ts 不再自己拼 /login 字符串', async () => {
    const source = (await import('@/api/index.ts?raw')).default
    const builtByHelper = /loginHref\(/.test(source)
    const handSpliced = /window\.location\.href\s*=\s*['"]\/login['"]/.test(source)

    expect(builtByHelper).toBe(true)
    expect(handSpliced).toBe(false)
  })
})
