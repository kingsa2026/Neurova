/**
 * ChatPage 思考段滚动跟随接线契约（2026-09-12 bug 回归）。
 *
 * 用户报障：思考过程较长出现滚动条后，看不到最新思考。
 * utils 层行为已由 chatSteps.reasoningFollow.test.ts 锁定；这里按
 * ChatPage.streamLifecycle.test.ts 的源码契约模式锁定接线三处：
 * 1. 模板 .nr-step-reasoning 挂 @scroll 翻阅守卫；
 * 2. SSE reasoning/thinking 分支追加文本后调用 followReasoningScroll；
 * 3. followReasoningScroll 内有 stick 守卫 + nextTick（DOM 更新后再滚）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/pages/ChatPage.vue'), 'utf-8')

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

describe('思考段滚动跟随接线', () => {
  it('模板：.nr-step-reasoning 容器挂 @scroll 翻阅守卫', () => {
    expect(source).toMatch(/class="nr-step-reasoning"[^>]*@scroll="onReasoningScroll"/)
  })

  it('SSE reasoning/thinking 分支：追加文本后触发滚动跟随', () => {
    const branch = blockAfter("case 'reasoning':")
    expect(branch).not.toBe('')
    expect(branch).toContain('appendReasoningStep')
    expect(branch).toContain('followReasoningScroll()')
  })

  it('followReasoningScroll：stick 守卫在前 + nextTick 后贴底', () => {
    const fn = blockAfter('function followReasoningScroll(')
    expect(fn).not.toBe('')
    expect(fn).toContain('reasoningStick.value')
    expect(fn).toContain('nextTick')
    expect(fn).toContain('followActiveReasoningScroll')
  })

  it('onReasoningScroll：以 isNearBottom 回写 stick 态', () => {
    const fn = blockAfter('function onReasoningScroll(')
    expect(fn).not.toBe('')
    expect(fn).toContain('isNearBottom')
    expect(fn).toContain('reasoningStick.value')
  })
})
