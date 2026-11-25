/**
 * API-03 前端接线判据：登出请求必须把 refresh_token 带给后端。
 *
 * 后端登出只在收到 refresh_token 时连带撤销 refresh 家族；前端若只发空 body，
 * 登出后旧 refresh 仍可续签——API-03 的后端修复在网页端等同未生效。
 */
import { describe, expect, it, vi } from 'vitest'

const post = vi.fn(async (..._args: unknown[]) => ({ code: 0, message: 'ok', data: null }))

vi.mock('@/api/index', () => ({
  api: {
    get: vi.fn(),
    post: (url: string, body?: unknown) => post(url, body),
  },
}))

import { authAPI } from '../auth'

describe('authAPI.logout carries refresh_token', () => {
  it('posts refresh_token when provided', async () => {
    await authAPI.logout('rt-1')
    expect(post).toHaveBeenCalledWith('/auth/logout', { refresh_token: 'rt-1' })
  })

  it('posts no body when no refresh token is available', async () => {
    post.mockClear()
    await authAPI.logout()
    expect(post).toHaveBeenCalledWith('/auth/logout', undefined)
  })
})