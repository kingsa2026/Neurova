/**
 * 创作专区后台任务轮询（R4）：/studio 长任务立即返回 run_id，
 * 状态经 GET /projects/{pid} 的 runs 列表投影，此处轮询至终态。
 */
import { getProject, type StudioRun } from '@/api/modules/studio'

const POLL_MS = 2500
const MAX_WAIT_MS = 10 * 60 * 1000

/**
 * 终态集合：与生产侧写入点同源——`done`/`failed` 由 studio_api 的 wrapper 落
 * （`_spawn_run`），`done_with_fallback` 由 services 的抽取步落
 * （neurova/aigc_studio/services.py 的 `extract_assets`）。
 * 少认一个，前端就把一条已完成的任务一直 poll 到 10 分钟超时。
 */
const TERMINAL_STATUSES = new Set(['done', 'done_with_fallback', 'failed'])

type Translate = (key: string, named?: Record<string, unknown>) => string

/**
 * 把台账行里的批量读数说成人能看的一句（`detail_json` 的读侧）。
 *
 * 生产侧 `_settleRun` 每行都写三个固定键：`fallback_failed` / `fallback_blocked` /
 * `fallback`。前两个就是**决定这行是不是 `done_with_fallback` 的那两个数**，前端只取用、
 * 不重算——把 `blocked_*` 的归并在这儿再抄一遍即同一口径两份定义。
 * 老行没有这些键，退回台账自身的成因文本（`error`），不让警示条空转。
 */
export function describeRunOutcome(run: StudioRun, t: Translate): string {
  let facts: Record<string, unknown> = {}
  try {
    facts = JSON.parse(run.detail_json || '{}') as Record<string, unknown>
  } catch {
    /* 半截 JSON 不该让状态面报错，按无读数处理 */
  }
  const parts: string[] = []
  const failed = Number(facts.fallback_failed) || 0
  const blocked = Number(facts.fallback_blocked) || 0
  if (failed) parts.push(t('studio.runPartialFailed', { n: failed }))
  if (blocked) parts.push(t('studio.runPartialBlocked', { n: blocked }))
  const cause = String(facts.fallback || '')
  if (cause) parts.push(cause)
  return parts.length ? parts.join('; ') : (run.error || '')
}

export async function waitStudioRun(
  pid: string,
  runId: string,
  opts: { onTick?: (run: StudioRun | null) => void; signal?: { cancelled: boolean } } = {},
): Promise<StudioRun | null> {
  const deadline = Date.now() + MAX_WAIT_MS
  while (Date.now() < deadline) {
    if (opts.signal?.cancelled) return null
    try {
      const res: any = await getProject(pid)
      const runs: StudioRun[] = res?.data?.runs ?? []
      const run = runs.find((r) => r.id === runId) ?? null
      opts.onTick?.(run)
      if (run && TERMINAL_STATUSES.has(run.status)) return run
    } catch {
      /* 网络抖动继续轮 */
    }
    await new Promise((r) => setTimeout(r, POLL_MS))
  }
  return null
}
