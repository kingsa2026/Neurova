/**
 * CanvasDesignerPage 执行事件流卸载收束契约测试（F-06 回归）。
 *
 * 页面体量大不便整体挂载，以源码契约锁定修复形态：
 * - 等待流结束的 setInterval 回调判 isDisposed（卸载即收束，不再空转）；
 * - 兜底 setTimeout(600_000) 句柄保存为 runFallbackTimer，收束/卸载时清除；
 * - SSE 订阅句柄提升到组件作用域（activeExecutionUnsubscribe），
 *   onBeforeUnmount 能兜底 unsubscribe（原实现为函数局部 const 不可达）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(
  resolve(process.cwd(), 'src/modules/collaboration/CanvasDesignerPage.vue'),
  'utf-8',
)

/** 抽取 anchor 之后第一个平衡大括号块的内容。 */
function blockAfter(anchor: string): string {
  const idx = source.indexOf(anchor)
  if (idx === -1) return ''
  const braceStart = source.indexOf('{', idx)
  if (braceStart === -1) return ''
  let depth = 0
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(braceStart + 1, i)
    }
  }
  return ''
}

describe('F-06 画布执行事件流的卸载收束', () => {
  it('等待流结束的 interval 回调判 isDisposed（isDisposed || streamEnded 收束）', () => {
    expect(source).toContain('if (isDisposed.value || streamEnded) settle()')
  })

  it('兜底 timeout 句柄被保存（runFallbackTimer）并在收束时清除', () => {
    expect(source).toContain('runFallbackTimer = setTimeout(')
    const waitBlock = blockAfter('事件流结束后（终态收束或断流）决定是否需要轮询兜底')
    expect(waitBlock).toContain('clearTimeout(runFallbackTimer)')
    expect(waitBlock).toContain('runFallbackTimer = null')
  })

  it('订阅句柄提升到组件作用域（onBeforeUnmount 可达）', () => {
    expect(source).toContain('let activeExecutionUnsubscribe')
    expect(source).toContain('activeExecutionUnsubscribe = unsubscribe')
  })

  it('onBeforeUnmount 清兜底定时器并兜底取消订阅', () => {
    const unmount = blockAfter('onBeforeUnmount(() => {')
    expect(unmount).not.toBe('')
    expect(unmount).toContain('clearTimeout(runFallbackTimer)')
    expect(unmount).toContain('activeExecutionUnsubscribe?.()')
  })
})
