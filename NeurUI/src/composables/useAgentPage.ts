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
export function useAgentPage(options?: { onAgentChange?: (newAgentId: string) => void }) {
  const route = useRoute()
  const agentStore = useAgentStore()

  // Resolve agentId from route params or fall back to the store's current agent
  const agentId = ref<string>(
    (route.params.agentId as string) || agentStore.currentAgentId || '',
  )

  // The full Agent object from the store (reactive)
  const currentAgent = computed<Agent | undefined>(() =>
    agentId.value
      ? agentStore.agents.find((a) => a.id === agentId.value)
      : undefined,
  )

  // Whether the agent data is still loading
  const agentLoading = computed(() => agentStore.loading)

  // Keep agentId in sync when route params change (e.g. navigating between agents)
  watch(
    () => route.params.agentId,
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
