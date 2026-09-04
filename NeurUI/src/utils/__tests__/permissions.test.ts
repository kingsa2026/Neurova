/**
 * 菜单可见性过滤工具测试
 *
 * 契约:
 *  1. admin / allowed_modules 为空数组 → 不限制（全部可见）——向后兼容存量用户。
 *  2. allowed_modules 非空 → 只有命中的模块可见；未在白名单里的路由一律隐藏。
 *  3. 动态路由前缀匹配：/agent/:id/memory 类模块，按前缀命中实际路由。
 */
import { describe, it, expect } from 'vitest'
import { canAccessModule, filterModules } from '@/utils/permissions'

describe('canAccessModule', () => {
  it('admin 恒可见', () => {
    expect(canAccessModule('/settings', { role: 'admin', allowed_modules: [] })).toBe(true)
    expect(canAccessModule('/settings', { role: 'admin', allowed_modules: ['/chat'] })).toBe(true)
  })

  it('allowed_modules 为空 = 不限制', () => {
    expect(canAccessModule('/aigc', { role: 'user', allowed_modules: [] })).toBe(true)
    expect(canAccessModule('/chat', { role: 'user', allowed_modules: [] })).toBe(true)
  })

  it('非空白名单：命中/未命中', () => {
    const allowed = ['/chat', '/agent/:id/memory', '/marketplace']
    expect(canAccessModule('/chat', { role: 'user', allowed_modules: allowed })).toBe(true)
    expect(canAccessModule('/agent/a1/memory', { role: 'user', allowed_modules: allowed })).toBe(true)
    expect(canAccessModule('/aigc', { role: 'user', allowed_modules: allowed })).toBe(false)
    expect(canAccessModule('/settings', { role: 'user', allowed_modules: allowed })).toBe(false)
  })

  it('agent 域子路由按前缀命中（/agent/:id/sleep 涵盖 sleep/settings）', () => {
    const allowed = ['/agent/:id/sleep']
    expect(canAccessModule('/agent/x1/sleep', { role: 'user', allowed_modules: allowed })).toBe(true)
    expect(canAccessModule('/agent/x1/sleep/settings', { role: 'user', allowed_modules: allowed })).toBe(true)
    expect(canAccessModule('/agent/x1/memory', { role: 'user', allowed_modules: allowed })).toBe(false)
  })

  it('allowed_modules 缺省（undefined，旧缓存用户）= 不限制', () => {
    expect(canAccessModule('/chat', { role: 'user', allowed_modules: undefined })).toBe(true)
  })
})

describe('filterModules', () => {
  it('过滤后仅保留命中模块，顺序不变', () => {
    const modules = ['/chat', '/agents', '/aigc', '/knowledge']
    const out = filterModules(modules, { role: 'user', allowed_modules: ['/chat', '/knowledge'] })
    expect(out).toEqual(['/chat', '/knowledge'])
  })

  it('空白名单不过滤', () => {
    const out = filterModules(['/chat', '/aigc'], { role: 'user', allowed_modules: [] })
    expect(out).toEqual(['/chat', '/aigc'])
  })
})
