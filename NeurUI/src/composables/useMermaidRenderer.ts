/**
 * mermaid 图表渲染（补课 E）。
 *
 * markdown.ts 把 ```mermaid 围栏块输出为占位 div（data-mermaid-code=
 * encodeURIComponent 编码的源码）；本模块在 DOM 插入后扫描占位、
 * 动态 import mermaid（首帧不加载 ~1MB 包）、按主题渲染 SVG。
 * 渲染失败（流式期间代码不完整是常态）保留源码 pre 兜底。
 */
import { nextTick } from 'vue'

let mermaidPromise: Promise<any> | null = null
let initialized = false

async function getMermaid(dark: boolean): Promise<any> {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((m) => {
      const mermaid = m.default
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: dark ? 'dark' : 'neutral',
      })
      initialized = true
      return mermaid
    })
  }
  return mermaidPromise
}

export function useMermaidRenderer(getDark: () => boolean) {
  /** 扫描容器内未渲染的占位 div 并渲染（幂等：done 标记跳过）。 */
  async function renderIn(container: HTMLElement | null): Promise<void> {
    if (!container) return
    const pending = Array.from(
      container.querySelectorAll<HTMLElement>('.nr-mermaid[data-mermaid-code]:not([data-mermaid-done])'),
    )
    if (pending.length === 0) return

    let mermaid: any
    try {
      mermaid = await getMermaid(getDark())
    } catch (e) {
      // 动态加载失败：占位保留源码 pre，不重试（本次会话内）
      mermaidPromise = null
      for (const el of pending) el.setAttribute('data-mermaid-done', 'error')
      return
    }

    for (const el of pending) {
      const encoded = el.getAttribute('data-mermaid-code') || ''
      let code = ''
      try {
        code = decodeURIComponent(encoded)
      } catch {
        code = encoded
      }
      try {
        const { svg } = await mermaid.render(`nr-mermaid-svg-${Math.random().toString(36).slice(2)}`, code)
        el.innerHTML = svg
        el.setAttribute('data-mermaid-done', '1')
      } catch {
        // 流式期间代码不完整：不标记 done，等下一轮内容更新重试
      }
    }
    void initialized
  }

  /** 防抖封装（流式期间高频内容变更，400ms 静默后才渲染）。 */
  let timer: ReturnType<typeof setTimeout> | null = null
  function scheduleRender(container: HTMLElement | null, delay = 400): void {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      void nextTick().then(() => renderIn(container))
    }, delay)
  }

  function dispose(): void {
    if (timer) clearTimeout(timer)
    timer = null
  }

  return { renderIn, scheduleRender, dispose }
}
