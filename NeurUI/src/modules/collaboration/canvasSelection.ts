/**
 * canvasSelection — 框选多选纯函数（遗留 F）。
 *
 * normalizeRect：起点/终点（屏幕或画布坐标均可）归一化为 {x,y,w,h}；
 * nodesInRect：节点（position + 估算尺寸）与选框矩形相交判定。
 * 默认节点估算 140×140 与 fitView 一致。
 */
export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export function normalizeRect(
  startX: number,
  startY: number,
  curX: number,
  curY: number,
): Rect {
  return {
    x: Math.min(startX, curX),
    y: Math.min(startY, curY),
    w: Math.abs(curX - startX),
    h: Math.abs(curY - startY),
  }
}

export const DEFAULT_NODE_SIZE = { w: 140, h: 140 }

export function nodesInRect(
  nodes: Array<{ id: string; position: { x: number; y: number } }>,
  rect: Rect,
  nodeSize: { w: number; h: number } = DEFAULT_NODE_SIZE,
): string[] {
  const hit: string[] = []
  for (const n of nodes) {
    const nx = n.position?.x ?? 0
    const ny = n.position?.y ?? 0
    const intersects =
      nx < rect.x + rect.w &&
      nx + nodeSize.w > rect.x &&
      ny < rect.y + rect.h &&
      ny + nodeSize.h > rect.y
    if (intersects) hit.push(n.id)
  }
  return hit
}
