/**
 * 技能归档/回滚 API 封装（工单 011）。
 *
 * 钉的是"调用面把 agent 与操作者说清楚"：
 *  - 归档读面必须带 `agent_id`（不带会打到默认 agent 的技能库）；
 *  - 回滚必须带 `operator`（后端回滚留痕要记是谁按的，后端 422 拒空）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
const post = vi.fn()

vi.mock('@/api', () => ({
  default: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))

import { getSkillArchives, rollbackSkill } from '@/api/modules/governance'

describe('skill rollback api', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    get.mockResolvedValue({ data: { code: 0, data: { skill_id: 'sk_a', archives: [] } } })
    post.mockResolvedValue({ data: { code: 0, data: { rolled_back: true } } })
  })

  it('归档读面带 agent_id 查询串', async () => {
    await getSkillArchives('sk_a', 'kai')
    expect(get).toHaveBeenCalledWith('/governance/skills/sk_a/archives', {
      params: { agent_id: 'kai' },
    })
  })

  it('回滚带 operator 与 agent_id', async () => {
    await rollbackSkill('sk_a', 'admin1', 'kai')
    expect(post).toHaveBeenCalledWith('/governance/skills/sk_a/rollback', {
      operator: 'admin1',
      agent_id: 'kai',
    })
  })
})
