/**
 * toTemplate 归一化测试（根因修复防回归）
 *
 * 后端 CollaborationTemplate（collaboration_api.py L40-49）字段是 snake_case
 * `template_id`，且**无** `type`；前端 CollabTemplate 期望 `id`/`type`。sessions 有
 * toSession 归一、templates 曾缺此步 → 向导模板卡片 tpl.id=undefined → 选中失效、
 * 两卡片同时高亮、canProceed 恒 false（第 1 步成死路）。此测试锁定 template_id→id 归一。
 */
import { describe, it, expect } from 'vitest'
import { toTemplate } from '@/api/modules/collaboration'

describe('toTemplate 归一化', () => {
  it('template_id → id，补 type 默认空串，透传 name/description/participants', () => {
    const t = toTemplate({
      template_id: 'project_734ec6b0a160',
      name: 'New Collaboration',
      description: '说明',
      participants: ['agent-a', 'agent-b'],
    })
    expect(t).toMatchObject({
      id: 'project_734ec6b0a160',
      name: 'New Collaboration',
      description: '说明',
      type: '',
      participants: ['agent-a', 'agent-b'],
    })
  })

  it('缺 participants / description → 安全默认（[] / 空串）', () => {
    const t = toTemplate({ template_id: 'x', name: 'y' })
    expect(t.id).toBe('x')
    expect(t.participants).toEqual([])
    expect(t.description).toBe('')
  })

  it('后端已带 type 时保留（前向兼容）', () => {
    const t = toTemplate({ template_id: 'x', name: 'y', type: 'pipeline' })
    expect(t.type).toBe('pipeline')
  })
})
