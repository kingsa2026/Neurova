/**
 * 画布全屏助手 — 纯函数层（document 依赖注入，便于 vitest 隔离）
 */

export interface FullscreenDoc {
  fullscreenElement: Element | null
  exitFullscreen?: () => Promise<void> | void
  webkitExitFullscreen?: () => void
}

export interface FullscreenEl {
  requestFullscreen?: () => Promise<void> | void
  webkitRequestFullscreen?: () => void
}

export function isFullscreen(doc: FullscreenDoc): boolean {
  return Boolean(doc.fullscreenElement)
}

/** 标准 API 或 webkit 前缀任一可用即可 */
export function canFullscreen(doc: FullscreenDoc, el: FullscreenEl): boolean {
  return Boolean(el.requestFullscreen || el.webkitRequestFullscreen)
}

/** 优先标准 requestFullscreen，回退 webkit 前缀（Safari 旧版） */
export function requestFullscreenCompat(el: FullscreenEl, doc: FullscreenDoc): void {
  if (typeof el.requestFullscreen === 'function') {
    void el.requestFullscreen()
    return
  }
  if (typeof el.webkitRequestFullscreen === 'function') {
    el.webkitRequestFullscreen()
  }
}

/** 优先标准 exitFullscreen，回退 webkit 前缀 */
export function exitFullscreenCompat(doc: FullscreenDoc): void {
  if (typeof doc.exitFullscreen === 'function') {
    void doc.exitFullscreen()
    return
  }
  if (typeof doc.webkitExitFullscreen === 'function') {
    doc.webkitExitFullscreen()
  }
}
