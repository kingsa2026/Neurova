/**
 * 审计⑫：并行工具结果交叉错挂。
 * call A → call B → result A → result B 的到达顺序下，旧实现把
 * result A 挂到最近活跃段 B、result B 经 !s.result 回填 A。
 */
import { describe, expect, it } from 'vitest'
import { appendToolStep, attachToolResult } from '../chatSteps'

describe('attachToolResult 并行归属（审计⑫）', () => {
  it('带 toolName 时按名归属（交错到达）', () => {
    let steps = appendToolStep([], 'toolA', '{}')
    steps = appendToolStep(steps, 'toolB', '{}')
    steps = attachToolResult(steps, 'A 的结果', undefined, 'toolA')
    steps = attachToolResult(steps, 'B 的结果', undefined, 'toolB')

    expect(steps[0]).toMatchObject({ name: 'toolA', result: 'A 的结果', active: false })
    expect(steps[1]).toMatchObject({ name: 'toolB', result: 'B 的结果', active: false })
  })

  it('同段名多次出现：活跃段优先', () => {
    let steps = appendToolStep([], 'toolA', '{"n":1}')
    steps = attachToolResult(steps, '第一次', undefined, 'toolA')
    steps = appendToolStep(steps, 'toolA', '{"n":2}')
    steps = attachToolResult(steps, '第二次', undefined, 'toolA')

    expect(steps[0].result).toBe('第一次')
    expect(steps[1].result).toBe('第二次')
  })

  it('无 toolName 回退旧语义（最近活跃段）', () => {
    let steps = appendToolStep([], 'toolA', '{}')
    steps = appendToolStep(steps, 'toolB', '{}')
    steps = attachToolResult(steps, '先到结果')
    expect(steps[1].result).toBe('先到结果')
  })

  it('带 toolName 但无命中段 → 回退旧语义（不丢结果）', () => {
    let steps = appendToolStep([], 'toolA', '{}')
    steps = attachToolResult(steps, '迟到结果', undefined, 'toolUnknown')
    expect(steps[0].result).toBe('迟到结果')
  })
})
