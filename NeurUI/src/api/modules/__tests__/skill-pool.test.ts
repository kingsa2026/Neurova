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
// 既有函数 — 验证 URL 对齐 ADR 0013 canonical 端点 (/skill-pool/*)
// ===========================================================================
describe('skill-pool API — 既有函数 URL 对齐', () => {
  it('getPublicSkills calls GET /skill-pool/public', async () => {
    await skillPool.getPublicSkills()
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/public', { params: undefined })
  })

  it('getPrivateSkills calls GET /skill-pool/private with agent_id param', async () => {
    await skillPool.getPrivateSkills('agent-1')
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/private', { params: { agent_id: 'agent-1' } })
  })

  it('installSkill calls POST /skill-pool/{skillId}/install', async () => {
    await skillPool.installSkill('skill-1', 'agent-1')
    expect(mockPost).toHaveBeenCalledWith('/skill-pool/skill-1/install', { agent_id: 'agent-1' })
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
  it('uninstallSkill calls DELETE /skill-pool/private/{skillId}/push with agent_id', async () => {
    await skillPool.uninstallSkill('skill-1', 'agent-1')
    expect(mockDelete).toHaveBeenCalledWith('/skill-pool/private/skill-1/push', {
      params: { agent_id: 'agent-1' },
    })
  })

  // --- getAgentSkills ---
  it('getAgentSkills calls GET /skill-pool/agent/{agentId}/skills', async () => {
    await skillPool.getAgentSkills('agent-1')
    expect(mockGet).toHaveBeenCalledWith('/skill-pool/agent/agent-1/skills')
  })

  // --- enableSkill ---
  it('enableSkill calls PUT /skill-pool/private/{skillId} with config.enabled', async () => {
    await skillPool.enableSkill('skill-1', true)
    expect(mockPut).toHaveBeenCalledWith('/skill-pool/private/skill-1', {
      config: { enabled: true },
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
})

// ===========================================================================
// 端点废弃守护 — 确保不再调用已 _DEPRECATED 的端点
// ===========================================================================
describe('skill-pool API — 废弃端点守护', () => {
  it('不应调用 /skills-market/* 端点', async () => {
    const source = await import('@/api/modules/skill-pool?raw').catch(() => null)
    if (source) {
      expect(source.default).not.toContain('/skills-market/')
      expect(source.default).not.toContain('/marketplace/skills/')
    }
    // 即使无法 ?raw import，也验证函数调用不触发废弃端点
    await skillPool.getPublicSkills().catch(() => {})
    await skillPool.installSkill('s1', 'a1').catch(() => {})
    const calls = [...mockGet.mock.calls, ...mockPost.mock.calls]
    calls.forEach(([url]) => {
      expect(String(url)).not.toMatch(/\/skills-market\//)
      expect(String(url)).not.toMatch(/\/marketplace\/skills\//)
    })
  })
})
