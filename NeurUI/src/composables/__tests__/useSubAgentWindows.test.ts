/**
 * useSubAgentWindows — 子 Agent 浮窗栈状态（P2-15 防回归）。
 *
 * 契约：
 * 1. chunk 增量累积进 bodyText（对外语义与原 chunks.join('') 一致）并计数；
 * 2. completed/failed 窗口超时自动回收；running 窗口不受超时影响；
 * 3. 同一 subagent 重新 started 时清除待回收定时器、重置窗口；
 * 4. clearSubAgentWindows 整栈回收（会话/Agent 切换用），并清空定时器；
 * 5. 非 subagent 事件返回 false 交还调用方分派。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useSubAgentWindows } from '@/composables/useSubAgentWindows'

const { subAgentWindows, handleSubAgentSyncEvent, clearSubAgentWindows } = useSubAgentWindows()

function evt(type: string, payload: Record<string, unknown>) {
  return { event_type: type, payload }
}

describe('useSubAgentWindows（P2-15）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    clearSubAgentWindows()
  })

  afterEach(() => {
    clearSubAgentWindows()
    vi.useRealTimers()
  })

  it('chunk 增量累积到 bodyText（与原 chunks join("") 语义一致）并计数', () => {
    expect(handleSubAgentSyncEvent(evt('subagent_started', { subagent_id: 'a1', agent_name: '搜索' }))).toBe(true)
    handleSubAgentSyncEvent(evt('subagent_chunk', { subagent_id: 'a1', data: 'foo' }))
    handleSubAgentSyncEvent(evt('subagent_chunk', { subagent_id: 'a1', data: 'bar' }))

    const win = subAgentWindows.value.a1
    expect(win.bodyText).toBe('foobar')
    expect(win.chunkCount).toBe(2)
  })

  it('completed 窗口短时间保留、超时后自动回收', () => {
    handleSubAgentSyncEvent(evt('subagent_started', { subagent_id: 'a2' }))
    handleSubAgentSyncEvent(evt('subagent_chunk', { subagent_id: 'a2', data: 'x' }))
    handleSubAgentSyncEvent(evt('subagent_completed', { subagent_id: 'a2', status: 'completed', report: 'done' }))

    expect(subAgentWindows.value.a2.status).toBe('completed')
    expect(subAgentWindows.value.a2.report).toBe('done')

    vi.advanceTimersByTime(60_000)
    expect(subAgentWindows.value.a2).toBeDefined() // 未到回收时限，用户仍可读报告

    vi.advanceTimersByTime(600_000)
    expect(subAgentWindows.value.a2).toBeUndefined() // 超时回收
  })

  it('failed 窗口同样超时回收；running 窗口不受超时影响', () => {
    handleSubAgentSyncEvent(evt('subagent_started', { subagent_id: 'a3' }))
    handleSubAgentSyncEvent(evt('subagent_started', { subagent_id: 'a4' }))
    handleSubAgentSyncEvent(evt('subagent_completed', { subagent_id: 'a3', status: 'failed', error: 'boom' }))

    vi.advanceTimersByTime(600_000)

    expect(subAgentWindows.value.a3).toBeUndefined()
    expect(subAgentWindows.value.a4).toBeDefined()
    expect(subAgentWindows.value.a4.status).toBe('running')
  })

  it('重新 started 清除待回收定时器并重置窗口', () => {
    handleSubAgentSyncEvent(evt('subagent_started', { subagent_id: 'a5' }))
    handleSubAgentSyncEvent(evt('subagent_completed', { subagent_id: 'a5', status: 'completed', report: 'r1' }))

    // 未到超时即重新启动同一 subagent
    handleSubAgentSyncEvent(evt('subagent_started', { subagent_id: 'a5', task: 'retry' }))
    handleSubAgentSyncEvent(evt('subagent_chunk', { subagent_id: 'a5', data: 'new' }))

    vi.advanceTimersByTime(600_000)

    const win = subAgentWindows.value.a5
    expect(win).toBeDefined()
    expect(win.status).toBe('running')
    expect(win.bodyText).toBe('new')
    expect(win.chunkCount).toBe(1)
  })

  it('clearSubAgentWindows 整栈回收并清空待回收定时器', () => {
    handleSubAgentSyncEvent(evt('subagent_started', { subagent_id: 'a6' }))
    handleSubAgentSyncEvent(evt('subagent_completed', { subagent_id: 'a6', status: 'completed', report: 'r' }))

    clearSubAgentWindows()
    expect(Object.keys(subAgentWindows.value)).toHaveLength(0)

    // 定时器已清：推进时钟不抛错、窗口不复活
    expect(() => vi.advanceTimersByTime(600_000)).not.toThrow()
    expect(subAgentWindows.value.a6).toBeUndefined()
  })

  it('非 subagent 事件返回 false；未知窗口的 chunk 被忽略不崩', () => {
    expect(handleSubAgentSyncEvent(evt('computer_action', { action: 'click' }))).toBe(false)
    expect(handleSubAgentSyncEvent(evt('subagent_chunk', { subagent_id: 'ghost', data: 'x' }))).toBe(true)
    expect(Object.keys(subAgentWindows.value)).toHaveLength(0)
  })
})
