/**
 * 审批裁决「记忆放行」识别器（D1 记忆式批准的展示层读数）单元测试。
 *
 * 契约（与后端 neurova/agent/approval_chain.py 对齐）：
 * 1. 显式 decision_source="memory_grant" → 命中（grant_id 取显式字段，
 *    缺失时回落 decided_by 标记尾段）；
 * 2. 现行审计投影（GET /audit/approvals、项目档案 approvals）不带
 *    decision_source，但裁决人记为 "memory_grant:<grant_id>"（写入点
 *    requestRunApproval 的 decidedBy 拼装）→ 前缀命中并提取编号；
 * 3. 两者皆无（普通链路裁决 / 旧数据）→ null，调用面不渲染徽标。
 */
import { describe, expect, it } from 'vitest'
import { memoryGrantOf, memoryGrantTitleOf, MEMORY_GRANT_SOURCE } from '../approvalGrant'

describe('memoryGrantOf — 记忆放行识别', () => {
  it('decision_source=memory_grant 显式命中，grant_id 取显式字段', () => {
    expect(memoryGrantOf({ decision_source: 'memory_grant', grant_id: 'g-123' })).toEqual({
      grantId: 'g-123',
    })
  })

  it('decision_source 命中但缺 grant_id 时回落 decided_by 尾段', () => {
    expect(
      memoryGrantOf({ decision_source: 'memory_grant', decided_by: 'memory_grant:g-777' }),
    ).toEqual({ grantId: 'g-777' })
  })

  it('审计面现行形状：仅 decided_by 带 memory_grant: 前缀也命中', () => {
    expect(memoryGrantOf({ decided_by: 'memory_grant:grant_ab12cd34' })).toEqual({
      grantId: 'grant_ab12cd34',
    })
  })

  it('普通链路裁决（chain/人工）不命中', () => {
    expect(memoryGrantOf({ decision_source: 'chain', decided_by: 'user_admin' })).toBeNull()
    expect(memoryGrantOf({ decided_by: 'auto_rule:L0' })).toBeNull()
    expect(memoryGrantOf({ decided_by: 'room:user_1' })).toBeNull()
  })

  it('decided_by 含 memory_grant 字样但无冒号编号不算命中（防误报）', () => {
    expect(memoryGrantOf({ decided_by: 'memory_grant' })).toBeNull()
    expect(memoryGrantOf({ decided_by: 'memory_grant:' })).toBeNull()
  })

  it('空/缺字段记录返回 null（向后兼容：旧数据不渲染徽标）', () => {
    expect(memoryGrantOf(null)).toBeNull()
    expect(memoryGrantOf(undefined)).toBeNull()
    expect(memoryGrantOf({})).toBeNull()
    expect(memoryGrantOf({ decided_by: '' })).toBeNull()
  })

  it('标记常量与后端 GRANT_SOURCE_MARKER 同词值', () => {
    expect(MEMORY_GRANT_SOURCE).toBe('memory_grant')
  })
})

describe('memoryGrantTitleOf — 徽标 title 文案（t 注入）', () => {
  const t = (key: string, params?: Record<string, unknown>) =>
    params && 'id' in params ? `${key}:${params.id}` : key

  it('带授权单编号时 title 提示编号', () => {
    expect(memoryGrantTitleOf({ decided_by: 'memory_grant:g-9' }, t)).toBe(
      'audit.memoryGrantTitle:g-9',
    )
  })

  it('无编号（仅 decision_source 命中）退回徽标文案', () => {
    expect(memoryGrantTitleOf({ decision_source: 'memory_grant' }, t)).toBe('audit.memoryGrantBadge')
  })

  it('未命中返回空串（不渲染徽标也不出 title）', () => {
    expect(memoryGrantTitleOf({ decided_by: 'user_1' }, t)).toBe('')
    expect(memoryGrantTitleOf(null, t)).toBe('')
  })
})
