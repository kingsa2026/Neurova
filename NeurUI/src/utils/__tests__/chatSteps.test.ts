import { describe, expect, it } from 'vitest'
import {
  appendReasoningStep,
  appendToolStep,
  attachToolResult,
  buildStepsFromHistory,
  deriveStreamPhase,
  finishAllSteps,
  toggleStep,
  type ChatStep,
} from '../chatSteps'

describe('chatSteps 步骤化时间轴', () => {
  it('推理续写：活跃推理段续写不开新段', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '第一段')
    appendReasoningStep(steps, '第二段')
    expect(steps).toHaveLength(1)
    expect(steps[0].text).toBe('第一段第二段')
    expect(steps[0].active).toBe(true)
  })

  it('工具打断推理：推理段封口收起，工具段活跃', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '想想')
    appendToolStep(steps, 'web_search', '{"query":"x"}')
    expect(steps).toHaveLength(2)
    expect(steps[0].kind).toBe('reasoning')
    expect(steps[0].active).toBe(false)
    // 自动收起：封口时 open 翻 false（三需求②"步骤结束自动折叠"）
    expect(steps[0].open).toBe(false)
    expect(steps[1].kind).toBe('tool')
    expect(steps[1].name).toBe('web_search')
    expect(steps[1].active).toBe(true)
    expect(steps[1].open).toBe(true)
  })

  it('工具后再思考：开新推理段（交替时间轴，图一形态）', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '想1')
    appendToolStep(steps, 'web_search', '{}')
    attachToolResult(steps, '结果')
    appendReasoningStep(steps, '想2')
    expect(steps.map((s) => s.kind)).toEqual(['reasoning', 'tool', 'reasoning'])
    expect(steps[2].text).toBe('想2')
    expect(steps[2].active).toBe(true)
  })

  it('attachToolResult 落到活跃工具段并封口', () => {
    const steps: ChatStep[] = []
    appendToolStep(steps, 'run_command', 'ls')
    attachToolResult(steps, 'file1\nfile2')
    expect(steps[0].result).toBe('file1\nfile2')
    expect(steps[0].active).toBe(false)
    expect(steps[0].open).toBe(false)
  })

  it('正文开始 finishAllSteps：所有活跃段收起', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '想')
    appendToolStep(steps, 'grep', 'x') // 无 result 的工具段
    finishAllSteps(steps)
    expect(steps.every((s) => !s.active)).toBe(true)
    expect(steps.every((s) => !s.open)).toBe(true)
  })

  it('用户手动展开后 toggleStep 独立生效（一开不全开）', () => {
    const steps: ChatStep[] = []
    appendToolStep(steps, 'a', '{}')
    attachToolResult(steps, 'r1')
    appendToolStep(steps, 'b', '{}')
    attachToolResult(steps, 'r2')
    // 两段都收起
    expect(steps.every((s) => !s.open)).toBe(true)
    // 只展开第一段
    toggleStep(steps, steps[0].id)
    expect(steps[0].open).toBe(true)
    expect(steps[1].open).toBe(false)
  })

  it('历史合成：reasoning 在前 + 工具段随后，全部收起', () => {
    const steps = buildStepsFromHistory(
      '旧推理内容',
      [
        { name: 'web_search', arguments: '{}', result: 'r1' },
        { name: 'read_file', arguments: '{}', result: 'r2' },
      ],
    )
    expect(steps.map((s) => s.kind)).toEqual(['reasoning', 'tool', 'tool'])
    expect(steps.every((s) => !s.open)).toBe(true)
    expect(steps.every((s) => !s.active)).toBe(true)
    expect(steps[1].result).toBe('r1')
  })

  it('历史合成：无 reasoning 无工具 → 空数组', () => {
    expect(buildStepsFromHistory(undefined, undefined)).toEqual([])
  })
})

describe('deriveStreamPhase 流式状态派生（三需求①）', () => {
  it('无步骤无正文 → understanding（收到信息，正在理解）', () => {
    expect(deriveStreamPhase({ content: '', steps: [], streaming: true })).toBe('understanding')
  })

  it('活跃推理段 → thinking', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '想')
    expect(deriveStreamPhase({ content: '', steps, streaming: true })).toBe('thinking')
  })

  it('活跃工具段 → tool', () => {
    const steps: ChatStep[] = []
    appendToolStep(steps, 'run_command', 'ls')
    expect(deriveStreamPhase({ content: '', steps, streaming: true })).toBe('tool')
  })

  it('正文开始 → output', () => {
    const steps: ChatStep[] = []
    appendReasoningStep(steps, '想')
    expect(deriveStreamPhase({ content: '你好', steps, streaming: true })).toBe('output')
  })
})
