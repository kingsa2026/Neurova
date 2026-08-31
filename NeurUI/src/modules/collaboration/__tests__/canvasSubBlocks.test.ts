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

describe('知识库节点 kb_type 联动（R-9）', () => {
  // 镜像后端 builtin.py knowledge_base sub_blocks 的 condition
  const kbBlocks: SubBlockLike[] = [
    { id: 'query', condition: null },
    { id: 'limit', condition: null },
    { id: 'kb_config_id', condition: { field: 'kb_type', operator: 'neq', value: 'local' } },
    { id: 'api_url', condition: { field: 'kb_type', operator: 'eq', value: 'custom' } },
    { id: 'api_key', condition: { field: 'kb_type', operator: 'eq', value: 'custom' } },
    { id: 'dataset_id', condition: { field: 'kb_type', operator: 'eq', value: 'custom' } },
    { id: 'app_id', condition: { field: 'kb_type', operator: 'eq', value: 'feishu' } },
    { id: 'app_secret', condition: { field: 'kb_type', operator: 'eq', value: 'feishu' } },
    { id: 'space_id', condition: { field: 'kb_type', operator: 'eq', value: 'feishu' } },
    { id: 'base_url', condition: { field: 'kb_type', operator: 'in', value: ['iflow', 'ima'] } },
    { id: 'allow_local', condition: { field: 'kb_type', operator: 'eq', value: 'ima' } },
  ]

  const visibleIds = (kbType: string) =>
    filterVisibleSubBlocks(kbBlocks, { kb_type: kbType }).map((b) => b.id)

  it('local 只显示通用字段（无远程配置）', () => {
    expect(visibleIds('local')).toEqual(['query', 'limit'])
  })

  it('iflow 显示 query/limit/config/base_url（无 custom/feishu/ima 专属）', () => {
    const ids = visibleIds('iflow')
    expect(ids).toContain('kb_config_id')
    expect(ids).toContain('base_url')
    expect(ids).not.toContain('api_url')
    expect(ids).not.toContain('app_id')
    expect(ids).not.toContain('allow_local')
  })

  it('feishu 显示 app_id/app_secret/space_id 专属', () => {
    const ids = visibleIds('feishu')
    expect(ids).toContain('app_id')
    expect(ids).toContain('app_secret')
    expect(ids).toContain('space_id')
    expect(ids).not.toContain('api_url')
    expect(ids).not.toContain('allow_local')
  })

  it('ima 显示 base_url + allow_local', () => {
    const ids = visibleIds('ima')
    expect(ids).toContain('base_url')
    expect(ids).toContain('allow_local')
    expect(ids).not.toContain('app_secret')
  })

  it('custom 显示 api_url/api_key/dataset_id 专属', () => {
    const ids = visibleIds('custom')
    expect(ids).toContain('api_url')
    expect(ids).toContain('api_key')
    expect(ids).toContain('dataset_id')
    expect(ids).not.toContain('app_id')
    expect(ids).not.toContain('base_url')
  })
})
