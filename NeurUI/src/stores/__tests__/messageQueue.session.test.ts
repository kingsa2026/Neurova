/**
 * 审计修复③：队列会话隔离——排队项必须绑定入队时会话。
 *
 * 旧形态：messageQueue 是全局扁平队列，切会话不清空 →
 * BUG-2 守卫跳过 drain 后排队项悬挂；之后在别的会话任何一次 drain
 * 都会把 A 会话排队的文本发进 B 会话（跨会话泄漏）。
 * 新契约：enqueue 携带 sessionId；next/pendingCount 按会话过滤；
 * 未传 sessionId 时退回全局语义（向后兼容）。
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useMessageQueueStore } from '../messageQueue'

describe('messageQueue session isolation（审计③）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useMessageQueueStore().clear()
  })

  it('enqueue 记录会话，next(sessionId) 只取本会话队首', () => {
    const q = useMessageQueueStore()
    q.enqueue('A 会话的排队', 'sA')
    q.enqueue('B 会话的排队', 'sB')

    expect(q.next('sA')?.text).toBe('A 会话的排队')
    expect(q.next('sB')?.text).toBe('B 会话的排队')
  })

  it('B 会话 drain 不消费 A 会话的排队项', () => {
    const q = useMessageQueueStore()
    q.enqueue('A 的消息', 'sA')
    q.enqueue('B 的消息', 'sB')

    const item = q.next('sB')
    expect(item).toBeTruthy()
    q.markSending(item!.id)
    q.markSent(item!.id)
    // A 的排队项仍在
    expect(q.next('sA')?.text).toBe('A 的消息')
    // B 已空
    expect(q.next('sB')).toBeUndefined()
  })

  it('pendingCount 按会话过滤', () => {
    const q = useMessageQueueStore()
    q.enqueue('A1', 'sA')
    q.enqueue('A2', 'sA')
    q.enqueue('B1', 'sB')
    expect(q.countPending('sA')).toBe(2)
    expect(q.countPending('sB')).toBe(1)
    expect(q.countPending()).toBe(3)
    expect(q.pendingCount).toBe(3)
  })

  it('未传 sessionId 时保持全局语义（向后兼容）', () => {
    const q = useMessageQueueStore()
    q.enqueue('X')
    q.enqueue('Y', 'sA')
    expect(q.next()?.text).toBe('X')
    expect(q.countPending()).toBe(2)
  })

  it('items 携带 sessionId 字段', () => {
    const q = useMessageQueueStore()
    q.enqueue('带会话', 's42')
    expect(q.items[0].sessionId).toBe('s42')
  })
})
