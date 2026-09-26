/**
 * 聊天流所有权单一事实源红测：离开页面只解绑视图，绝不中止流。
 *
 * 现场故障（2026-09-26）：ChatPage 的 onBeforeUnmount 直接 abortController.abort()，
 * 把一轮仍在后台跑、且后端已备好 replay 缓冲与落库的推理从显示侧掐死；回到页面
 * 既不重连也不重载，气泡永远停在半截。根因是"流的生命周期被绑在组件生命周期上"。
 * 本模块把中止权收口成三种显式用户意图，视图脱离不再是一种。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  abortChatStream,
  attachChatStreamView,
  claimChatStream,
  currentChatStream,
  detachChatStreamView,
  onChatStreamSettled,
  releaseChatStream,
} from '@/composables/chatStreamRegistry'

function recordingController() {
  const aborted = vi.fn()
  return { aborted, controller: { signal: {}, abort: aborted } as unknown as AbortController }
}

describe('chatStreamRegistry', () => {
  beforeEach(() => {
    // 每条用例独立：清掉模块级在途表，避免互相污染
    for (const sid of ['s1', 's2', 's3', 'dup', 'settle', 'abort']) {
      const stream = currentChatStream(sid)
      if (stream) releaseChatStream(sid)
    }
  })

  it('脱离视图不中止流，流仍在途', () => {
    const { aborted, controller } = recordingController()
    claimChatStream({ sessionId: 's1', roundKey: 'r1', controller })

    detachChatStreamView('s1')

    expect(aborted).not.toHaveBeenCalled()
    expect(currentChatStream('s1')).not.toBeNull()
  })

  it('只有三种显式用户意图能中止流，其它理由一律拒绝', () => {
    const { aborted, controller } = recordingController()
    claimChatStream({ sessionId: 's2', roundKey: 'r2', controller })

    // 把"离开页面"当理由传进来必须被拒绝——否则同一个 bug 能从后门回来
    expect(abortChatStream('s2', 'viewDetached' as never)).toBe(false)
    expect(aborted).not.toHaveBeenCalled()

    expect(abortChatStream('s2', 'userStopped')).toBe(true)
    expect(aborted).toHaveBeenCalledTimes(1)
    expect(currentChatStream('s2')).toBeNull()
  })

  it('同会话仍有在途流时二次 claim 被拒，不产生读不上数的孤儿流', () => {
    const first = recordingController()
    const second = recordingController()
    expect(claimChatStream({ sessionId: 'dup', roundKey: 'rA', controller: first.controller })).not.toBeNull()

    expect(claimChatStream({ sessionId: 'dup', roundKey: 'rB', controller: second.controller })).toBeNull()
    // 原流必须活着（重挂载不得把在途流挤掉）
    expect(currentChatStream('dup')?.roundKey).toBe('rA')
  })

  it('重挂视图拿回的是同一个 controller，停止按钮能中止在途那一轮', () => {
    const { aborted, controller } = recordingController()
    claimChatStream({ sessionId: 's3', roundKey: 'r3', controller })
    detachChatStreamView('s3')

    const rebound = attachChatStreamView('s3')

    expect(rebound?.controller).toBe(controller)
    expect(rebound?.viewBound).toBe(true)
    rebound?.controller.abort()
    expect(aborted).toHaveBeenCalledTimes(1)
  })

  it('自然结束与中止都要通知结算订阅方，并区分是否被中止', () => {
    const settled = vi.fn()
    onChatStreamSettled(settled)

    const { controller } = recordingController()
    claimChatStream({ sessionId: 'settle', roundKey: 'rS', controller })
    releaseChatStream('settle')
    expect(settled).toHaveBeenCalledWith('settle', { aborted: false })

    const other = recordingController()
    claimChatStream({ sessionId: 'abort', roundKey: 'rT', controller: other.controller })
    abortChatStream('abort', 'switchedSession')
    expect(settled).toHaveBeenLastCalledWith('abort', { aborted: true })
  })
})
