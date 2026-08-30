/**
 * 画布店铺下拉纯函数测试 — TDD 红灯先行。
 *
 * 范围（§6.1）：
 * 1. storeOptionLabel：格式「店铺名（平台 · active）」；
 * 2. buildStoreSelectOptions：按平台过滤 + 排序；
 * 3. 空列表/未知平台返回空数组。
 */
import { describe, expect, it } from 'vitest'
import { buildStoreSelectOptions, storeOptionLabel, type StoreItem } from '../canvasStores'

const stores: StoreItem[] = [
  { store_id: 'store_1', platform: 'taobao', store_name: '淘宝A', status: 'active' },
  { store_id: 'store_2', platform: 'taobao', store_name: '淘宝B', status: 'error' },
  { store_id: 'store_3', platform: 'pdd', store_name: '拼多多A', status: 'active' },
  { store_id: 'store_4', platform: 'taobao', store_name: '淘宝C', status: 'pending' },
]

describe('storeOptionLabel', () => {
  it('格式化：店铺名（平台 · 状态）', () => {
    expect(storeOptionLabel(stores[0])).toBe('淘宝A（淘宝 · active）')
  })

  it('状态缺失时省略状态段', () => {
    expect(storeOptionLabel({ store_id: 'x', platform: 'taobao', store_name: '无名店' })).toBe('无名店（淘宝）')
  })
})

describe('buildStoreSelectOptions', () => {
  it('按平台过滤并输出 {label, value}', () => {
    const options = buildStoreSelectOptions(stores, 'taobao')
    expect(options).toHaveLength(3)
    expect(options[0]).toEqual({ label: '淘宝A（淘宝 · active）', value: 'store_1' })
    expect(options.map(o => o.value)).toContain('store_4')
  })

  it('不匹配平台返回空数组', () => {
    expect(buildStoreSelectOptions(stores, 'amazon')).toHaveLength(0)
    expect(buildStoreSelectOptions([], 'taobao')).toHaveLength(0)
  })

  it('平台为空（店铺授权节点）展示全部店铺', () => {
    const options = buildStoreSelectOptions(stores, '')
    expect(options).toHaveLength(4)
  })

  it('未知平台名时回退显示原始 platform 键', () => {
    const opts = buildStoreSelectOptions([{ store_id: 's1', platform: 'weird-platform', store_name: '怪店', status: 'active' }], 'weird-platform')
    expect(opts[0].label).toContain('weird-platform')
  })
})
