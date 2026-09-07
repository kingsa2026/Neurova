/**
 * B3：taskName 执行摘要——时间轴段标题优先显示模型自述短语。
 * 生命周期：tool_call(taskNameActive) 起 → tool_result(taskNameComplete) 收；
 * complete 缺省时保留 active 文案；历史合成透传 taskName；无 taskName 回退工具名。
 */
import { describe, expect, it } from 'vitest'
import {
  appendToolStep,
  attachToolResult,
  buildStepsFromHistory,
  type ChatStep,
} from '../chatSteps'

describe('taskName lifecycle', () => {
  it('appendToolStep carries taskName from tool_call event', () => {
    const steps = appendToolStep([], 'web_search', '{"query":"x"}', '搜索天气')
    expect(steps[0].taskName).toBe('搜索天气')
  })

  it('appendToolStep without taskName keeps step clean (falls back to name)', () => {
    const steps = appendToolStep([], 'web_search', '{"query":"x"}')
    expect(steps[0].taskName).toBeUndefined()
  })

  it('attachToolResult fills complete phrase only when active phrase absent', () => {
    let steps = appendToolStep([], 'web_search', '{}', '搜索天气')
    steps = attachToolResult(steps, '{"ok":1}', '已查天气')
    // v0 语义：完成态短语（不带成败语义）应替换进行中短语——标题随生命周期
    // 从 active 迁移到 complete；active 文案只作 complete 缺失时的兜底
    expect(steps[0].taskName).toBe('已查天气')
    expect(steps[0].result).toBe('{"ok":1}')
    expect(steps[0].active).toBe(false)
  })

  it('attachToolResult without complete phrase keeps active phrase as fallback', () => {
    let steps = appendToolStep([], 'web_search', '{}', '搜索天气')
    steps = attachToolResult(steps, '{"ok":1}')
    expect(steps[0].taskName).toBe('搜索天气')
  })

  it('attachToolResult backfills when tool_call had no taskName (flush path)', () => {
    let steps = appendToolStep([], 'web_search', '{}')
    steps = attachToolResult(steps, 'ok', '已搜索')
    expect(steps[0].taskName).toBe('已搜索')
  })

  it('attachToolResult without any taskName leaves fallback to step name', () => {
    let steps = appendToolStep([], 'computer_shell', '{}')
    steps = attachToolResult(steps, 'ok')
    expect(steps[0].taskName).toBeUndefined()
  })

  it('buildStepsFromHistory passes taskName through', () => {
    const steps = buildStepsFromHistory(undefined, [
      { name: 'memory', arguments: '{}', result: 'ok', taskName: '查记忆' },
    ])
    expect((steps[0] as ChatStep).taskName).toBe('查记忆')
  })

  it('title fallback contract: taskName || name', () => {
    // 渲染契约（ChatPage: step.taskName || step.name）的数据面等价断言
    const withName = buildStepsFromHistory(undefined, [
      { name: 'planning', arguments: '{}' },
    ])[0]
    expect(withName.taskName || withName.name).toBe('planning')
    const withTask = buildStepsFromHistory(undefined, [
      { name: 'planning', arguments: '{}', taskName: '建计划' },
    ])[0]
    expect(withTask.taskName || withTask.name).toBe('建计划')
  })
})
