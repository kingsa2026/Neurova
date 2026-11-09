/**
 * 2D 画布的力导向布局（d3-force-3d 两维模拟），替代树式放射布局。
 *
 * 为什么换：真实图谱是多父稠密图，放射布局只对 BFS 树边承诺零交叉——
 * 非树边（跨子树/环边）大量交错，且层内等分角让密集扇区节点挤压重叠
 * （全图态 209 节点实测扎堆 + 交线成网）。力导向以物理松弛对齐用户的
 * 四点诉求：
 *  - collide 硬防重叠（成对屏幕距离 ≥ 碰撞直径，几何保证）；
 *  - manyBody 斥力 + 轻质心拉力 → 节点间距均匀、包围盒有界；
 *  - link 弹簧（距离均一、强度按度数反比）→ 边短而匀，交叉局部最小化；
 *  - 聚焦语义保留：选中/枢纽节点以 fx/fy 硬锚定在原点（= 放射的圆心）。
 *
 * 确定性：sunflower 初始撒点（黄金角、无随机）+ 固定种子 randomSource
 * （d3 的 jiggle 在节点完全同位时才触发，注入后同输入逐点相等）。
 * 保存布局/拖拽覆盖的优先级在页面层解析，本函数只产计算位置。
 */
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
  forceX,
  forceY,
  type SimulationNodeDatum,
} from 'd3-force-3d'

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

/** 碰撞直径（px）：节点卡片宽 96 + 间距，成对中心距低于它即视觉重叠。 */
export const LAYOUT_COLLIDE_DIAMETER = 112
/** 弹簧自然长度（px）：关系线的目标长度。 */
export const LINK_DISTANCE = 130
/** 初始撒点半径（px）：sunflower 圆盘，仅作迭代起点。 */
const SEED_RADIUS = 360

interface SimNode extends SimulationNodeDatum {
  id: string
  degree: number
  anchored: boolean
}

/** 固定种子 LCG：确定性随机源（jiggle 兜底用，正常路径不触发）。 */
function seededRandom(): () => number {
  let s = 0x2f6e2b1
  return () => {
    s = (1664525 * s + 1013904223) % 4294967296
    return s / 4294967296
  }
}

export function forceLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  rootId?: string,
): Map<string, LayoutPoint> {
  const positions = new Map<string, LayoutPoint>()
  if (!nodes.length) return positions

  const nodeIds = new Set(nodes.map((n) => n.id))
  const degree = new Map<string, number>()
  for (const e of edges) {
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target) || e.source === e.target) continue
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1)
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1)
  }

  // sunflower 撒点：黄金角均布，确定且初始即不重叠、无同位。
  const golden = Math.PI * (3 - Math.sqrt(5))
  const simNodes: SimNode[] = nodes.map((n, i) => {
    const r = SEED_RADIUS * Math.sqrt((i + 0.5) / nodes.length)
    const angle = i * golden
    return {
      id: n.id,
      degree: degree.get(n.id) ?? 0,
      anchored: n.id === rootId,
      x: r * Math.cos(angle),
      y: r * Math.sin(angle),
    }
  })

  // forceLink 会把 link 的 source/target 原地替换为节点对象引用——必须喂拷贝，
  // 否则调用方的 edges 数组（store 原数据）被变异污染。
  const simLinks = edges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target) && e.source !== e.target)
    .map((e) => ({ source: e.source, target: e.target }))

  const simulation = forceSimulation(simNodes, 2)
    .force(
      'link',
      forceLink<SimNode, { source: string; target: string }>(simLinks)
        .id((d) => d.id)
        .distance(LINK_DISTANCE)
        // hub 弹性弱化：度数高的节点少被单边拽动，星形枝叶才能摊开。
        .strength((l) => {
          const s = simNodes.find((n) => n.id === (l as unknown as { source: SimNode }).source.id)
          const t = simNodes.find((n) => n.id === (l as unknown as { target: SimNode }).target.id)
          const min = Math.min(s?.degree ?? 1, t?.degree ?? 1)
          return 1 / Math.max(min, 2)
        }),
    )
    .force('charge', forceManyBody().strength(-420))
    .force('collide', forceCollide<SimNode>().radius(LAYOUT_COLLIDE_DIAMETER / 2).iterations(3))
    // 轻质心拉力：无根锚定的分量/孤立点不漂出包围盒。
    .force('x', forceX<SimNode>(0).strength(0.06))
    .force('y', forceY<SimNode>(0).strength(0.06))
    .randomSource(seededRandom())
    .stop()

  // 聚焦根硬锚定原点（放射布局「圆心」语义的力导向等价物）。
  for (const n of simNodes) {
    if (n.anchored) {
      n.fx = 0
      n.fy = 0
    }
  }

  // 同步跑至冷却（默认 alpha 1 / decay 0.0227 / min 0.001 ≈ 300 tick）。
  const ticks = 300
  for (let i = 0; i < ticks; i++) simulation.tick()

  for (const n of simNodes) {
    positions.set(n.id, { x: n.x ?? 0, y: n.y ?? 0 })
  }
  return positions
}
