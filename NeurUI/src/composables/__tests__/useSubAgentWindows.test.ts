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
const apiGet = vi.fn()
vi.mock('@/api', () => ({ api: { get: (...args: any[]) => apiGet(...args) } }))

import {
  useSubAgentWindows, restoreSubAgentWindows, LEDGER_TO_WINDOW_STATUS,
} from '@/composables/useSubAgentWindows'

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


/**
 * §6-78 L 条（H2-6）：状态面回读与"事件带事实"。
 *
 * 三条契约——① STARTED 带上 status 时，前端用它（经唯一那处映射），不再自造；
 * ② 回读走台账读面 `scope=subagents`，状态映射只有 LEDGER_TO_WINDOW_STATUS 一处；
 * ③ 读面故障只留痕，**不拿空列表冒充"这条会话没派过子任务"**（那是把"读不到"
 *    写成"没有"，与本仓反复登记的假成功同族）。
 */
describe('useSubAgentWindows 状态面回读（H2-6 · §6-78 L 条）', () => {
  beforeEach(() => {
    apiGet.mockReset()
    clearSubAgentWindows()
  })

  it('STARTED 带 status 时用事件的事实（经唯一映射），不带时才落默认', () => {
    // 事件说 running → running；说 queued（后端若先扩态）→ 映射成 UI 的 running，
    // 而不是把未知词值原样塞进界面状态
    handleSubAgentSyncEvent(evt('subagent_started', {
      subagent_id: 'q1', agent_name: '搜索', task: 't', status: 'queued',
    }))
    expect(subAgentWindows.value.q1.status).toBe('running')
    expect(LEDGER_TO_WINDOW_STATUS.queued).toBe('running')

    handleSubAgentSyncEvent(evt('subagent_started', {
      subagent_id: 'q2', agent_name: '搜索', task: 't',
    }))
    expect(subAgentWindows.value.q2.status).toBe('running')

    // 反向：事件带着 completed 进来时，前端不得自顾自显示 running
    handleSubAgentSyncEvent(evt('subagent_started', {
      subagent_id: 'q3', agent_name: '搜索', task: 't', status: 'completed',
    }))
    expect(subAgentWindows.value.q3.status).toBe('completed')
  })

  it('回读走台账读面，状态与成因都按那唯一一处映射落进窗口', async () => {
    apiGet.mockResolvedValue({ data: { runs: [
      { subagent_id: 'r1', agent_id: 'researcher', status: 'running', task: '在跑的', error_type: '' },
      { subagent_id: 'r2', agent_id: 'writer', status: 'failed', task: '超时那条', error_type: 'subagent_timeout' },
      { subagent_id: 'r3', agent_id: 'writer', status: 'cancelled', task: '被取消', error_type: 'subagent_cancelled' },
    ] } })
    await restoreSubAgentWindows('sess-1')
    expect(apiGet).toHaveBeenCalledWith('/console/chat/runs', {
      params: { session_id: 'sess-1', scope: 'subagents' },
    })
    expect(subAgentWindows.value.r1.status).toBe('running')
    expect(subAgentWindows.value.r1.task).toBe('在跑的')
    expect(subAgentWindows.value.r2.status).toBe('failed')
    expect(subAgentWindows.value.r2.error).toBe('subagent_timeout')
    expect(subAgentWindows.value.r3.status).toBe(LEDGER_TO_WINDOW_STATUS.cancelled)
  })

  it('读面故障只留痕：不拿空窗口冒充"这条会话没派过子任务"', async () => {
    apiGet.mockRejectedValue(new Error('503 run 台账已关闭'))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await restoreSubAgentWindows('sess-2')
    expect(Object.keys(subAgentWindows.value)).toEqual([])
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('切会话后过期的回填不写进当前视图', async () => {
    apiGet.mockResolvedValue({ data: { runs: [{ subagent_id: 'x', agent_id: 'a', status: 'running', task: 't' }] } })
    await restoreSubAgentWindows('sess-3', () => true)
    expect(subAgentWindows.value.x).toBeTruthy()
    clearSubAgentWindows()
    await restoreSubAgentWindows('sess-3', () => false)
    expect(Object.keys(subAgentWindows.value)).toEqual([])
  })
})
