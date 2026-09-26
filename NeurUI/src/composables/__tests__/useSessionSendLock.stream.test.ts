/**
 * 锁的生命周期必须跟着"这一轮流"走，而不是跟着视图走。
 *
 * 背景：把流的生命周期从组件上移后（ChatPage 离开页面不再中止流），若最后一个
 * 视图实例卸载就立刻释放 Web Lock，另一个标签立刻可以往**同一个会话**发消息，
 * 两条流并发写同一会话——修一个显示中断却引入并发写入，不可接受。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

import { useSessionSendLock, resetSessionSendLockForTest } from '@/composables/useSessionSendLock'
import { claimChatStream, releaseChatStream } from '@/composables/chatStreamRegistry'

function installLockApi(recorder: { released: boolean }) {
  // @ts-expect-error 注入 mock
  navigator.locks = {
    request: vi.fn((_name: string, _opts: any, cb: any) => {
      const held = cb({ name: _name })
      return new Promise<void>((resolve) => {
        if (held && typeof held.then === 'function') {
          held.then(() => {
            recorder.released = true
            resolve()
          })
        } else {
          resolve()
        }
      })
    }),
  }
}

function mountLockHolder(sid: string) {
  const sessionId = ref(sid)
  return mount({
    setup() {
      useSessionSendLock(sessionId)
      return () => null
    },
  })
}

async function letLockApiSettle() {
  await new Promise((r) => setTimeout(r, 0))
}

describe('useSessionSendLock 与在途流', () => {
  let recorder = { released: false }

  beforeEach(() => {
    vi.restoreAllMocks()
    resetSessionSendLockForTest()
    recorder = { released: false }
    installLockApi(recorder)
    releaseChatStream('s1')
  })

  it('卸载时该会话仍有在途流 → 锁不释放，等流结算才放', async () => {
    const wrapper = mountLockHolder('s1')
    await letLockApiSettle()
    expect(recorder.released).toBe(false)

    claimChatStream({ sessionId: 's1', roundKey: 'r1', controller: new AbortController() })

    wrapper.unmount()
    await letLockApiSettle()
    expect(recorder.released).toBe(false)

    releaseChatStream('s1')
    await letLockApiSettle()
    expect(recorder.released).toBe(true)
  })

  it('卸载时没有在途流 → 照旧立即释放（不把不相关会话的锁焊死）', async () => {
    const wrapper = mountLockHolder('s1')
    await letLockApiSettle()

    wrapper.unmount()
    await letLockApiSettle()

    expect(recorder.released).toBe(true)
  })
})
