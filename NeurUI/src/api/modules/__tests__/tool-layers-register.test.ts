/**
 * MCP register 弹窗载荷契约（2026-09-12 复核修复防回归）。
 *
 * 用户报障：register 弹窗的 auth_token 输入框不起作用——
 * ① 前端曾把 auth_token 随手填载荷直发，后端 connect 无此字段 → 静默丢弃；
 * ② 后端 MCPServerConnectRequest.transport 默认 stdio → URL 注册被要求
 *    command → 恒 400。
 * 修复 = 纯函数 buildMCPRegisterPayload 锁定两件事：transport 恒 http、
 * token 映射为标准 Bearer Authorization 头（空值不发）。
 */
import { describe, expect, it } from 'vitest'
import { buildMCPRegisterPayload } from '@/api/modules/tool-layers'

describe('buildMCPRegisterPayload（register 弹窗契约）', () => {
  it('auth_token 映射为标准 Bearer Authorization 头', () => {
    const p = buildMCPRegisterPayload('我的服务', 'https://mcp.example/sse', 'tok-abc123')
    expect(p.transport).toBe('http')
    expect(p.headers.Authorization).toBe('Bearer tok-abc123')
  })

  it('token 两端空白裁剪后入头', () => {
    const p = buildMCPRegisterPayload('x', 'https://a.b', '  tok  ')
    expect(p.headers.Authorization).toBe('Bearer tok')
  })

  it('token 为空/未填 → headers 干净为空对象（不发空 Authorization 污染配置）', () => {
    expect(buildMCPRegisterPayload('x', 'https://a.b').headers).toEqual({})
    expect(buildMCPRegisterPayload('x', 'https://a.b', '   ').headers).toEqual({})
  })

  describe('oauth 子配置（断点①前端写侧）', () => {
    it('授权码流各字段按后端键名入载荷，空白项不发', () => {
      const p = buildMCPRegisterPayload('x', 'https://a.b', undefined, {
        grant_type: 'authorization_code',
        authorization_url: 'https://idp/authorize',
        token_url: ' https://idp/token ',
        client_id: 'cid',
        client_secret: '',
        scope: '',
      })
      expect(p.oauth).toEqual({
        grant_type: 'authorization_code',
        authorization_url: 'https://idp/authorize',
        token_url: 'https://idp/token',
        client_id: 'cid',
      })
    })

    it('oauth 全空 → 载荷不带 oauth 键（后端归一化为空表，不写脏配置）', () => {
      const p = buildMCPRegisterPayload('x', 'https://a.b', undefined, {
        grant_type: '',
        token_url: '',
        client_id: '   ',
      })
      expect('oauth' in p).toBe(false)
    })

    it('未传 oauth 参数 → 与既有三参调用形态逐字一致（不扩契约）', () => {
      expect(buildMCPRegisterPayload('n', 'https://a.b', 'tok')).toEqual({
        name: 'n',
        url: 'https://a.b',
        transport: 'http',
        headers: { Authorization: 'Bearer tok' },
      })
    })
  })

  it('name/url 原样透传', () => {
    const p = buildMCPRegisterPayload('srv1', 'http://localhost:3000/mcp')
    expect(p.name).toBe('srv1')
    expect(p.url).toBe('http://localhost:3000/mcp')
  })
})
