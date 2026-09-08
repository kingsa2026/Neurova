/**
 * 队列续发 runner（审计①③⑯ 修复，2026-09-08）。
 *
 * 从 ChatPage 抽出为可测模块，修三个审计项：
 * - ① P0 续发死锁：旧实现 drain 设 _draining=true 后 await sendMessage，
 *   sendMessage finally 的递归 drain 被守卫吞掉、外层复位退出——排队 ≥2 条
 *   只自动发 1 条。新实现：单层 while 循环逐条续发；重入调用（sendMessage
 *   finally 仍会触发）降级为 no-op，由本循环驱动排空。
 * - ③ 会话隔离：drainer 构造时绑定发起会话（takeNext 已按会话过滤），
 *   流中切会话后本次 drain 只消费发起会话的排队项。
 * - ⑯ paused 语义：默认 drain（自动续发）尊重暂停直接返回；force 入口
 *   （用户点「立即」）只发送一条，后续续发仍尊重 paused。
 */

export interface QueueDrainDeps {
  /** 队列是否暂停（自动续发守卫） */
  isPaused: () => boolean
  /** 取下一条待发（不出队）；按 drainer 绑定的会话过滤 */
  takeNext: () => { id: string; text: string } | undefined
  /** 标记发送中（防重入；false=项已被移除/状态竞争，跳过） */
  markSending: (id: string) => boolean
  /** 发送成功出队 */
  markSent: (id: string) => void
  /** 发送失败转 failed 供重试 */
  markFailed: (id: string, error?: string) => void
  /** 发送一条排队文本（返回是否成功；失败以返回值或异常表达均可） */
  send: (text: string) => Promise<boolean>
}

export interface QueueDrainer {
  /** 排空当前会话队列；force=true 时忽略 paused 发送首条（显式「立即」）。 */
  drain: (force?: boolean) => Promise<void>
  /** 是否正在排空（供外部 UI/守卫参考）。 */
  isDraining: () => boolean
}

export function createQueueDrainer(deps: QueueDrainDeps): QueueDrainer {
  let draining = false

  async function drain(force = false): Promise<void> {
    // 审计①：重入（sendMessage finally 递归触发）→ no-op。
    // 循环体自身会继续消费后续排队项，递归无必要。
    if (draining) return
    // 审计⑯：自动续发尊重 paused；显式 force 入口放行首条，
    // 但首条之后的续发仍尊重 paused（force 只作用于当次点击）
    if (!force && deps.isPaused()) return
    draining = true
    try {
      let allowForce = force
      let skipped = 0
      while (true) {
        if (!allowForce && deps.isPaused()) break
        const item = deps.takeNext()
        if (!item) break
        if (!deps.markSending(item.id)) {
          // 状态竞争（项被移除/已发送）。防病态死循环：takeNext 若不
          // 消费该项会一直返回同一条——连续跳过超过队列深度即退出
          skipped += 1
          if (skipped > 16) break
          continue
        }
        skipped = 0
        try {
          const ok = await deps.send(item.text)
          if (ok) deps.markSent(item.id)
          else deps.markFailed(item.id, 'send failed')
        } catch (err) {
          deps.markFailed(item.id, err instanceof Error ? err.message : String(err))
        }
        allowForce = false
      }
    } finally {
      draining = false
    }
  }

  return { drain, isDraining: () => draining }
}
