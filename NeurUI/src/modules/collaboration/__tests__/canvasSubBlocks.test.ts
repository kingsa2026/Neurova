/**
 * 画布 sub_block 条件可见性（联动显示）单元测试 — TDD 红灯先行。
 *
 * 背景：电商节点的平台参数需随「平台」下拉联动显示，
 * 如选择亚马逊才出现 MarketplaceId/SP-API 区域，选择淘宝则出现 num_iid 相关参数。
 * SubBlockConfig.condition 契约（models.py）：{field, operator, value}，
 * operator ∈ eq（默认）| neq | in。
 */
import { describe, it, expect } from 'vitest'
import {
  evalSubBlockCondition,
  filterVisibleSubBlocks,
  type SubBlockCondition,
  type SubBlockLike,
} from '../canvasSubBlocks'

const block = (id: string, condition?: SubBlockCondition | null): SubBlockLike => ({ id, condition })

describe('evalSubBlockCondition', () => {
  it('无条件时始终可见', () => {
    expect(evalSubBlockCondition(undefined, {})).toBe(true)
    expect(evalSubBlockCondition(null, { platform: 'amazon' })).toBe(true)
  })

  it('condition 缺少 field 时视为可见（fail-open，避免字段静默消失）', () => {
    expect(evalSubBlockCondition({ field: '', value: 'amazon' }, {})).toBe(true)
  })

  it('operator 缺省按 eq 处理', () => {
    const cond: SubBlockCondition = { field: 'platform', value: 'amazon' }
    expect(evalSubBlockCondition(cond, { platform: 'amazon' })).toBe(true)
    expect(evalSubBlockCondition(cond, { platform: 'taobao' })).toBe(false)
  })

  it('eq 匹配与不匹配', () => {
    const cond: SubBlockCondition = { field: 'platform', operator: 'eq', value: 'amazon' }
    expect(evalSubBlockCondition(cond, { platform: 'amazon' })).toBe(true)
    expect(evalSubBlockCondition(cond, { platform: 'jd' })).toBe(false)
  })

  it('neq 仅在值不相等时可见', () => {
    const cond: SubBlockCondition = { field: 'platform', operator: 'neq', value: 'amazon' }
    expect(evalSubBlockCondition(cond, { platform: 'taobao' })).toBe(true)
    expect(evalSubBlockCondition(cond, { platform: 'amazon' })).toBe(false)
  })

  it('in 按数组成员匹配', () => {
    const cond: SubBlockCondition = { field: 'platform', operator: 'in', value: ['ali1688', 'xianyu', 'shein'] }
    expect(evalSubBlockCondition(cond, { platform: 'xianyu' })).toBe(true)
    expect(evalSubBlockCondition(cond, { platform: 'amazon' })).toBe(false)
  })

  it('in 的 value 不是数组时按 eq 兜底', () => {
    const cond: SubBlockCondition = { field: 'platform', operator: 'in', value: 'amazon' }
    expect(evalSubBlockCondition(cond, { platform: 'amazon' })).toBe(true)
    expect(evalSubBlockCondition(cond, { platform: 'jd' })).toBe(false)
  })

  it('config 中缺少目标字段时条件块不可见', () => {
    const cond: SubBlockCondition = { field: 'platform', operator: 'eq', value: 'amazon' }
    expect(evalSubBlockCondition(cond, {})).toBe(false)
  })

  it('数字与字符串做宽松比较（slider 值 vs 字符串条件值）', () => {
    const cond: SubBlockCondition = { field: 'level', operator: 'eq', value: '3' }
    expect(evalSubBlockCondition(cond, { level: 3 })).toBe(true)
  })
})

describe('filterVisibleSubBlocks', () => {
  it('保持顺序且仅过滤条件不满足的块', () => {
    const blocks: SubBlockLike[] = [
      block('platform'),
      block('marketplace_id', { field: 'platform', operator: 'eq', value: 'amazon' }),
      block('alert_threshold'),
    ]
    const visible = filterVisibleSubBlocks(blocks, { platform: 'taobao' })
    expect(visible.map(b => b.id)).toEqual(['platform', 'alert_threshold'])
  })

  it('空列表返回空列表', () => {
    expect(filterVisibleSubBlocks([], { platform: 'amazon' })).toEqual([])
  })
})

describe('平台参数联动场景（同键多变体）', () => {
  // 同一 config 键（如 asin）按平台提供不同标题的变体块，
  // 任一平台下应恰好显示一个变体，且绑定同一键
  const variants: SubBlockLike[] = [
    { id: 'asin', title: '商品 ASIN', condition: { field: 'platform', operator: 'eq', value: 'amazon' } },
    { id: 'asin', title: '淘宝 num_iid', condition: { field: 'platform', operator: 'eq', value: 'taobao' } },
  ]

  it('选择亚马逊时仅显示 ASIN 变体', () => {
    const visible = filterVisibleSubBlocks(variants, { platform: 'amazon' })
    expect(visible).toHaveLength(1)
    expect(visible[0].title).toBe('商品 ASIN')
  })

  it('选择淘宝时仅显示 num_iid 变体', () => {
    const visible = filterVisibleSubBlocks(variants, { platform: 'taobao' })
    expect(visible).toHaveLength(1)
    expect(visible[0].title).toBe('淘宝 num_iid')
  })

  it('选择无变体的平台时该键不显示任何变体', () => {
    expect(filterVisibleSubBlocks(variants, { platform: 'jd' })).toHaveLength(0)
  })
})
