import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the api module before importing anything that depends on it
vi.mock('@/api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    post: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    put: vi.fn().mockResolvedValue({ code: 0, data: {} }),
    delete: vi.fn().mockResolvedValue({ code: 0, data: {} }),
  },
}))

import api from '@/api'
import * as skillPool from '@/api/modules/skill-pool'

const mockGet = vi.mocked(api.get)
const mockPost = vi.mocked(api.post)
const mockPut = vi.mocked(api.put)
const mockDelete = vi.mocked(api.delete)

beforeEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// 既有函数 — 验证 URL 对齐 ADR 0013 canonical 端点 (/skill-pool/* 与 /marketplace/*)
// ===========================================================================
describe('skill-pool API — 既有函数 URL 对齐', () => {
  it('getPublicSkills calls GET /marketplace/skills (catalog 同源; 功能页原走 /skill-pool/public 僵尸空字典)', async () => {
    await skillPool.getPublicSkills()
    expect(mockGet).toHaveBeenCalledWith('/marketplace/skills', {
      params: { limit: 100, offset: 0, with_total: true },
    })
  })

  it('listPublicLibrarySkills calls GET /skill-pool/public（三层库公共库真源，Wave H3 真人化）', async () => {
    await skillPool.listPublicLibrarySkills()
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/public')
  })

  it('listMySkills calls GET /skill-pool/me/skills（Wave V 用户私库页签）', async () => {
    await skillPool.listMySkills()
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/me/skills')
  })

  it('installSkill calls POST /marketplace/skills/{skillId}/install (canonical; 2026-09-09 修复: 原 /skill-pool/{id}/install 路由不存在恒 404)', async () => {
    await skillPool.installSkill('skill-1', 'agent-1')
    expect(mockPost).toHaveBeenCalledTimes(1)
    const [url, body] = mockPost.mock.calls[0]
    expect(String(url)).toBe('/marketplace/skills/skill-1/install')
    expect(body).toMatchObject({ agent_id: 'agent-1' })
  })

  it('installSkillFromUrl calls POST /skill-pool/install-from-url', async () => {
    await skillPool.installSkillFromUrl('https://github.com/x/skill')
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/install-from-url', {
      url: 'https://github.com/x/skill',
      version: undefined,
    })
  })

  it('installSkillFromZip calls POST /skill-pool/install-from-zip with FormData', async () => {
    const file = new File(['test'], 'skill.zip', { type: 'application/zip' })
    await skillPool.installSkillFromZip(file)
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/install-from-zip', expect.any(FormData), {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  })

  // --- 提交-审核三连(ADR 0013 canonical 前缀;后端曾只有 /v1/marketplace 版,404 断链) ---
  it('submitSkillForReview calls POST /skill-pool/skills/submit', async () => {
    await skillPool.submitSkillForReview({
      skill_id: 'my-tool',
      name: 'My Tool',
      version: '1.0.0',
      description: 'A community skill',
    })
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/skills/submit', {
      skill_id: 'my-tool',
      name: 'My Tool',
      version: '1.0.0',
      description: 'A community skill',
    })
  })

  it('listSkillSubmissions calls GET /skill-pool/skill-submissions with review_status param', async () => {
    await skillPool.listSkillSubmissions('pending')
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/skill-submissions', {
      params: { review_status: 'pending' },
    })
  })

  it('reviewSkillSubmission calls POST /skill-pool/skill-submissions/{id}/review', async () => {
    await skillPool.reviewSkillSubmission('subs_1', true, 'looks good')
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/skill-submissions/subs_1/review', {
      approve: true,
      note: 'looks good',
    })
  })
})

// ===========================================================================
// 新增函数 — TDD RED 阶段
// ===========================================================================
describe('skill-pool API — 新增函数', () => {
  // --- uninstallSkill ---
  it('uninstallSkill calls DELETE /marketplace/skills/{skillId}/install with agent_id (canonical; 原走 private/push 取消推送语义假成功不落盘)', async () => {
    await skillPool.uninstallSkill('skill-1', 'agent-1')
    expect(mockDelete).toHaveBeenCalledTimes(1)
    const [url, config] = mockDelete.mock.calls[0]
    expect(String(url)).toBe('/marketplace/skills/skill-1/install')
    expect(config).toMatchObject({ params: { agent_id: 'agent-1' } })
  })

  // --- getAgentSkills ---
  it('getAgentSkills calls GET /skill-pool/agent/{agentId}/skills', async () => {
    await skillPool.getAgentSkills('agent-1')
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/agent/agent-1/skills')
  })

  it('searchAgentDomainHarnesses calls GET /skill-pool/agent/{agentId}/domain-harnesses', async () => {
    await skillPool.searchAgentDomainHarnesses('agent-1', { query: '合同', domain: 'legal', limit: 5 })
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/agent/agent-1/domain-harnesses', {
      params: { query: '合同', domain: 'legal', limit: 5 },
    })
  })

  // --- enableSkill（V5 行级真通道 + agent 定库）---
  it('enableSkill calls PUT /skill-pool/private/{skillId} with agent_id + enabled 行级字段', async () => {
    await skillPool.enableSkill('skill-1', true, 'agent-1')
    expect(mockPut).toHaveBeenCalledWith('/skill-pool/private/skill-1', { enabled: true }, {
      params: { agent_id: 'agent-1' },
    })
  })

  // --- executeSkill ---
  it('executeSkill calls POST /skill-pool/private/{skillId}/execute', async () => {
    await skillPool.executeSkill('skill-1', 'agent-1', { query: 'hello' })
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/private/skill-1/execute', {
      agent_id: 'agent-1',
      arguments: { query: 'hello' },
    })
  })

  // --- Wave V 用户私库 CRUD ---
  it('createMySkill calls POST /skill-pool/me/skills', async () => {
    await skillPool.createMySkill({ name: 'n', description: 'd' })
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/me/skills', { name: 'n', description: 'd' })
  })

  it('updateMySkill calls PUT /skill-pool/me/skills/{id}', async () => {
    await skillPool.updateMySkill('m1', { name: 'n2' })
    expect(mockPut).toHaveBeenCalledWith('/skill-pool/me/skills/m1', { name: 'n2' })
  })

  it('deleteMySkill calls DELETE /skill-pool/me/skills/{id}', async () => {
    await skillPool.deleteMySkill('m1')
    expect(mockDelete).toHaveBeenCalledWith('/skill-pool/me/skills/m1')
  })

  it('installPublicToMine calls POST /skill-pool/me/skills/{id}/from-public（公共→我的私库副本+血缘）', async () => {
    await skillPool.installPublicToMine('p1')
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/me/skills/p1/from-public')
  })
})

// ===========================================================================
// P1-2 合并审批面 — URL 与后端 skill_pool_api 路由逐字对齐
// （后端端点先于前端存在，"后端有了没人调"是同一种断裂的反向形态）
// ===========================================================================
describe('skill-pool API — 技能合并审批面（P1-2）', () => {
  it('listConsolidationPlans calls GET /skill-pool/agent/{id}/consolidation/plans', async () => {
    await skillPool.listConsolidationPlans('agent-1')
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/agent/agent-1/consolidation/plans')
  })

  it('approveConsolidation calls POST .../{umbrella}/approve', async () => {
    await skillPool.approveConsolidation('agent-1', 'read_write_skill')
    expect(mockPost).toHaveBeenCalledWith(
      '/skill-pool/agent/agent-1/consolidation/read_write_skill/approve',
    )
  })

  it('rejectConsolidation calls POST .../{umbrella}/reject', async () => {
    await skillPool.rejectConsolidation('agent-1', 'read_write_skill')
    expect(mockPost).toHaveBeenCalledWith(
      '/skill-pool/agent/agent-1/consolidation/read_write_skill/reject',
    )
  })

  it('umbrella 名字含特殊字符时按路径段转义（后端按路径参数取件，不转义会串段）', async () => {
    await skillPool.approveConsolidation('agent-1', 'a/b c')
    expect(mockPost).toHaveBeenCalledWith(
      `/skill-pool/agent/agent-1/consolidation/${encodeURIComponent('a/b c')}/approve`,
    )
  })
})

// ===========================================================================
// 端点废弃守护 — 确保不再调用已 _DEPRECATED 的端点
// ===========================================================================
describe('skill-pool API — 废弃端点守护', () => {
  it('不应调用 /skills-market/* 端点', async () => {
    const source = await import('@/api/modules/skill-pool?raw').catch(() => null)
    if (source) {
      expect(source.default).not.toContain('/skills-market/')
    }
    // 即使无法 ?raw import，也验证函数调用不触发废弃端点
    await skillPool.getPublicSkills().catch(() => {})
    await skillPool.installSkill('s1', 'a1').catch(() => {})
    const calls = [...mockGet.mock.calls, ...mockPost.mock.calls]
    calls.forEach(([url]) => {
      expect(String(url)).not.toMatch(/\/skills-market\//)
    })
  })

  it('不应调用僵尸路由 POST /skill-pool/{id}/install（路由不存在恒 404；安装唯一正道是 /marketplace/skills/{id}/install）', async () => {
    await skillPool.installSkill('s1', 'a1').catch(() => {})
    const calls = [...mockGet.mock.calls, ...mockPost.mock.calls, ...mockDelete.mock.calls]
    calls.forEach(([url]) => {
      expect(String(url)).not.toMatch(/\/skill-pool\/[^/]+\/install$/)
    })
  })
})

// ===========================================================================
// 技能行主键归一（2026-10-24）
// 后端四个技能读面的行主键都叫 skill_id（marketplace.MarketplaceSkill /
// skill_pool_api.SkillInfo），前端消费方统一读 id。旧形态是各页自己重命名，
// AgentSkillPage 的市场导入漏了这一笔 ⇒ 装出来的 URL 是
// /marketplace/skills/undefined/install（真机 404）；同一形状还潜伏在
// AgentSchedulerPage 的技能下拉（取到 undefined，存下的调度任务指向不存在的技能）。
// 归一因此上收到 API 边界一处完成，本组判据钉的是「边界出口带 id」。
// ===========================================================================
describe('skill-pool API — skill_id→id 归一在边界一处完成', () => {
  it('市场读面 with_total 信封 {items:[{skill_id}]} 出口带 id，且原 skill_id 字段保留', async () => {
    mockGet.mockResolvedValueOnce({
      items: [{ skill_id: 'web-search', name: 'Web Search', description: '搜索' }],
      total: 1,
    } as any)
    const rows = await skillPool.getPublicSkills()
    expect(rows).toHaveLength(1)
    expect(rows[0].id).toBe('web-search')
    expect(rows[0].skill_id).toBe('web-search')
  })

  it('市场读面裸数组旧契约同样出口带 id', async () => {
    mockGet.mockResolvedValueOnce([{ skill_id: 'xfyun--ocr', name: 'OCR', description: '' }] as any)
    const rows = await skillPool.getPublicSkills()
    expect(rows[0].id).toBe('xfyun--ocr')
  })

  it('市场读面带 {code,data} 信封时先解信封再归一（拦截器之外的第二形态）', async () => {
    mockGet.mockResolvedValueOnce({ code: 0, data: [{ skill_id: 'a', name: 'A', description: '' }] } as any)
    const rows = await skillPool.getPublicSkills()
    expect(rows.map((s) => s.id)).toEqual(['a'])
  })

  it('公共库读面出口带 id', async () => {
    mockGet.mockResolvedValueOnce([{ skill_id: 'p1', name: '公共技能', description: '' }] as any)
    const rows = await skillPool.listPublicLibrarySkills()
    expect(rows[0].id).toBe('p1')
  })

  it('用户私库读面出口带 id', async () => {
    mockGet.mockResolvedValueOnce([{ skill_id: 'm1', name: '我的技能', description: '' }] as any)
    const rows = await skillPool.listMySkills()
    expect(rows[0].id).toBe('m1')
  })

  it('agent 技能读面出口带 id（SkillInfo 契约主键是 skill_id）', async () => {
    mockGet.mockResolvedValueOnce([{ skill_id: 'sk_a', name: 'synth_alpha', description: '' }] as any)
    const rows = await skillPool.getAgentSkills('agent-1')
    expect(rows[0].id).toBe('sk_a')
  })

  it('行本身已带 id 时不被 skill_id 缺省覆盖（后端不改契约的前提下两种都收）', async () => {
    mockGet.mockResolvedValueOnce([{ id: 'kept', name: 'X', description: '' }] as any)
    const rows = await skillPool.getAgentSkills('agent-1')
    expect(rows[0].id).toBe('kept')
  })
})
