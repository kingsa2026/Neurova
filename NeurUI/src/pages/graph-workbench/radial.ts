/**
 * 2D 画布的放射（径向）布局：以根节点为圆心按 BFS 层级铺同心环，
 * 每个子树分到一段连续角度扇区——扇区互不重叠，从几何上保证
 * **树边（父→子的径向线段）互不交叉**；环边（非树边）不承诺无交叉。
 *
 * 根的选择由调用方定：有选中节点以选中为根（聚焦后图以它为圆心重铺），
 * 否则取度数最高的节点当枢纽。孤立连通分量各自成子放射，按分量叶子数
 * 切分整圆角度带、根半径错开，避免圆心叠点。
 */

export interface LayoutNode {
  id: string
  label: string
  type: string
}

export interface LayoutEdge {
  source: string
  target: string
}

export interface LayoutPoint {
  x: number
  y: number
}

/** 总半径归一：最大深度映射到固定半径，整图占地恒定 ~2800px——
 * fit 后 zoom 不随图深塌到不可辨认（曾实测节点缩到 30x8 『看起来空』）。 */
export const DEFAULT_TOTAL_RADIUS = 1400

interface TreeNode {
  parent: string | null
  depth: number
  children: string[]
}

function buildBfsTree(
  root: string,
  adjacency: Map<string, string[]>,
): { tree: Map<string, TreeNode>; nodes: string[] } {
  const tree = new Map<string, TreeNode>()
  const order: string[] = []
  tree.set(root, { parent: null, depth: 0, children: [] })
  order.push(root)
  const queue = [root]
  while (queue.length) {
    const u = queue.shift()!
    for (const v of adjacency.get(u) ?? []) {
      if (tree.has(v)) continue
      tree.set(v, { parent: u, depth: tree.get(u)!.depth + 1, children: [] })
      tree.get(u)!.children.push(v)
      order.push(v)
      queue.push(v)
    }
  }
  return { tree, nodes: order }
}

function leafCount(tree: Map<string, TreeNode>, u: string): number {
  const children = tree.get(u)!.children
  if (!children.length) return 1
  return children.reduce((sum, c) => sum + leafCount(tree, c), 0)
}

/** 单个连通分量的放射铺设：根在圆心，子树按叶子数权重切分角度区间。 */
function layoutComponent(
  root: string,
  tree: Map<string, TreeNode>,
  centerRadius: number,
  angleStart: number,
  angleEnd: number,
  maxDepth: number,
  totalRadius: number,
  positions: Map<string, LayoutPoint>,
): void {
  const assign = (u: string, a0: number, a1: number): void => {
    const depth = tree.get(u)!.depth
    // 半径按层深比例归一到总半径：深图不爆占地，浅图不挤成一团。
    const radius = centerRadius + (maxDepth > 0 ? (depth / maxDepth) * totalRadius : 0)
    const mid = (a0 + a1) / 2
    positions.set(u, { x: radius * Math.cos(mid), y: radius * Math.sin(mid) })
    const total = leafCount(tree, u)
    let cursor = a0
    for (const c of tree.get(u)!.children) {
      const w = (leafCount(tree, c) / total) * (a1 - a0)
      assign(c, cursor, cursor + w)
      cursor += w
    }
  }
  assign(root, angleStart, angleEnd)
}

export function radialLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  rootId?: string,
): Map<string, LayoutPoint> {
  const positions = new Map<string, LayoutPoint>()
  if (!nodes.length) return positions

  const adjacency = new Map<string, string[]>()
  const degree = new Map<string, number>()
  const nodeIds = new Set(nodes.map((n) => n.id))
  for (const id of nodeIds) {
    adjacency.set(id, [])
    degree.set(id, 0)
  }
  for (const e of edges) {
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target) || e.source === e.target) continue
    adjacency.get(e.source)!.push(e.target)
    adjacency.get(e.target)!.push(e.source)
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }

  // 根：优先调用方指定（选中/焦点），否则度数最高的枢纽；全孤立时取首个节点。
  let root = rootId && nodeIds.has(rootId) ? rootId : ''
  if (!root) {
    let best = -1
    for (const id of nodeIds) {
      const d = degree.get(id) ?? 0
      if (d > best) {
        best = d
        root = id
      }
    }
  }
  if (!root) root = nodes[0].id

  // 连通分量划分：主分量（含根）先铺，其余分量按大小降序切分剩余角度带。
  const visited = new Set<string>()
  const components: Array<{ root: string; tree: Map<string, TreeNode>; leaves: number }> = []
  for (const start of [root, ...nodeIds]) {
    if (visited.has(start) || !nodeIds.has(start)) continue
    const { tree } = buildBfsTree(start, adjacency)
    for (const id of tree.keys()) visited.add(id)
    let leaves = 0
    for (const id of tree.keys()) {
      if (!tree.get(id)!.children.length) leaves++
    }
    components.push({ root: start, tree, leaves: Math.max(leaves, 1) })
  }
  // 主分量（root 所在）排最前，其余按叶子数降序。
  components.sort((a, b) => {
    if (a.root === root) return -1
    if (b.root === root) return 1
    return b.leaves - a.leaves
  })

  let maxDepth = 0
  for (const comp of components) {
    for (const node of comp.tree.values()) {
      if (node.depth > maxDepth) maxDepth = node.depth
    }
  }

  const totalLeaves = components.reduce((sum, c) => sum + c.leaves, 0)
  let cursor = 0
  let componentIndex = 0
  for (const comp of components) {
    const span = (comp.leaves / totalLeaves) * Math.PI * 2
    // 非主分量的根统一放外环（半径封顶）：孤立分量可能多达几十个，
    // 根半径随序号线性增长会把包围盒撑到数万像素（实测 38710px）。
    const centerRadius = componentIndex === 0 ? 0 : DEFAULT_TOTAL_RADIUS * 1.25
    layoutComponent(
      comp.root, comp.tree, centerRadius,
      cursor, cursor + span, maxDepth, DEFAULT_TOTAL_RADIUS, positions)
    cursor += span
    componentIndex++
  }
  return positions
}
