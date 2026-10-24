/**
 * 2D 画布的确定性布局（工作台）：按节点类型分列，列内按出现顺序均匀纵向分布。
 *
 * 2D 视图的语义是"结构化阅读"（与 3D 力导向的探索语义互补）：同一类型的节点
 * 同列、可预测的行列位置，点击/过滤/聚焦时图不会跳动。不引入 d3 依赖——
 * 分列布局几十行就够，力导向留给 3D 探索器。
 */

export interface LayoutNode {
  id: string
  label: string
  type: string
}

export interface LayoutPoint {
  x: number
  y: number
}

/** 列宽/行高的缺省尺：够放默认节点卡片，且列间距可读。 */
export const DEFAULT_COL_WIDTH = 240
export const DEFAULT_ROW_HEIGHT = 90

export function layeredLayout(
  nodes: LayoutNode[],
  colWidth: number = DEFAULT_COL_WIDTH,
  rowHeight: number = DEFAULT_ROW_HEIGHT,
): Map<string, LayoutPoint> {
  const positions = new Map<string, LayoutPoint>()
  // 类型桶按首次出现顺序排列——同一份数据每次布局结果相同（确定性）。
  const buckets = new Map<string, string[]>()
  for (const node of nodes) {
    const kind = node.type || 'other'
    if (!buckets.has(kind)) buckets.set(kind, [])
    buckets.get(kind)!.push(node.id)
  }
  let colIndex = 0
  for (const kind of buckets.keys()) {
    const ids = buckets.get(kind)!
    for (let i = 0; i < ids.length; i++) {
      positions.set(ids[i], { x: colIndex * colWidth, y: i * rowHeight })
    }
    colIndex++
  }
  return positions
}
