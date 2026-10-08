import { ref } from 'vue'
import { api } from '@/api'
import type { SubAgentWindowState } from '@/components/chat/SubAgentPanel.vue'

/**
 * 蜂群子 Agent 浮窗栈状态（2026-09-08 ChatPage 拆分产物）。
 *
 * 会话 WS 事件（subagent_started/chunk/completed）驱动的浮动小窗；
 * 模块级单例状态：SSE/WS 处理器（页面编排层）与 SubAgentWindowStack
 * 组件共享同一窗口表。
 *
 * P2-15（审计 2026-09-11）：chunks 数组改为「bodyText 累积字符串 + chunkCount
 * 计数」——原实现每 chunk push 对象且 SubAgentPanel 每 chunk 对全文重 join
 * （流内 O(n²)）；completed/failed 窗口超时自动回收，会话/Agent 切换由
 * ChatPage 调 clearSubAgentWindows() 整栈回收。
 */

const subAgentWindows = ref<Record<string, SubAgentWindowState>>({})

/** completed/failed 窗口的回收定时器（按 subagent_id） */
const recycleTimers = new Map<string, ReturnType<typeof setTimeout>>()
/** completed/failed 窗口保留时长：给用户读完报告的时间，过后自动回收 */
const COMPLETED_TTL_MS = 120_000

function clearRecycleTimer(subagentId: string): void {
  const t = recycleTimers.get(subagentId)
  if (t) {
    clearTimeout(t)
    recycleTimers.delete(subagentId)
  }
}

/**
 * 消费 subagent_* WS 事件；返回 true 表示事件已被本处理器消费
 * （computer_action 等非 subagent 事件返回 false，由调用方继续分派）。
 */
function handleSubAgentSyncEvent(event: { event_type: string; payload: Record<string, unknown> }): boolean {
  const p = event.payload as Record<string, string>
  const sid = p?.subagent_id
  if (!sid) return false
  if (event.event_type === 'subagent_started') {
    clearRecycleTimer(sid)
    subAgentWindows.value[sid] = {
      subagentId: sid,
      agentName: p.agent_name || sid,
      task: p.task || '',
      bodyText: '',
      chunkCount: 0,
      // 状态取自事件本身（改前这里硬编码 'running'：那一刻后端确实是 running，
      // 但事件不带事实，竞态或重放时前端只能一直猜）。词值到 UI 态的翻译只有
      // LEDGER_TO_WINDOW_STATUS 一处——事件先于后端扩态也不会渲染成未定义态。
      status: LEDGER_TO_WINDOW_STATUS[String(p.status ?? '')] ?? 'running',
      report: '',
    }
  } else if (event.event_type === 'subagent_chunk') {
    const win = subAgentWindows.value[sid]
    if (win && p.data !== undefined) {
      // 增量追加：拼接成本摊到每次 chunk 的追加本身，不再全量重拼
      win.bodyText += String(p.data)
      win.chunkCount++
    }
  } else if (event.event_type === 'subagent_completed') {
    const win = subAgentWindows.value[sid]
    if (win) {
      win.status = (p.status as SubAgentWindowState['status']) || 'completed'
      win.report = String(p.report || '')
      win.error = p.error || null
      // completed/failed 窗口超时自动回收（重新 started 会清掉定时器）
      clearRecycleTimer(sid)
      recycleTimers.set(
        sid,
        setTimeout(() => {
          recycleTimers.delete(sid)
          if (subAgentWindows.value[sid]?.status !== 'running') {
            delete subAgentWindows.value[sid]
          }
        }, COMPLETED_TTL_MS),
      )
    }
  } else {
    return false
  }
  return true
}

function closeSubAgentWindow(subagentId: string): void {
  clearRecycleTimer(subagentId)
  delete subAgentWindows.value[subagentId]
}

/** 会话/Agent 切换：整栈回收（含待回收定时器与仍在运行的窗口） */
function clearSubAgentWindows(): void {
  recycleTimers.clear()
  subAgentWindows.value = {}
}

/**
 * 台账状态 → 窗口状态（唯一一处映射）。词值表与后端 `agent_run_store` 对齐，
 * 对齐由 `tests/unit/api/test_agentRunStatusVocabularyParity.py` 钉住——
 * 后端加一个状态而这里没跟上，就是"窗口永远转圈"或"悄悄标完成"的下一场事故。
 */
export const LEDGER_TO_WINDOW_STATUS: Record<string, SubAgentWindowState['status']> = {
  queued: 'running',
  running: 'running',
  parked: 'running',
  completed: 'completed',
  failed: 'failed',
  cancelled: 'failed',
}

/**
 * 从 run 台账读面回填浮窗栈（§6-78 L 条：刷新/重启后子任务历史必须还在）。
 *
 * 数据源是 `GET /console/chat/runs?scope=subagents`——即"这次对话派出去了哪些子任务"，
 * 与 `loadParkedRuns` 同一条读面、同一套归属判定，不另开第二条查询口。
 * 读面故障（含 `NEUROVA_RUN_GATE=off` 的 503）只留痕不回填：**绝不拿空列表冒充"没派过**"。
 */
export async function restoreSubAgentWindows(
  sessionId: string,
  isActive: () => boolean = () => true,
): Promise<void> {
  if (!sessionId) return
  let runs: any[]
  try {
    const res: any = await api.get('/console/chat/runs', {
      params: { session_id: sessionId, scope: 'subagents' },
    })
    runs = res?.data?.runs ?? res?.runs ?? []
  } catch (e) {
    console.warn('[subagent] 台账读面不可用，浮窗不回填（不拿空列表冒充没有历史）:', e)
    return
  }
  // 过期响应不写当前视图：切会话后上一条 fetch 才回来的话，会把旧会话的子任务
  // 摆到新会话的浮窗里（与 ChatPage.loadParkedRuns 同一条纪律）
  if (!isActive()) return
  for (const row of runs) {
    const sid: string = row?.subagent_id
    if (!sid) continue
    clearRecycleTimer(sid)
    const status = LEDGER_TO_WINDOW_STATUS[String(row?.status ?? '')] ?? 'running'
    subAgentWindows.value[sid] = {
      subagentId: sid,
      agentName: row?.agent_id || sid,
      task: row?.task || '',
      bodyText: '',
      chunkCount: 0,
      status,
      report: '',
      error: row?.error_type || null,
    }
    if (status !== 'running') {
      recycleTimers.set(
        sid,
        setTimeout(() => {
          recycleTimers.delete(sid)
          if (subAgentWindows.value[sid]?.status !== 'running') {
            delete subAgentWindows.value[sid]
          }
        }, COMPLETED_TTL_MS),
      )
    }
  }
}

export function useSubAgentWindows() {
  return { subAgentWindows, handleSubAgentSyncEvent, closeSubAgentWindow, clearSubAgentWindows }
}
