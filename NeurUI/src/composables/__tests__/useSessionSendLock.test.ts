/**
 * useSessionSendLock 测试（补课 A4：跨标签单发送者）。
 *
 * jsdom 无 navigator.locks——锁定逻辑用 mock 验证：ifAvailable 竞争、
 * 释放后接管、无 API 能力降级。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useSessionSendLock, resetSessionSendLockForTest } from '@/composables/useSessionSendLock'

describe('useSessionSendLock', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    resetSessionSendLockForTest()
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

  // ── 防回归（2026-09-09 新建会话发送按钮禁用根因）──────────────────
  // Web Locks 规范：navigator.locks.request() 返回 Promise<void>，resolve 值恒为
  // undefined（没有 handle）；抢锁失败的唯一信号是回调收到 lock === null。
  // 若把 resolve undefined 误判为"抢锁失败"，锁释放时 stale await 会把
  // isOwner 打成 false——新建会话（sid→null，只释放不再抢）后发送按钮恒禁用。

  /** 规范忠实 mock：request 恒 resolve undefined，且仅在回调返回的持锁 promise settle 后 resolve。 */
  function specFaithfulRequest() {
    return vi.fn(async (_n: string, _o: any, cb: any) => {
      await cb({ name: _n })
      return undefined
    })
  }

  it('keeps ownership after release (new-chat path, sid→null)', async () => {
    // @ts-expect-error 注入 mock
    navigator.locks = { request: specFaithfulRequest() }
    const sid = ref<string | null>('s1')
    const { isOwner } = useSessionSendLock(sid)
    await new Promise((r) => setTimeout(r, 0))
    expect(isOwner.value).toBe(true)
    sid.value = null // 新对话：useSessionOps.createSession() → setCurrentSession(null)
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))
    expect(isOwner.value).toBe(true)
  })

  it('keeps ownership after switching sessions (stale await must not clobber)', async () => {
    // @ts-expect-error 注入 mock
    navigator.locks = { request: specFaithfulRequest() }
    const sid = ref<string | null>('s1')
    const { isOwner } = useSessionSendLock(sid)
    await new Promise((r) => setTimeout(r, 0))
    expect(isOwner.value).toBe(true)
    sid.value = 's2'
    await new Promise((r) => setTimeout(r, 0))
    expect(isOwner.value).toBe(true)
  })
})
