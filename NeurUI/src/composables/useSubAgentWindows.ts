import { ref } from 'vue'
import type { SubAgentWindowState } from '@/components/chat/SubAgentPanel.vue'

/**
 * 蜂群子 Agent 浮窗栈状态（2026-09-08 ChatPage 拆分产物）。
 *
 * 会话 WS 事件（subagent_started/chunk/completed）驱动的浮动小窗；
 * 模块级单例状态：SSE/WS 处理器（页面编排层）与 SubAgentWindowStack
 * 组件共享同一窗口表。
 */

const subAgentWindows = ref<Record<string, SubAgentWindowState>>({})

/**
 * 消费 subagent_* WS 事件；返回 true 表示事件已被本处理器消费
 * （computer_action 等非 subagent 事件返回 false，由调用方继续分派）。
 */
function handleSubAgentSyncEvent(event: { event_type: string; payload: Record<string, unknown> }): boolean {
  const p = event.payload as Record<string, string>
  const sid = p?.subagent_id
  if (!sid) return false
  if (event.event_type === 'subagent_started') {
    subAgentWindows.value[sid] = {
      subagentId: sid,
      agentName: p.agent_name || sid,
      task: p.task || '',
      chunks: [],
      status: 'running',
      report: '',
    }
  } else if (event.event_type === 'subagent_chunk') {
    const win = subAgentWindows.value[sid]
    if (win && p.data !== undefined) {
      win.chunks.push({ type: String(p.chunk_type || 'content'), data: String(p.data) })
    }
  } else if (event.event_type === 'subagent_completed') {
    const win = subAgentWindows.value[sid]
    if (win) {
      win.status = (p.status as SubAgentWindowState['status']) || 'completed'
      win.report = String(p.report || '')
      win.error = p.error || null
    }
  } else {
    return false
  }
  return true
}

function closeSubAgentWindow(subagentId: string): void {
  delete subAgentWindows.value[subagentId]
}

export function useSubAgentWindows() {
  return { subAgentWindows, handleSubAgentSyncEvent, closeSubAgentWindow }
}
