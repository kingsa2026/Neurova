import { ref, watch } from 'vue'
import { getSessionTakeoverState, recordHumanTakeover } from '@/api/modules/quality'

/**
 * 人工接管标记（D5 甲：控制台 producer）。
 * 状态以后端最近一条接管事件为准，切会话即重读；按钮点击只追加事实。
 */
export function useHumanTakeover(
  getSessionId: () => string | null | undefined,
  getAgentId: () => string | null | undefined,
) {
  const active = ref(false)
  const updating = ref(false)
  const stateError = ref<Error | null>(null)
  let revision = 0

  async function refresh(): Promise<void> {
    const revisionAtStart = ++revision
    const sessionId = getSessionId()
    if (!sessionId) {
      active.value = false
      return
    }
    try {
      const response = await getSessionTakeoverState(sessionId)
      if (revisionAtStart !== revision) return
      active.value = Boolean(response.data?.active)
      stateError.value = null
    } catch (err) {
      if (revisionAtStart !== revision) return
      active.value = false
      stateError.value = err instanceof Error ? err : new Error(String(err))
    }
  }

  watch(getSessionId, () => void refresh(), { immediate: true })

  async function toggle(): Promise<void> {
    const sessionId = getSessionId()
    if (!sessionId || updating.value) return
    const nextActive = !active.value
    const revisionAtStart = ++revision
    updating.value = true
    try {
      const response = await recordHumanTakeover({
        event_type: nextActive ? 'human_takeover_started' : 'human_takeover_ended',
        session_id: sessionId,
        agent_id: getAgentId() || '',
        source: 'console_mark',
        reason_code: 'console_toggle',
      })
      if (revisionAtStart !== revision) return
      active.value = response.data?.event_type === 'human_takeover_started'
      stateError.value = null
    } finally {
      updating.value = false
    }
  }

  return { active, updating, stateError, refresh, toggle }
}
