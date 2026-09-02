/**
 * useIMEComposition 测试（IME 合成防误发，对齐 QP useIMEComposition）。
 *
 * 契约：
 * - compositionstart→end 之间 shouldBlockSend=true（选词回车不发）
 * - Safari 语义：compositionend 后紧跟的 keydown 带 keyCode=229 → 阻止
 * - 正常英文回车不拦截
 */
import { describe, expect, it } from 'vitest'
import { useIMEComposition } from '@/composables/useIMEComposition'

const mkEvent = (overrides: Partial<KeyboardEvent> = {}): KeyboardEvent =>
  ({ isComposing: false, keyCode: 13, key: 'Enter', ...overrides }) as unknown as KeyboardEvent

describe('useIMEComposition', () => {
  it('blocks Enter during composition', () => {
    const { onCompositionStart, onCompositionEnd, shouldBlockSend } = useIMEComposition()
    onCompositionStart()
    expect(shouldBlockSend(mkEvent())).toBe(true)
    onCompositionEnd()
    expect(shouldBlockSend(mkEvent())).toBe(false)
  })

  it('blocks Safari composition-commit keydown (keyCode 229)', () => {
    const { onCompositionStart, onCompositionEnd, shouldBlockSend } = useIMEComposition()
    onCompositionStart()
    onCompositionEnd()
    // Safari：合成提交的回车 isComposing=false 但 keyCode=229
    expect(shouldBlockSend(mkEvent({ keyCode: 229 }))).toBe(true)
    // 之后的正常回车放行
    expect(shouldBlockSend(mkEvent())).toBe(false)
  })

  it('blocks when event.isComposing is set even without composition events', () => {
    const { shouldBlockSend } = useIMEComposition()
    expect(shouldBlockSend(mkEvent({ isComposing: true }))).toBe(true)
  })

  it('normal Enter is never blocked', () => {
    const { shouldBlockSend } = useIMEComposition()
    expect(shouldBlockSend(mkEvent())).toBe(false)
  })
})
