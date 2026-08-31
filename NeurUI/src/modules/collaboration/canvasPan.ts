/**
 * canvasPan — 无限画布视口平移纯函数（空格+左键拖拽）+ 节点落点坐标。
 *
 * 设计约束（见 __tests__/canvasPan.test.ts 契约）：
 * - 无限画布：节点坐标允许负值，不设原点硬边界；
 * - 空格平移按屏幕像素 1:1 累加（与 onWheel 平移一致，不随 zoom 缩放）；
 * - 激活判定 空格 + 左键 + 画布容器内，空格未按时画布行为零改变。
 */

export interface PanState {
  panX: number
  panY: number
}

export interface ClientPoint {
  x: number
  y: number
}

/** 落点 → 节点左上角的中心对齐偏移（节点估算 120×40 头部 + 主体，视觉居中） */
export const DROP_NODE_OFFSET: ClientPoint = { x: 60, y: 20 }

/** 空格+左键拖拽平移：新 pan = 起点 pan + 屏幕像素位移（1:1，不除 zoom） */
export function panByDrag(start: PanState, from: ClientPoint, to: ClientPoint): PanState {
  return {
    panX: start.panX + (to.x - from.x),
    panY: start.panY + (to.y - from.y),
  }
}

/** 指针落点 → 节点左上角（画布坐标）。允许负值——无限画布无原点边界 */
export function dropNodePosition(
  pointerX: number,
  pointerY: number,
  offset: ClientPoint = DROP_NODE_OFFSET,
): ClientPoint {
  return { x: pointerX - offset.x, y: pointerY - offset.y }
}

/** 空格平移激活判定：空格按下 + 左键 + 事件命中画布容器 */
export function shouldPanOnSpace(
  spaceDown: boolean,
  button: number,
  withinCanvas: boolean,
): boolean {
  return spaceDown && button === 0 && withinCanvas
}
