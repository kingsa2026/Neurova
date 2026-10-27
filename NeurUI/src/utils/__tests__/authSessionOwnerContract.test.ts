/**
 * 会话键属主模块自身的契约（新单元；本批红灯里"import 红"来自这一档，与行为红分开计）
 *
 * 两件值得钉的事：
 * 1. 键名是**线上面**——`auth_token`/`refresh_token`/`user` 三把键已在 localStorage 里存着
 *    真实会话。属主改名等于把所有现存登录态一次性作废，所以这里的断言是"改名必须显式过这一格"。
 * 2. 读取口不给 null：8 处消费点里有的写 `|| ''`、有的直接 `Bearer ${token}`（未登录时
 *    拼出字面 `Bearer null`）。单一读取口把这两种写法收敛成一种。
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { AUTH_REFRESH_TOKEN_KEY, AUTH_TOKEN_KEY, AUTH_USER_KEY, readAccessToken } from '@/utils/authSession'

beforeEach(() => {
  localStorage.clear()
})

describe('会话键属主契约', () => {
  it('三把键名与线上历史一致（改名要过这一格，不许静默作废所有登录态）', () => {
    expect(AUTH_TOKEN_KEY).toBe('auth_token')
    expect(AUTH_REFRESH_TOKEN_KEY).toBe('refresh_token')
    expect(AUTH_USER_KEY).toBe('user')
  })

  it('无凭证时给空串而不是 null：调用方拼出的头不会是字面 "Bearer null"', () => {
    expect(readAccessToken()).toBe('')
    expect(`Bearer ${readAccessToken()}`).not.toContain('null')
  })

  it('读的就是 secureStorage 里那把键（写侧落盘即可读出，不经任何手工传参）', () => {
    localStorage.setItem(AUTH_TOKEN_KEY, 'WS-LIVE-JWT')
    expect(readAccessToken()).toBe('WS-LIVE-JWT')
  })
})
