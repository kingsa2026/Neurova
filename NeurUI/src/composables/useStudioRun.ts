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
