/**
 * 思考段滚动跟随（2026-09-12 bug 回归）。
 *
 * 用户报障：聊天页 agent 思考过程较长时，.nr-step-reasoning 出现内部滚动条
 * （max-height 320px）后视图停在顶部，看不到最新流式思考。
 * 根因：流式追加文本后没有任何滚动跟随逻辑。
 * 修复契约：活跃推理段容器贴底（scrollTop=scrollHeight）；
 * 用户向上翻阅（距底超阈值）时暂停跟随，回到底部恢复。
 */
import { describe, it, expect } from 'vitest'
import {
  appendReasoningStep,
  appendToolStep,
  finishStep,
  followActiveReasoningScroll,
  isNearBottom,
  type ChatStep,
} from '../chatSteps'

/** 按 ChatPage 模板契约搭一个最小 DOM：nr-step-item(.is-active) > nr-step-reasoning。 */
function mountReasoningDOM(text: string, active = true): HTMLElement {
  const root = document.createElement('div')
  const item = document.createElement('div')
  item.className = active ? 'nr-step-item is-active' : 'nr-step-item'
  const reasoning = document.createElement('div')
  reasoning.className = 'nr-step-reasoning'
  reasoning.textContent = text
  // jsdom 无布局引擎：手工注入滚动尺寸（内容 900px / 视口 320px）
  Object.defineProperty(reasoning, 'scrollHeight', { value: 900, configurable: true })
  Object.defineProperty(reasoning, 'clientHeight', { value: 320, configurable: true })
  item.appendChild(reasoning)
  root.appendChild(item)
  return root
}

describe('followActiveReasoningScroll 思考段贴底跟随', () => {
  it('活跃推理段：贴底（scrollTop=scrollHeight），最新思考可见', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '一段很长的思考')
    const root = mountReasoningDOM(steps[0].text || '')
    const el = followActiveReasoningScroll(root)
    expect(el).not.toBeNull()
    expect(el!.scrollTop).toBe(900)
  })

  it('无活跃推理段（工具段/已封口）→ 不误滚、返回 null', () => {
    const root = mountReasoningDOM('历史思考', false)
    expect(followActiveReasoningScroll(root)).toBeNull()
  })

  it('空容器无 .nr-step-item → 返回 null 不报错', () => {
    expect(followActiveReasoningScroll(document.createElement('div'))).toBeNull()
  })
})

describe('isNearBottom 距底判定（翻阅暂停跟随）', () => {
  const h = { scrollHeight: 900, clientHeight: 320 }

  it('贴底（距底 0）→ 跟随', () => {
    expect(isNearBottom(580, h.scrollHeight, h.clientHeight)).toBe(true)
  })

  it('距底 40 > 默认阈值 → 用户向上翻阅，暂停跟随', () => {
    expect(isNearBottom(540, h.scrollHeight, h.clientHeight)).toBe(false)
  })

  it('回到底部附近 → 恢复跟随', () => {
    expect(isNearBottom(575, h.scrollHeight, h.clientHeight)).toBe(true)
  })
})

describe('模板契约：选择器锚定活跃推理段', () => {
  it('工具段活跃时不得误选（选择器只命中 is-active 下的推理容器）', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '想')
    appendToolStep(steps, 'web_search', '{}') // 推理段封口、工具段活跃
    finishStep(steps[0])
    // 工具段下没有 .nr-step-reasoning，即便 is-active 也不命中
    const root = document.createElement('div')
    const toolItem = document.createElement('div')
    toolItem.className = 'nr-step-item is-active'
    root.appendChild(toolItem)
    expect(followActiveReasoningScroll(root)).toBeNull()
  })
})
