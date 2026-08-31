/**
 * canvasMinimap — 小地图纯函数（遗留 F）。
 *
 * computeMinimapLayout：内容包围盒 → fit 缩放与居中偏移，
 * 输出节点 mini 矩形 + 当前视口矩形（zoom/pan 换算）。
 * miniClickToPan：mini 点击点 → 新 panX/panY（该画布点居中）。
 */
export interface MinimapNodeLike {
  id: string
  position: { x: number; y: number }
}

export interface MinimapViewport {
  zoom: number
  panX: number
  panY: number
}

export interface MiniRect {
  x: number
  y: number
  w: number
  h: number
}

export interface MinimapLayout {
  scale: number
  offsetX: number
  offsetY: number
  /** 内容包围盒左上角（画布坐标）——mini 点→画布点换算的基准 */
  contentOrigin: { x: number; y: number }
  nodeRects: Array<MiniRect & { id: string }>
  viewportRect: MiniRect
}

/** 节点估算尺寸（与 fitView 一致） */
const NODE_SIZE = { w: 140, h: 140 }
const MINIMAP_PADDING = 8

export function computeMinimapLayout(
  nodes: MinimapNodeLike[],
  viewport: MinimapViewport,
  container: { w: number; h: number },
  mini: { w: number; h: number },
): MinimapLayout {
  // 内容包围盒（画布坐标，含节点估算尺寸）
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const n of nodes) {
    const x = n.position?.x ?? 0
    const y = n.position?.y ?? 0
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    maxX = Math.max(maxX, x + NODE_SIZE.w)
    maxY = Math.max(maxY, y + NODE_SIZE.h)
  }

  const hasContent = nodes.length > 0 && maxX >= minX
  const contentW = hasContent ? maxX - minX : 0
  const contentH = hasContent ? maxY - minY : 0

  const fitW = mini.w - MINIMAP_PADDING * 2
  const fitH = mini.h - MINIMAP_PADDING * 2
  const scale = hasContent
    ? Math.min(fitW / contentW, fitH / contentH, 1)
    : Math.min(fitW / container.w, fitH / container.h, 1)

  // 内容居中到 mini
  const offsetX = hasContent
    ? (mini.w - contentW * scale) / 2
    : (mini.w - container.w * scale) / 2
  const offsetY = hasContent
    ? (mini.h - contentH * scale) / 2
    : (mini.h - container.h * scale) / 2

  const nodeRects = nodes.map((n) => ({
    id: n.id,
    x: offsetX + (n.position?.x ?? 0) * scale,
    y: offsetY + (n.position?.y ?? 0) * scale,
    w: NODE_SIZE.w * scale,
    h: NODE_SIZE.h * scale,
  }))

  // 视口（画布单位）：中心 = (container/2 - pan) / zoom，尺寸 = container/zoom
  const vpW = container.w / viewport.zoom
  const vpH = container.h / viewport.zoom
  const vpCx = container.w / 2 / viewport.zoom - viewport.panX / viewport.zoom
  const vpCy = container.h / 2 / viewport.zoom - viewport.panY / viewport.zoom
  const viewportRect: MiniRect = {
    x: offsetX + (vpCx - vpW / 2) * scale,
    y: offsetY + (vpCy - vpH / 2) * scale,
    w: vpW * scale,
    h: vpH * scale,
  }

  return {
    scale,
    offsetX,
    offsetY,
    contentOrigin: { x: hasContent ? minX : 0, y: hasContent ? minY : 0 },
    nodeRects,
    viewportRect,
  }
}

export function miniClickToPan(
  click: { x: number; y: number },
  layout: MinimapLayout,
  container: { w: number; h: number },
): { panX: number; panY: number } {
  // mini 点 → 画布坐标（相对内容原点偏移）
  const contentX = (click.x - layout.offsetX) / layout.scale + layout.contentOrigin.x
  const contentY = (click.y - layout.offsetY) / layout.scale + layout.contentOrigin.y
  // 该画布点居中到视口：pan = container/2 - content * zoom
  // zoom 未随点击改变——用 viewportRect 反推当前 zoom：
  // viewportRect.w = (container.w / zoom) * scale → zoom = container.w * scale / viewportRect.w
  const zoom =
    layout.viewportRect.w > 0 ? (container.w * layout.scale) / layout.viewportRect.w : 1
  return {
    panX: container.w / 2 - contentX * zoom,
    panY: container.h / 2 - contentY * zoom,
  }
}
