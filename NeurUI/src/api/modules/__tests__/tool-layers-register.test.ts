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

  it('name/url 原样透传', () => {
    const p = buildMCPRegisterPayload('srv1', 'http://localhost:3000/mcp')
    expect(p.name).toBe('srv1')
    expect(p.url).toBe('http://localhost:3000/mcp')
  })
})
