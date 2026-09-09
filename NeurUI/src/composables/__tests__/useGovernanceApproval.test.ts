/**
 * useGovernanceApproval — 事件路径上下文回归测试（2026-09-09）。
 *
 * 根因（ChatPage 拆分 54478927 引入）：confirmApproval/rejectApproval 挂在
 * GovernanceApprovalModal 的 @ok/@cancel 上（事件处理器，无组件实例），
 * 拆分迁移时把 useI18n() 写进函数体——vue-i18n 在 getCurrentInstance() 为
 * null 时抛 "Must be called at the top of a setup function"，批准/拒绝
 * 点击毫无反应（loading 未置、弹窗不关）。
 *
 * 契约：confirm/reject 必须可在组件上下文之外调用；文案取 i18n.global.t。
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'

const { approveRequest, rejectRequest, addWhitelistEntry } = vi.hoisted(() => ({
  approveRequest: vi.fn(),
  rejectRequest: vi.fn(),
  addWhitelistEntry: vi.fn(),
}))

vi.mock('@/api', () => ({ api: {} }))
vi.mock('@/api/modules/governance', () => ({
  approveRequest,
  rejectRequest,
  addWhitelistEntry,
}))

import { useGovernanceApproval } from '../useGovernanceApproval'

describe('useGovernanceApproval — 动作函数脱离组件上下文可调用', () => {
  beforeEach(() => {
    approveRequest.mockReset()
    rejectRequest.mockReset()
    addWhitelistEntry.mockReset()
    const { approvalModal, approvalRemember } = useGovernanceApproval()
    approvalModal.open = false
    approvalModal.loading = false
    approvalModal.approvalId = ''
    approvalRemember.value = ''
  })

  it('confirmApproval 在事件处理器上下文外调用不抛异常且完成审批', async () => {
    const m = useGovernanceApproval()
    m.approvalModal.approvalId = 'apr-1'
    approveRequest.mockResolvedValue({ data: { executed: false, result: null } })

    await expect(m.confirmApproval()).resolves.toBeUndefined()

    expect(approveRequest).toHaveBeenCalledWith('apr-1', expect.any(String), undefined)
    expect(m.approvalModal.open).toBe(false)
    expect(m.approvalModal.loading).toBe(false)
  })

  it('rejectApproval 在事件处理器上下文外调用完成拒绝', async () => {
    const m = useGovernanceApproval()
    m.approvalModal.approvalId = 'apr-2'
    rejectRequest.mockResolvedValue({})

    await expect(m.rejectApproval()).resolves.toBeUndefined()

    expect(rejectRequest).toHaveBeenCalledWith('apr-2', expect.any(String))
    expect(m.approvalModal.open).toBe(false)
  })

  it('勾选白名单时 confirmApproval 先入免检列表', async () => {
    const m = useGovernanceApproval()
    m.approvalModal.approvalId = 'apr-3'
    m.approvalModal.command = 'python script.py --flag'
    m.approvalAddWhitelist.value = true
    approveRequest.mockResolvedValue({ data: {} })

    await m.confirmApproval()

    expect(addWhitelistEntry).toHaveBeenCalledWith({
      pattern: 'python',
      match_type: 'prefix',
      note: expect.any(String),
    })
  })
})
