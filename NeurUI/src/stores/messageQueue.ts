/**
 * 消息队列 Pinia store（补课 P3-b：QP messageQueueStore 的 NV 轻量版）。
 *
 * 流式回复进行中用户再次发送 → 入队而非丢弃；当前轮 done 后自动出队续发。
 * 状态机：pending → sending → sent | failed；失败可 retry（回 pending）。
 * 仅承载文本轮（附件轮即时上传，不排队——QP 同款取舍的简化）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface QueuedMessage {
  /** 客户端生成 id（入队时刻毫秒+序号，仅前端队列标识） */
  id: string
  text: string
  /** 入队时刻 ISO（出队发送时转 client_timestamp 轮次定位键） */
  enqueuedAt: string
  status: 'pending' | 'sending' | 'failed'
  /** failed 时的错误摘要（retry 后清除） */
  error?: string
}

let seq = 0

export const useMessageQueueStore = defineStore('messageQueue', () => {
  const items = ref<QueuedMessage[]>([])
  /** 队列开关：暂停时不自动续发（新发送仍直接走即时链路） */
  const paused = ref(false)

  const pendingCount = computed(() => items.value.filter((i) => i.status === 'pending').length)
  const hasPending = computed(() => pendingCount.value > 0)

  /** 入队（流式中再次发送）。 */
  function enqueue(text: string): QueuedMessage {
    seq += 1
    const item: QueuedMessage = {
      id: `q${Date.now()}-${seq}`,
      text: text.trim(),
      enqueuedAt: new Date().toISOString(),
      status: 'pending',
    }
    items.value.push(item)
    return item
  }

  /** 取下一条待发（不出队——发送成功才移除，失败转 failed）。 */
  function next(): QueuedMessage | undefined {
    return items.value.find((i) => i.status === 'pending')
  }

  /** 标记发送中（防重入）。 */
  function markSending(id: string): boolean {
    const item = items.value.find((i) => i.id === id)
    if (!item || item.status !== 'pending') return false
    item.status = 'sending'
    return true
  }

  /** 发送成功 → 出队。 */
  function markSent(id: string): void {
    items.value = items.value.filter((i) => i.id !== id)
  }

  /** 发送失败 → failed（保留供 retry；当前轮的错误已就地展示）。 */
  function markFailed(id: string, error?: string): void {
    const item = items.value.find((i) => i.id === id)
    if (item) {
      item.status = 'failed'
      item.error = error
    }
  }

  /** failed → pending（重试）。 */
  function retry(id: string): boolean {
    const item = items.value.find((i) => i.id === id)
    if (!item || item.status !== 'failed') return false
    item.status = 'pending'
    item.error = undefined
    return true
  }

  /** 就地编辑 pending 文案。 */
  function updateText(id: string, text: string): boolean {
    const item = items.value.find((i) => i.id === id)
    if (!item || item.status !== 'pending') return false
    item.text = text.trim()
    return true
  }

  /** 重排 pending 项（补课 A3：QP reorder 语义；非 pending 位置不动）。 */
  function reorder(orderedIds: string[]): void {
    const byId = new Map(items.value.map((i) => [i.id, i]))
    const pendingOrdered = orderedIds
      .map((id) => byId.get(id))
      .filter((i): i is QueuedMessage => !!i && i.status === 'pending')
    const pendingIds = new Set(pendingOrdered.map((i) => i.id))
    // 未出现在 orderedIds 中的 pending 保持相对顺序追加在后
    const rest = items.value.filter(
      (i) => i.status === 'pending' && !pendingIds.has(i.id),
    )
    const nonPending = items.value.filter((i) => i.status !== 'pending')
    items.value = [...nonPending, ...pendingOrdered, ...rest]
  }

  /** 插队：把指定 pending 项移到队首（下一个被续发的就是它）。 */
  function moveToTop(id: string): boolean {
    const item = items.value.find((i) => i.id === id)
    if (!item || item.status !== 'pending') return false
    const rest = items.value.filter((i) => i.id !== id)
    const nonPending = rest.filter((i) => i.status !== 'pending')
    const pendings = rest.filter((i) => i.status === 'pending')
    items.value = [...nonPending, item, ...pendings]
    return true
  }

  /** 移除单条（pending/failed 均可；sending 不可移除）。 */
  function remove(id: string): boolean {
    const item = items.value.find((i) => i.id === id)
    if (!item || item.status === 'sending') return false
    items.value = items.value.filter((i) => i.id !== id)
    return true
  }

  /** 清空队列（仅 pending/failed；sending 不受影响）。 */
  function clear(): void {
    items.value = items.value.filter((i) => i.status === 'sending')
  }

  function setPaused(value: boolean): void {
    paused.value = value
  }

  return {
    items,
    paused,
    pendingCount,
    hasPending,
    enqueue,
    next,
    markSending,
    markSent,
    markFailed,
    retry,
    updateText,
    reorder,
    moveToTop,
    remove,
    clear,
    setPaused,
  }
})
