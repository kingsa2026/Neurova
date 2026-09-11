import { ref } from 'vue'
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
      status: 'running',
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

export function useSubAgentWindows() {
  return { subAgentWindows, handleSubAgentSyncEvent, closeSubAgentWindow, clearSubAgentWindows }
}
