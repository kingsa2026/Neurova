/**
 * useSessionSendLock 测试（补课 A4：跨标签单发送者）。
 *
 * jsdom 无 navigator.locks——锁定逻辑用 mock 验证：ifAvailable 竞争、
 * 释放后接管、无 API 能力降级。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useSessionSendLock } from '@/composables/useSessionSendLock'

describe('useSessionSendLock', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // @ts-expect-error 测试环境注入
    delete navigator.locks
  })

  it('degrades to owner=true when locks API missing', async () => {
    const sid = ref('s1')
    const { isOwner } = useSessionSendLock(sid)
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))
    expect(isOwner.value).toBe(true)
  })

  it('acquires lock when available', async () => {
    let heldResolve: (() => void) | null = null as (() => void) | null
    const request = vi.fn(
      (_name: string, _opts: any, cb: any) =>
        new Promise<void>((resolve) => {
          heldResolve = resolve
          void cb({ name: _name })
        }),
    )
    // @ts-expect-error 注入 mock
    navigator.locks = { request }
    const sid = ref('s1')
    const { isOwner, release } = useSessionSendLock(sid)
    await new Promise((r) => setTimeout(r, 0))
    expect(request).toHaveBeenCalledWith(
      'neurova-chat-send:s1',
      { ifAvailable: true },
      expect.any(Function),
    )
    expect(isOwner.value).toBe(true)
    release()
    heldResolve?.()
  })

  it('switches session releases old lock and reacquires', async () => {
    const request = vi.fn(async (_n: string, _o: any, cb: any) => {
      await cb({ name: _n })
      return undefined
    })
    // @ts-expect-error 注入 mock
    navigator.locks = { request }
    const sid = ref('s1')
    useSessionSendLock(sid)
    await new Promise((r) => setTimeout(r, 0))
    sid.value = 's2'
    await new Promise((r) => setTimeout(r, 0))
    expect(request).toHaveBeenCalledWith(
      'neurova-chat-send:s2',
      { ifAvailable: true },
      expect.any(Function),
    )
  })

  it('marks non-owner when lock unavailable', async () => {
    const request = vi.fn(async (_n: string, _o: any, cb: any) => {
      await cb(null) // 锁被占
      return undefined
    })
    // @ts-expect-error 注入 mock
    navigator.locks = { request }
    const sid = ref('s1')
    const { isOwner } = useSessionSendLock(sid)
    await new Promise((r) => setTimeout(r, 0))
    expect(isOwner.value).toBe(false)
  })
})
