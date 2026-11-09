// ---------------------------------------------------------------------------
// 部门分组层级树构建（specs/2026-11-07 批 F：parent_group_id 驱动的单亲树）
//
// 单一事实源：GroupPage 层级视图/父组树选、EnhancedUserPage 与 AgentFormPage
// 的分组树选共用本构建器——三页各抄一份会同时触发 duplicate-function 守卫
// 与教义第 6 条。环安全：孤儿组（父组缺失/成环）如实归入根层，不丢不炸。
// ---------------------------------------------------------------------------

export interface DeptGroupLike {
  group_id: string
  name: string
  members_count?: number
  parent_group_id?: string | null
  is_system?: boolean
}

export interface DeptTreeNode {
  title: string
  /** a-tree-select 的取值；a-tree 忽略该字段无副作用 */
  value: string
  key: string
  /** 成员数（members_count 缺省时为 undefined）；树视图插槽据此渲染徽章 */
  membersCount?: number
  /** 组节点 id；行内操作（成员/改名/编辑/删除）据此渲染与定位 */
  groupId?: string
  isSystem?: boolean
  children?: DeptTreeNode[]
}

export interface BuildDeptTreeOptions {
  /** 排除该组及其整棵子树（父组选择防自指/防环） */
  excludeId?: string
}

export function buildDeptTreeData(
  groups: DeptGroupLike[],
  opts?: BuildDeptTreeOptions,
): DeptTreeNode[] {
  const excluded = new Set<string>()
  if (opts?.excludeId) {
    // 排除自身并沿 parent 链向下收编整棵子树（迭代到不动点，环安全）
    excluded.add(opts.excludeId)
    let grew = true
    while (grew) {
      grew = false
      for (const g of groups) {
        if (g.parent_group_id && excluded.has(g.parent_group_id) && !excluded.has(g.group_id)) {
          excluded.add(g.group_id)
          grew = true
        }
      }
    }
  }

  const deptGroups = groups.filter((g) => !g.is_system && !excluded.has(g.group_id))
  const known = new Set(deptGroups.map((g) => g.group_id))

  const build = (parentId: string | null): DeptTreeNode[] => {
    const children = deptGroups.filter(
      (g) => (g.parent_group_id && known.has(g.parent_group_id) ? g.parent_group_id : null) === parentId,
    )
    return children.map((g) => ({
      title: g.name,
      value: g.group_id,
      key: g.group_id,
      membersCount: g.members_count,
      groupId: g.group_id,
      isSystem: !!g.is_system,
      children: build(g.group_id),
    }))
  }

  const tree = build(null)
  // 孤儿组（parent 指向已删组/成环不可达）：归入根层，不丢组
  const reachable = new Set<string>()
  const walk = (nodes: DeptTreeNode[]) => {
    for (const n of nodes) {
      reachable.add(n.key)
      if (n.children) walk(n.children)
    }
  }
  walk(tree)
  for (const g of deptGroups) {
    if (!reachable.has(g.group_id)) {
      tree.push({ title: g.name, value: g.group_id, key: g.group_id, membersCount: g.members_count, groupId: g.group_id, isSystem: !!g.is_system })
    }
  }
  return tree
}
