import { computed, watch, onUnmounted, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agents'

/**
 * Agent 级功能页面的通用 composable
 * 提供响应式的 agentId，自动响应路由参数和 store 变化
 *
 * 使用模式：
 * ```ts
 * const { agentId, initAgent } = useAgentPage('/agent/:agentId/chat', () => loadData())
 * onMounted(async () => { await initAgent(); loadData() })
 * ```
 *
 * 当用户通过 AgentSidebar 切换 agent 时，路由自动更新，
 * onAgentChange 回调自动触发，页面数据随之刷新。
 *
 * @param pagePath 页面路径模板，如 '/agent/:agentId/chat'
 * @param onAgentChange agent 变化时的回调（用于重新加载数据）
 * @returns 响应式的 agentId 和辅助函数
 */
export function useAgentPage(
  pagePath: string,
  onAgentChange?: (newAgentId: string) => void | Promise<void>
) {
  const route = useRoute()
  const router = useRouter()
  const agentStore = useAgentStore()

  // 响应式 agentId：优先从路由参数获取，其次从 store
  const agentId = computed(() => {
    const fromRoute = route.params.agentId as string
    const fromStore = agentStore.currentAgentId
    return fromRoute || fromStore || ''
  })

  // 标记是否已初始化，防止 store→route watch 在初始化时误触发
  let initialized = false

  // 监听路由参数变化 → 同步 store + 触发回调
  watch(
    () => route.params.agentId,
    (newAgentId, oldAgentId) => {
      if (newAgentId && typeof newAgentId === 'string') {
        // 同步 store
        agentStore.setCurrentAgent(newAgentId)
        // 仅在 agent 真正变化时（非首次挂载）触发回调
        // 首次挂载由 onMounted 中的 loadData() 负责
        if (initialized && newAgentId !== oldAgentId && onAgentChange) {
          onAgentChange(newAgentId)
        }
      }
    },
  )

  // 监听 store 变化 → 同步路由（仅在初始化完成后）
  watch(
    () => agentStore.currentAgentId,
    (newId) => {
      if (!initialized) return
      const routeAgentId = route.params.agentId as string
      if (newId && newId !== routeAgentId) {
        const newPath = pagePath.replace(':agentId', newId)
        router.push(newPath)
      }
    },
  )

  // 初始化：确保 agents 已加载且有默认选中
  async function initAgent() {
    if (!agentStore.agents.length) {
      await agentStore.loadAgents()
    }
    if (agentStore.agents.length && !agentId.value) {
      agentStore.setCurrentAgent(agentStore.agents[0].id)
    }
    initialized = true
  }

  return {
    agentId,
    agentStore,
    initAgent,
  }
}
