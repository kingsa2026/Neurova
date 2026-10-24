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
/** 同层相邻节点的最小弧长（px）：卡片宽 96 + 间距，低于它就视觉重叠。 */
export const DEFAULT_MIN_ARC = 120
/** 每层子环数：同层节点分内/外两个子环交错排布，圆周容量翻倍、占地减半。 */
export const RINGS_PER_LAYER = 2
/** 子环间距：卡片高 40 + 间隙，径向不叠。 */
export const RING_INNER_GAP = 55

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
  // 层内节点按 BFS 序收集（组内保持父序——层间序一致，树边交叉最少）。
  const layers: string[][] = []
  for (const [id, node] of tree) {
    if (id === root) continue
    ;(layers[node.depth] ??= []).push(id)
  }
  // 半径逐层递推：层深比例打底，但必须 ≥ 圆周容量（同层 N 个节点分
  // RINGS_PER_LAYER 个子环交错排布，每个子环弧长 ≥ MIN_ARC）且 ≥
  // 前层 + 子环跨度（相邻层不贴脸）。
  const radii: number[] = [0]
  for (let d = 1; d <= maxDepth; d++) {
    const count = layers[d]?.length ?? 0
    const perRing = Math.ceil(count / RINGS_PER_LAYER)
    const capacity = perRing > 0 ? (perRing * DEFAULT_MIN_ARC) / Math.PI : 0
    radii[d] = Math.max(
      centerRadius + (maxDepth > 0 ? (d / maxDepth) * totalRadius : 0),
      capacity,
      radii[d - 1] + RINGS_PER_LAYER * RING_INNER_GAP)
  }
  // 根在圆心；每层节点分双子环交错排布（内环偶数位、外环奇数位，
  // 层内序保持——相邻子环节点角度错开半个步长）。
  positions.set(root, { x: centerRadius, y: centerRadius })
  for (let d = 1; d <= maxDepth; d++) {
    const ids = layers[d]
    if (!ids) continue
    const perRing = Math.ceil(ids.length / RINGS_PER_LAYER)
    const baseRadius = centerRadius + radii[d]
    ids.forEach((id, i) => {
      // 角度按层内全局序连续分配（不按子环重置 slot）——序即角度序，
      // 父子块的方向一致性才保得住；只有半径按奇偶分子环。
      const mid = angleStart + ((i + 0.5) / ids.length) * (angleEnd - angleStart)
      const radius = baseRadius + (i % 2) * RING_INNER_GAP
      positions.set(id, { x: radius * Math.cos(mid), y: radius * Math.sin(mid) })
    })
  }
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

  // 小分量保底角宽：碎片分量（2-5 节点）按叶权只能分到极窄扇区，
  // 分量内部节点几乎同点（重叠重灾区）。每个分量至少 MIN_SPAN，
  // 被挤占的角度从大分量按权重扣回。
  const MIN_SPAN = (Math.PI * 2) / 60
  const totalLeaves = components.reduce((sum, c) => sum + c.leaves, 0)
  const spans = components.map((c) => (c.leaves / totalLeaves) * Math.PI * 2)
  let deficit = 0
  let bigWeight = 0
  spans.forEach((span, i) => {
    if (span < MIN_SPAN) {
      deficit += MIN_SPAN - span
      spans[i] = MIN_SPAN
    } else {
      bigWeight += compWeight(i)
    }
  })
  function compWeight(i: number): number {
    return components[i].leaves
  }
  spans.forEach((span, i) => {
    if (span > MIN_SPAN) spans[i] = span - (deficit * compWeight(i)) / (bigWeight || 1)
  })
  let cursor = 0
  let componentIndex = 0
  for (const comp of components) {
    const span = spans[componentIndex]
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
