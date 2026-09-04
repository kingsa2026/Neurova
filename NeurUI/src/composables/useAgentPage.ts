import { ref, watch, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import type { Agent } from '@/types/agent'

/**
 * Composable for agent-scoped pages.
 *
 * Automatically extracts the `agentId` from route params, keeps it in sync
 * when the route changes, and exposes the current agent from the store.
 *
 * Usage:
 * ```vue
 * <script setup lang="ts">
 * import { useAgentPage } from '@/composables/useAgentPage'
 *
 * const { agentId, currentAgent, agentLoading } = useAgentPage()
 * </script>
 * ```
 */

/**
 * agentId 来源解析优先级：params.agentId > query.agentId > store 兜底。
 *
 * 背景：/agent/:agentId/chat 在 router 中 redirect 到 /chat 且把 agentId
 * 转入 query（?agentId=x），使 AgentList 点"对话"能进入对应智能体会话；
 * 普通 /chat 入口无 params/query，回落 agentStore.currentAgentId。
 * 空串/缺失按下一级回退。
 */
export function resolveAgentId(
  params: { agentId?: unknown } | undefined,
  query: { agentId?: unknown } | undefined,
  fallback: string,
): string {
  const p = params?.agentId
  if (typeof p === 'string' && p) return p
  const q = query?.agentId
  if (typeof q === 'string' && q) return q
  if (Array.isArray(q) && typeof q[0] === 'string' && q[0]) return q[0]
  return fallback
}

export function useAgentPage(options?: { onAgentChange?: (newAgentId: string) => void }) {
  const route = useRoute()
  const agentStore = useAgentStore()

  // Resolve agentId from route params/query or fall back to the store's current agent
  const agentId = ref<string>(
    resolveAgentId(
      route.params as Record<string, unknown>,
      route.query as Record<string, unknown>,
      agentStore.currentAgentId || '',
    ),
  )

  // The full Agent object from the store (reactive)
  const currentAgent = computed<Agent | undefined>(() =>
    agentId.value
      ? agentStore.agents.find((a) => a.id === agentId.value)
      : undefined,
  )

  // Whether the agent data is still loading
  const agentLoading = computed(() => agentStore.loading)

  // Keep agentId in sync when route params/query change (e.g. navigating between agents)
  watch(
    () => route.query.agentId,
    (newId) => {
      if (route.params?.agentId) return // params 优先, query 不覆盖
      const next = resolveAgentId(undefined, { agentId: newId }, agentId.value)
      if (next && next !== agentId.value) {
        agentId.value = next
        agentStore.setCurrentAgent(next)
      }
    },
  )

  watch(
    () => route.params?.agentId,
    (newId) => {
      if (newId && typeof newId === 'string') {
        agentId.value = newId
        agentStore.setCurrentAgent(newId)
      }
    },
  )

  // Keep agentId in sync when store changes (e.g. AgentSwitcher selection)
  watch(
    () => agentStore.currentAgentId,
    (newId) => {
      if (newId && newId !== agentId.value) {
        agentId.value = newId
      }
    },
  )

  // Fire onAgentChange callback whenever agentId changes (from any source)
  watch(agentId, (newId) => {
    if (newId && options?.onAgentChange) {
      options.onAgentChange(newId)
    }
  })

  // On mount, ensure agents are loaded and register the agentId as current
  onMounted(async () => {
    if (agentStore.agents.length === 0) {
      await agentStore.loadAgents()
    }
    if (agentId.value) {
      agentStore.setCurrentAgent(agentId.value)
    }
  })

  return {
    agentId,
    currentAgent,
    agentLoading,
  }
}
