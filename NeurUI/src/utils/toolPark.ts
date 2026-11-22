/**
 * U8 工具 park 轮询（SSH/shell 长命令迟交结果）。
 *
 * 后端超 park 软阈值返回 {parked:true, park_id, poll_after, max_wait_s} 信封
 * （tool_executor._parkedToolExecution）；前端凭 park_id 按 poll_after 间隔
 * 轮询 GET /v1/tools/park/{park_id}，completed/failed 终态返回。
 * 轮询有次数上限（max_wait_s/间隔 + 余量，绝对上限 400 次）——超限诚实失败，
 * 不无限挂起；404（park_id 不存在/过期）立即失败。
 */
import { getParkedToolResult } from '@/api/modules/tools'

export interface ParkedEnvelope {
  parkId: string
  pollAfterSec: number
  maxWaitSec: number
}

/** tool_result 文本 → park 信封（非 parked 信封/非 JSON/缺 park_id → null） */
export function parseParkedEnvelope(resultText?: string | null): ParkedEnvelope | null {
  if (!resultText) return null
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(String(resultText)) as Record<string, unknown>
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null
  if (parsed.parked !== true || typeof parsed.park_id !== 'string' || !parsed.park_id) return null
  return {
    parkId: parsed.park_id,
    pollAfterSec:
      typeof parsed.poll_after === 'number' && parsed.poll_after > 0 ? parsed.poll_after : 2,
    maxWaitSec:
      typeof parsed.max_wait_s === 'number' && parsed.max_wait_s > 0 ? parsed.max_wait_s : 800,
  }
}

export interface ParkPollOutcome {
  status: 'completed' | 'failed'
  data: Record<string, unknown>
}

type FetchFn = (parkId: string) => Promise<unknown>

/**
 * 轮询 park 结果直到终态（completed/failed）。
 *
 * maxAttempts 缺省 = ceil(max_wait_s*1000/interval) + 5（余量吸收网络抖动），
 * 绝对上限 400 次；瞬时网络错误继续轮询，404 与超限抛错。
 */
export async function pollParkedResult(
  park: ParkedEnvelope,
  opts: { intervalMs?: number; maxAttempts?: number; fetch?: FetchFn } = {},
): Promise<ParkPollOutcome> {
  const fetchFn = opts.fetch ?? getParkedToolResult
  const intervalMs = opts.intervalMs ?? Math.max(1000, park.pollAfterSec * 1000)
  const maxAttempts =
    opts.maxAttempts ?? Math.min(400, Math.ceil((park.maxWaitSec * 1000) / intervalMs) + 5)
  let lastError = ''
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (attempt > 0) await delay(intervalMs)
    try {
      const resp: any = await fetchFn(park.parkId)
      const data = (resp?.data?.data ?? resp?.data ?? {}) as Record<string, unknown>
      if (data.status === 'completed' || data.status === 'failed') {
        return { status: data.status, data }
      }
      lastError = String(data.error || '')
    } catch (e: any) {
      if (e?.response?.status === 404) {
        throw new Error(`park_id 不存在或已过期: ${park.parkId}`)
      }
      lastError = String(e?.message || e)
    }
  }
  throw new Error(lastError || `park 轮询超限（${maxAttempts} 次）: ${park.parkId}`)
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
