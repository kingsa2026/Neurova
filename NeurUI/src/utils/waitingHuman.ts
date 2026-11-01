/**
 * 待人队列读数合并（N-3）。
 *
 * 两个来源各自完整、互不依赖：
 * - 桌面审计 needs_human：后端已给出计数与最久等待秒数；
 * - 治理审批待办：条目带 ISO created_at，最久等待在客户端按同一把尺算。
 *
 * 取**并集**而不是只取其一：只报审计会让「有审批卡着」看起来没人等；
 * 只报审批会让被拒/存疑的工具动作静默缺席。任一来源失败时保留另一来源，
 * 由调用方留痕，不在这里吞成 0。
 */
export interface WaitingHumanSource {
  count: number
  oldestWaitSeconds: number
}

export interface WaitingHumanSummary {
  count: number
  oldestWaitSeconds: number
}

export function mergeWaitingHuman(
  audit: WaitingHumanSource | null,
  approvalCreatedAts: Array<string | null | undefined> | null,
  nowMs: number = Date.now(),
): WaitingHumanSummary {
  const count = Math.max(0, Number(audit?.count ?? 0))
  let oldest = Math.max(0, Number(audit?.oldestWaitSeconds ?? 0))

  if (approvalCreatedAts) {
    let approvalCount = 0
    for (const createdAt of approvalCreatedAts) {
      if (!createdAt) continue
      const ts = Date.parse(createdAt)
      if (Number.isNaN(ts)) continue
      approvalCount += 1
      oldest = Math.max(oldest, Math.max(0, (nowMs - ts) / 1000))
    }
    return { count: count + approvalCount, oldestWaitSeconds: oldest }
  }

  return { count, oldestWaitSeconds: oldest }
}
