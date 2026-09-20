import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
const post = vi.fn()

vi.mock('@/api', () => ({
  default: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
}))

import {
  getRsiStatus,
  listRsiProposals,
  approveRsiProposal,
  rejectRsiProposal,
} from '@/api/modules/rsiGovernance'

/**
 * RSI 治理 API 封装（工单 011）。
 *
 * 钉的是"前端有没有把 agent 说清楚"：三个动作都必须带上 `agent_id`，
 * 否则会打到"最后构造的那个 agent"（后端串写的另一半成因在前端）。
 * 批准还要能把 `tool_sequence` 递进去 —— manifest 缺可执行内容时
 * 后端按 not_supported 拒绝，前端没有补交口就等于这条通道走不通。
 */
describe('rsiGovernance api', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    get.mockResolvedValue({ data: { code: 0, data: {} } })
    post.mockResolvedValue({ data: { code: 0, data: {} } })
  })

  it('读状态时把 agent_id 放进查询串', async () => {
    await getRsiStatus('kai')
    expect(get).toHaveBeenCalledWith('/governance/rsi/status', { params: { agent_id: 'kai' } })
  })

  it('提案列表带 state 与 agent_id，且默认 all', async () => {
    await listRsiProposals({ agentId: 'kai' })
    expect(get).toHaveBeenCalledWith('/governance/rsi/proposals', {
      params: { state: 'all', agent_id: 'kai' },
    })
    await listRsiProposals({ state: 'applied', agentId: 'yi_ling' })
    expect(get).toHaveBeenLastCalledWith('/governance/rsi/proposals', {
      params: { state: 'applied', agent_id: 'yi_ling' },
    })
  })

  it('批准请求带 approver 与补交的 tool_sequence', async () => {
    await approveRsiProposal('prop-1', { approvedBy: 'admin', toolSequence: ['a', 'b'], agentId: 'kai' })
    expect(post).toHaveBeenCalledWith(
      '/governance/rsi/proposals/prop-1/approve',
      { approved_by: 'admin', tool_sequence: ['a', 'b'] },
      { params: { agent_id: 'kai' } },
    )
  })

  it('未补交序列时不写 tool_sequence 键（交给后端判 not_supported）', async () => {
    await approveRsiProposal('prop-2', { approvedBy: 'admin' })
    expect(post).toHaveBeenCalledWith(
      '/governance/rsi/proposals/prop-2/approve',
      { approved_by: 'admin' },
      { params: {} },
    )
  })

  it('驳回请求带原因与 agent_id', async () => {
    await rejectRsiProposal('prop-3', { reason: '方向不对', agentId: 'kai' })
    expect(post).toHaveBeenCalledWith(
      '/governance/rsi/proposals/prop-3/reject',
      { reason: '方向不对' },
      { params: { agent_id: 'kai' } },
    )
  })
})
