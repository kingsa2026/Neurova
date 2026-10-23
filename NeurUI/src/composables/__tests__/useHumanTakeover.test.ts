/**
 * 人工接管按钮状态机：以后端事实为准，写入只追加开始/结束事件。
 */
import { nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/modules/quality', () => ({
  getSessionTakeoverState: vi.fn(),
  recordHumanTakeover: vi.fn(),
}))

import {
  getSessionTakeoverState,
  recordHumanTakeover,
  type QualityEvent,
  type TakeoverState,
} from '@/api/modules/quality'
import { useHumanTakeover } from '@/composables/useHumanTakeover'

const mockGet = vi.mocked(getSessionTakeoverState)
const mockPost = vi.mocked(recordHumanTakeover)

function state(sessionId: string, active: boolean) {
  return {
    code: 0,
    message: 'ok',
    data: {
      session_id: sessionId,
      active,
      observed: true,
      last_event: null,
    } as TakeoverState,
  }
}

function event(eventType: 'human_takeover_started' | 'human_takeover_ended'): QualityEvent {
  return {
    event_id: 'cqe_1',
    event_type: eventType,
    session_id: 's-1',
    source: 'console_mark',
    source_event_id: '',
    reason_code: 'console_toggle',
    occurred_at: '2026-10-23T00:00:00+00:00',
    duplicate: false,
  }
}

describe('useHumanTakeover', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue(state('s-1', false))
    mockPost.mockImplementation(async (payload) => ({
      code: 0,
      message: 'ok',
      data: event(payload.event_type),
    }))
  })

  it('挂载即按当前会话恢复后端状态', async () => {
    mockGet.mockResolvedValue(state('s-1', true))
    const sid = ref<string | null>('s-1')
    const takeover = useHumanTakeover(() => sid.value, () => 'a-1')
    await flushPromises()

    expect(mockGet).toHaveBeenCalledWith('s-1')
    expect(takeover.active.value).toBe(true)
  })

  it('无会话时不发请求、状态为未接管', async () => {
    const takeover = useHumanTakeover(() => null, () => 'a-1')
    await flushPromises()

    expect(mockGet).not.toHaveBeenCalled()
    expect(takeover.active.value).toBe(false)
  })

  it('点击接管写入 started（console_mark），再次点击写入 ended', async () => {
    const takeover = useHumanTakeover(() => 's-1', () => 'a-1')
    await flushPromises()

    await takeover.toggle()
    expect(mockPost).toHaveBeenLastCalledWith({
      event_type: 'human_takeover_started',
      session_id: 's-1',
      agent_id: 'a-1',
      source: 'console_mark',
      reason_code: 'console_toggle',
    })
    expect(takeover.active.value).toBe(true)

    await takeover.toggle()
    expect(mockPost).toHaveBeenLastCalledWith(
      expect.objectContaining({ event_type: 'human_takeover_ended' }),
    )
    expect(takeover.active.value).toBe(false)
  })

  it('写入失败向上抛，状态不变且可再次点击', async () => {
    const takeover = useHumanTakeover(() => 's-1', () => 'a-1')
    await flushPromises()
    mockPost.mockRejectedValueOnce(new Error('db down'))

    await expect(takeover.toggle()).rejects.toThrow('db down')
    expect(takeover.active.value).toBe(false)
    expect(takeover.updating.value).toBe(false)
  })

  it('状态读取失败时暴露错误，界面据此不把未知当未接管', async () => {
    mockGet.mockRejectedValueOnce(new Error('network down'))
    const takeover = useHumanTakeover(() => 's-1', () => 'a-1')
    await flushPromises()

    expect(takeover.stateError.value).toBeTruthy()
  })

  it('切换会话后重读新会话状态', async () => {
    const sid = ref<string | null>('s-1')
    mockGet.mockImplementation(async (sessionId) => state(sessionId, sessionId === 's-2'))
    const takeover = useHumanTakeover(() => sid.value, () => 'a-1')
    await flushPromises()

    sid.value = 's-2'
    await nextTick()
    await flushPromises()

    expect(mockGet).toHaveBeenLastCalledWith('s-2')
    expect(takeover.active.value).toBe(true)
  })
})
