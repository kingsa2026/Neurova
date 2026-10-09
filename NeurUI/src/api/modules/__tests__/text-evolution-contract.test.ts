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
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

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
    await evolution.abCompareSkills('kai', { skill_id: 's1', candidate_text: '新正文' })
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

  it('abCompareSkills → POST /evolution/skills/{agentId}/ab', async () => {
    await evolution.abCompareSkills('kai', { skill_id: 's1', candidate_text: '新正文' })
    expect(apiMock.post).toHaveBeenCalledWith(
      '/evolution/skills/kai/ab',
      { skill_id: 's1', candidate_text: '新正文' },
    )
  })

  it('真臂必须显式带 real_trajectory；不带时不得被当成真轨迹面', async () => {
    await evolution.abCompareSkills('kai', {
      skill_id: 's1', candidate_text: '新正文', real_trajectory: true,
    })
    const realBody = apiMock.post.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(realBody.real_trajectory).toBe(true)

    await evolution.abCompareSkills('kai', { skill_id: 's1', candidate_text: '新正文' })
    const plainBody = apiMock.post.mock.calls.at(-1)?.[1] as Record<string, unknown>
    expect(plainBody.real_trajectory).toBeUndefined()
  })
})

/**
 * 审计运行三态的拼写在两个事实源之间不得漂移（§6-95 后半）。
 *
 * 后端 `SkillEvolutionService.runLookup` 出 `attached | missing | none_recorded`，
 * 前端 `AuditRunState` 与页面 `auditRunNote` 按同样的字面量分派文案。任何一侧改名或
 * 加一档，页面就会把未知状态读成"没有那句话"——静默省略恰是这一裁要避免的形态，
 * 所以把它钉成逐字比对，而不是靠"看起来都是那三个词"。
 */
describe('审计运行三态跨语言同形', () => {
  const readRepoText = (relFromRoot: string, up: number): string =>
    readFileSync(resolve(process.cwd(), ...Array(up).fill('..'), relFromRoot), 'utf-8')
      .replace(/\r\n/g, '\n')

  const backend = readRepoText('neurova/evolution/eval/service.py', 1)
  const frontend = readRepoText('src/api/modules/text-evolution.ts', 0)

  function backendStates(): string[] {
    const start = backend.indexOf('def runLookup(')
    expect(start, '后端 runLookup 消失或改名——前端那侧的三态此刻无人出').toBeGreaterThan(-1)
    const end = backend.indexOf('\n    def ', start + 1)
    const segment = backend.slice(start, end === -1 ? undefined : end)
    return [...segment.matchAll(/'(attached|missing|none_recorded)'/g),
      ...segment.matchAll(/"(attached|missing|none_recorded)"/g)].map((m) => m[1])
  }

  function frontendStates(): string[] {
    const line = frontend.match(/^export type AuditRunState = (.+)$/m)
    expect(line, '前端 AuditRunState 消失——详情面对三态不再分派').not.toBeNull()
    return [...line![1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1])
  }

  it('两侧的状态集合逐字相等（多一档、少一档、改名都判红）', () => {
    const fromBackend = [...new Set(backendStates())].sort()
    const fromFrontend = [...new Set(frontendStates())].sort()
    expect(fromBackend).toEqual(['attached', 'missing', 'none_recorded'])
    expect(fromFrontend).toEqual(fromBackend)
  })

  it('检出器不是空转：状态漂移必须被抓到', () => {
    const drifted = frontend.replace(
      "export type AuditRunState = 'attached' | 'missing' | 'none_recorded'",
      "export type AuditRunState = 'attached' | 'gone'",
    )
    const line = drifted.match(/^export type AuditRunState = (.+)$/m)
    expect(line).not.toBeNull()
    const states = [...line![1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1]).sort()
    expect(states).not.toEqual([...new Set(backendStates())].sort())
  })

  it('前端读的运行字段名，生产写侧必须真的写出来', () => {
    /**
     * `EvolutionRunResult` 的 dataclass 字段名与它 `to_dict()` 的线上键名**不同形**：
     * `holdout_case_scores`（字段）→ `holdout_cases`（线上）。判据/面板按字段名读，
     * 就会读一个不存在的键而测试照样绿——本格把"按线上名读"钉住。
     */
    const runner = readRepoText('neurova/evolution/eval/runner.py', 1)
    const start = runner.indexOf('def to_dict(self) -> dict:')
    expect(start, 'runner 的 to_dict 消失或改名——字段名比对失去靶点').toBeGreaterThan(-1)
    const segment = runner.slice(start, runner.indexOf('\n    def ', start + 1))
    const wireKeys = new Set(
      [...segment.matchAll(/"([a-z_]+)":/g)].map((m) => m[1]),
    )

    const block = frontend.match(/export interface EvolutionRunAudit \{([\s\S]*?)\n\}/)
    expect(block, '前端 EvolutionRunAudit 消失——详情面对运行不再分派').not.toBeNull()
    const readFields = [...block![1].matchAll(/^ {2}([a-z_]+):/gm)].map((m) => m[1])
    expect(readFields.length, '字段检出器零命中——本格会空转').toBeGreaterThan(0)

    // `at` / `run_id` / `skill_id` / `artifact_type` 由 `_persist_run` 落盘时补，
    // 不在 to_dict 里；其余必须是 to_dict 的线上键。
    const addedByPersist = ['at', 'run_id', 'skill_id', 'artifact_type']
    const missing = readFields.filter(
      (field) => !addedByPersist.includes(field) && !wireKeys.has(field))
    expect(missing, `前端在读生产写侧不存在的键: ${missing.join(', ')}`).toEqual([])
    expect(wireKeys.has('holdout_cases'), '留出侧逐例读数的线上键名变了——面板会永远空着')
      .toBe(true)
  })
})
