/**
 * 创作专区后台任务轮询（R4）：/studio 长任务立即返回 run_id，
 * 状态经 GET /projects/{pid} 的 runs 列表投影，此处轮询至终态。
 */
import { getProject, type StudioRun } from '@/api/modules/studio'

const POLL_MS = 2500
const MAX_WAIT_MS = 10 * 60 * 1000

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
      if (run && (run.status === 'done' || run.status === 'failed')) return run
    } catch {
      /* 网络抖动继续轮 */
    }
    await new Promise((r) => setTimeout(r, POLL_MS))
  }
  return null
}
