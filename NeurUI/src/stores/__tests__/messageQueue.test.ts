/**
 * messageQueue store 状态机测试（补课 P3-b：消息队列）。
 *
 * 契约：
 * - 流式中发送 → enqueue；done 后 next() 出队续发
 * - pending → sending → sent(出队) | failed；failed 可 retry 回 pending
 * - sending 不可移除；updateText 仅 pending
 * - 暂停开关只影响自动续发，不改变队列内容
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useMessageQueueStore } from '@/stores/messageQueue'

describe('messageQueue store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('enqueue adds pending item with trimmed text', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('  hello  ')
    expect(item.status).toBe('pending')
    expect(item.text).toBe('hello')
    expect(q.pendingCount).toBe(1)
    expect(q.hasPending).toBe(true)
  })

  it('next returns first pending without dequeue', () => {
    const q = useMessageQueueStore()
    q.enqueue('a')
    q.enqueue('b')
    expect(q.next()?.text).toBe('a')
    expect(q.pendingCount).toBe(2)
  })

  it('sending → sent removes from queue', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('a')
    expect(q.markSending(item.id)).toBe(true)
    expect(q.next()).toBeUndefined() // sending 不再是 pending
    q.markSent(item.id)
    expect(q.items).toHaveLength(0)
  })

  it('sending → failed → retry → pending', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('a')
    q.markSending(item.id)
    q.markFailed(item.id, 'network down')
    const failed = q.items.find((i) => i.id === item.id)
    expect(failed?.status).toBe('failed')
    expect(failed?.error).toBe('network down')
    expect(q.retry(item.id)).toBe(true)
    expect(q.next()?.id).toBe(item.id)
    expect(q.next()?.error).toBeUndefined()
  })

  it('sending cannot be removed', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('a')
    q.markSending(item.id)
    expect(q.remove(item.id)).toBe(false)
    expect(q.items).toHaveLength(1)
  })

  it('updateText only works on pending', () => {
    const q = useMessageQueueStore()
    const item = q.enqueue('a')
    expect(q.updateText(item.id, 'edited')).toBe(true)
    expect(q.next()?.text).toBe('edited')
    q.markSending(item.id)
    expect(q.updateText(item.id, 'nope')).toBe(false)
    expect(q.items[0].text).toBe('edited')
  })

  it('clear keeps sending item', () => {
    const q = useMessageQueueStore()
    const a = q.enqueue('a')
    const b = q.enqueue('b')
    q.markSending(a.id)
    q.markFailed(b.id)
    q.clear()
    expect(q.items).toHaveLength(1)
    expect(q.items[0].id).toBe(a.id)
  })

  it('pause is just a flag', () => {
    const q = useMessageQueueStore()
    expect(q.paused).toBe(false)
    q.setPaused(true)
    expect(q.paused).toBe(true)
  })
})

describe('messageQueue reorder / moveToTop（补课 A3）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('moveToTop puts item at pending queue head', () => {
    const q = useMessageQueueStore()
    q.enqueue('a')
    const b = q.enqueue('b')
    expect(q.next()?.text).toBe('a')
    expect(q.moveToTop(b.id)).toBe(true)
    expect(q.next()?.text).toBe('b')
    // a 仍在队列中
    expect(q.pendingCount).toBe(2)
  })

  it('reorder reorders pending items, keeping non-pending pinned', () => {
    const q = useMessageQueueStore()
    const a = q.enqueue('a')
    const b = q.enqueue('b')
    const c = q.enqueue('c')
    q.markSending(a.id)
    q.reorder([c.id, b.id])
    const pending = q.items.filter((i) => i.status === 'pending')
    expect(pending.map((i) => i.text)).toEqual(['c', 'b'])
    // sending 项仍在队里
    expect(q.items.some((i) => i.id === a.id)).toBe(true)
    expect(c.id).toBeDefined()
  })

  it('reorder ignores unknown ids', () => {
    const q = useMessageQueueStore()
    q.enqueue('a')
    q.reorder(['ghost-id'])
    expect(q.items.filter((i) => i.status === 'pending')).toHaveLength(1)
  })
})
