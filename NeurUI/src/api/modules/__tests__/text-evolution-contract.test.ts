/**
 * text-evolution API 模块契约测试（2026-09-16 技能页 usage 404 根因修复）
 *
 * 根因：api/index.ts 的 axios baseURL 已是 config.apiBaseUrl='/api/v1'，
 * 全库 50+ 模块的 BASE 一律写 '/xxx'（base 补 /api/v1 → /api/v1/xxx）。
 * text-evolution.ts 却写 BASE='/v1/evolution'，拼出 /api/v1/v1/evolution/...
 * 双重 /v1 → 后端 text_evolution_api 挂在 /api/v1/evolution（register_endpoint_routers
 * 用 '/api' + '/v1/evolution'），故恒 404。
 *
 * 本测试钉死：所有请求路径以 '/evolution' 开头且不含 '/v1'，
 * 与后端 @router 路由逐条对齐。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn().mockResolvedValue({ data: {} }),
  post: vi.fn().mockResolvedValue({ data: {} }),
  put: vi.fn().mockResolvedValue({ data: {} }),
}))

vi.mock('@/api', () => ({ default: apiMock }))

import * as evolution from '../text-evolution'

/** 取最近一次调用发出的路径（get/post/put 第一参） */
function lastPath(): string {
  const call = apiMock.get.mock.calls.at(-1) ?? apiMock.post.mock.calls.at(-1) ?? apiMock.put.mock.calls.at(-1)
  return String(call?.[0])
}

describe('text-evolution 模块 HTTP 契约（路径不得含 /v1 前缀）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.get.mockResolvedValue({ data: {} })
    apiMock.post.mockResolvedValue({ data: {} })
    apiMock.put.mockResolvedValue({ data: {} })
  })

  it('getEvolutionSettings → GET /evolution/settings', async () => {
    await evolution.getEvolutionSettings()
    expect(lastPath()).toBe('/evolution/settings')
  })

  it('updateEvolutionSettings → PUT /evolution/settings', async () => {
    await evolution.updateEvolutionSettings({ text_evolution: true })
    expect(apiMock.put).toHaveBeenCalledWith('/evolution/settings', { text_evolution: true })
  })

  it('getLifecycleUsage → GET /evolution/skills/{agentId}/usage（回归：曾拼成 /v1/v1/... 404）', async () => {
    await evolution.getLifecycleUsage('kai')
    expect(lastPath()).toBe('/evolution/skills/kai/usage')
  })

  it('runLifecycleSweep → POST /evolution/skills/{agentId}/sweep', async () => {
    await evolution.runLifecycleSweep('kai')
    expect(lastPath()).toBe('/evolution/skills/kai/sweep')
  })

  it('pinSkill → POST /evolution/skills/{agentId}/{skillId}/pin，body {pinned}', async () => {
    await evolution.pinSkill('kai', 's1', true)
    expect(apiMock.post).toHaveBeenCalledWith('/evolution/skills/kai/s1/pin', { pinned: true })
  })

  it('evolveSkill → POST /evolution/skills/{agentId}/evolve', async () => {
    await evolution.evolveSkill('kai', { skill_id: 's1', iterations: 3 })
    expect(apiMock.post).toHaveBeenCalledWith('/evolution/skills/kai/evolve', { skill_id: 's1', iterations: 3 })
  })

  it('listProposals → GET /evolution/skills/{agentId}/proposals（status 走 params）', async () => {
    await evolution.listProposals('kai', 'pending')
    expect(apiMock.get).toHaveBeenCalledWith('/evolution/skills/kai/proposals', { params: { status: 'pending' } })
  })

  it('getProposal → GET /evolution/skills/{agentId}/proposals/{id}', async () => {
    await evolution.getProposal('kai', 'p1')
    expect(lastPath()).toBe('/evolution/skills/kai/proposals/p1')
  })

  it('approveProposal → POST /evolution/skills/{agentId}/proposals/{id}/approve', async () => {
    await evolution.approveProposal('kai', 'p1')
    expect(lastPath()).toBe('/evolution/skills/kai/proposals/p1/approve')
  })

  it('rejectProposal → POST /evolution/skills/{agentId}/proposals/{id}/reject', async () => {
    await evolution.rejectProposal('kai', 'p1')
    expect(lastPath()).toBe('/evolution/skills/kai/proposals/p1/reject')
  })

  it('全量守卫：任一请求路径都不得出现 /v1（base 已含 /api/v1）', async () => {
    await evolution.getEvolutionSettings()
    await evolution.getLifecycleUsage('kai')
    await evolution.runLifecycleSweep('kai')
    await evolution.pinSkill('kai', 's1', false)
    await evolution.evolveSkill('kai', { skill_id: 's1' })
    await evolution.listProposals('kai')
    await evolution.getProposal('kai', 'p1')
    await evolution.approveProposal('kai', 'p1')
    await evolution.rejectProposal('kai', 'p1')
    const paths = [
      ...apiMock.get.mock.calls,
      ...apiMock.post.mock.calls,
      ...apiMock.put.mock.calls,
    ].map((c) => String(c[0]))
    expect(paths.length).toBeGreaterThan(0)
    for (const p of paths) {
      expect(p).toMatch(/^\/evolution/)
      expect(p).not.toContain('/v1')
    }
  })
})
