/**
 * buildDeptTreeData 契约测试 — 部门层级树构建器（单一事实源）
 *
 * 契约:
 *  1. title 为纯组名（成员数不拼进标题——展示形式由各视图自定，
 *     GroupPage 树视图用 #title 插槽渲染成员徽章，树选弹层显示纯名称）。
 *  2. 节点携带 membersCount 字段（members_count 缺省时为 undefined）。
 *  3. 系统组过滤、孤儿组归根层、excludeId 排除整棵子树（既有行为回钉）。
 */
import { describe, it, expect } from 'vitest'
import { buildDeptTreeData, type DeptGroupLike } from '../deptTree'

const groups: DeptGroupLike[] = [
  { group_id: 'g1', name: '市场组', members_count: 3, parent_group_id: null, is_system: false },
  { group_id: 'g2', name: '市场一部', members_count: 1, parent_group_id: 'g1', is_system: false },
  { group_id: 'g3', name: '研发组', parent_group_id: null, is_system: false },
  { group_id: 'g4', name: '管理员', is_system: true },
  { group_id: 'g5', name: '孤儿组', parent_group_id: 'g-deleted', is_system: false },
]

describe('buildDeptTreeData 部门层级树构建器', () => {
  it('title 为纯组名，成员数经 membersCount 字段携带', () => {
    const tree = buildDeptTreeData(groups)
    const market = tree.find(n => n.key === 'g1')!
    expect(market.title).toBe('市场组')
    expect(market.membersCount).toBe(3)
    const sub = market.children!.find(n => n.key === 'g2')!
    expect(sub.title).toBe('市场一部')
    expect(sub.membersCount).toBe(1)
  })

  it('members_count 缺省时 membersCount 为 undefined，title 不出现括号尾巴', () => {
    const tree = buildDeptTreeData(groups)
    const dev = tree.find(n => n.key === 'g3')!
    expect(dev.title).toBe('研发组')
    expect(dev.membersCount).toBeUndefined()
    expect(dev.title).not.toMatch(/\(/)
  })

  it('系统组不入树，孤儿组归根层（既有行为回钉）', () => {
    const tree = buildDeptTreeData(groups)
    expect(tree.find(n => n.key === 'g4')).toBeUndefined()
    expect(tree.find(n => n.key === 'g5')!.title).toBe('孤儿组')
  })

  it('excludeId 排除自身与整棵子树（既有行为回钉）', () => {
    const tree = buildDeptTreeData(groups, { excludeId: 'g1' })
    expect(tree.find(n => n.key === 'g1')).toBeUndefined()
    expect(tree.find(n => n.key === 'g2')).toBeUndefined()
    expect(tree.find(n => n.key === 'g3')).toBeDefined()
  })
})
