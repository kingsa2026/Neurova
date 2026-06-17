import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import type { Agent, AgentConfig } from '@/types/agent'

// ---------------------------------------------------------------------------
// Helper: map snake_case API response to camelCase Agent
// ---------------------------------------------------------------------------
function mapAgentResponse(raw: Record<string, any>): Agent {
  const config = raw.config || {}
  return {
    id: raw.id ?? raw.agent_id,
    name: raw.name,
    description: raw.description ?? '',
    model: raw.model ?? config.model ?? '',
    provider: raw.provider ?? config.provider ?? '',
    status: raw.status ?? 'inactive',
    avatar: raw.avatar ?? null,
    createdAt: raw.created_at ?? raw.createdAt ?? '',
    updatedAt: raw.updated_at ?? raw.updatedAt ?? '',
    config: {
      systemPrompt: config.system_prompt ?? config.systemPrompt ?? '',
      temperature: config.temperature ?? 0.7,
      maxTokens: config.max_tokens ?? config.maxTokens ?? 4096,
      topP: config.top_p ?? config.topP ?? 1.0,
      ttsEnabled: config.tts_enabled ?? config.ttsEnabled ?? false,
      ttsVoice: config.tts_voice ?? config.ttsVoice ?? '',
      ttsSpeed: config.tts_speed ?? config.ttsSpeed ?? 1.0,
      ttsPitch: config.tts_pitch ?? config.ttsPitch ?? 1.0,
      tools: config.tools ?? [],
      skills: config.skills ?? [],
    },
    stats: raw.stats
      ? {
          totalConversations: raw.stats.total_conversations ?? raw.stats.totalConversations ?? 0,
          totalMessages: raw.stats.total_messages ?? raw.stats.totalMessages ?? 0,
          totalTokens: raw.stats.total_tokens ?? raw.stats.totalTokens ?? 0,
          avgResponseTime: raw.stats.avg_response_time ?? raw.stats.avgResponseTime ?? 0,
          lastActiveAt: raw.stats.last_active_at ?? raw.stats.lastActiveAt ?? undefined,
        }
      : undefined,
  }
}

/**
 * Map a camelCase AgentConfig back to snake_case for API requests.
 */
function mapConfigToApi(config: Partial<AgentConfig>): Record<string, any> {
  return {
    system_prompt: config.systemPrompt,
    temperature: config.temperature,
    max_tokens: config.maxTokens,
    top_p: config.topP,
    tts_enabled: config.ttsEnabled,
    tts_voice: config.ttsVoice,
    tts_speed: config.ttsSpeed,
    tts_pitch: config.ttsPitch,
    tools: config.tools,
    skills: config.skills,
  }
}

export const useAgentStore = defineStore('agents', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const agents = ref<Agent[]>([])
  const currentAgentId = ref<string | null>(null)
  const loading = ref<boolean>(false)
  const error = ref<string | null>(null)

  /**
   * Three-level isolation context.
   *
   * The backend composes a composite key of (agent_id, neuser_id, user_id).
   * neuser_id and user_id are derived from the JWT on the server side via
   * deps.py; the frontend is only responsible for supplying agent_id.
   *
   * Pages can read `isolationContext.agent_id` to display the active
   * isolation scope or pass it in API calls.
   */
  const isolationContext = ref<{ agent_id: string | null }>({ agent_id: null })

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------
  const currentAgent = computed<Agent | undefined>(() =>
    agents.value.find((a) => a.id === currentAgentId.value),
  )

  const agentOptions = computed(() =>
    agents.value.map((a) => ({
      label: a.name,
      value: a.id,
    })),
  )

  /**
   * Returns the agent_id portion of the three-level isolation key.
   * Useful as a shorthand when pages need to display or log the current scope.
   */
  const currentIsolationKey = computed<string | null>(() => isolationContext.value.agent_id)

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  /**
   * Load the full agent list from the API.
   */
  async function loadAgents(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res: any = await api.get('/agents')
      const data = res?.data ?? res
      const list = Array.isArray(data) ? data : data?.items ?? data?.agents ?? []
      agents.value = list.map(mapAgentResponse)

      // Auto-select default agent if none selected
      if (!currentAgentId.value && agents.value.length > 0) {
        const defaultAgent = agents.value.find(a => a.id === 'default' || a.name === 'neurova') ?? agents.value[0]
        setCurrentAgent(defaultAgent.id)
      }
    } catch (err: any) {
      error.value = err?.response?.data?.message || err?.message || 'Failed to load agents.'
      console.error('[AgentStore] loadAgents error:', err)
    } finally {
      loading.value = false
    }
  }

  /**
   * Create a new agent.
   */
  async function createAgent(payload: {
    name: string
    description?: string
    model?: string
    provider?: string
    config?: Partial<AgentConfig>
  }): Promise<Agent | null> {
    loading.value = true
    error.value = null
    try {
      const body: Record<string, any> = {
        name: payload.name,
        description: payload.description,
        model: payload.model,
        provider: payload.provider,
      }
      if (payload.config) {
        body.config = mapConfigToApi(payload.config)
      }
      const res: any = await api.post('/agents', body)
      const data = res?.data ?? res
      const newAgent = mapAgentResponse(data)
      agents.value.push(newAgent)
      return newAgent
    } catch (err: any) {
      error.value = err?.response?.data?.message || err?.message || 'Failed to create agent.'
      console.error('[AgentStore] createAgent error:', err)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Update an existing agent.
   */
  async function updateAgent(
    agentId: string,
    payload: {
      name?: string
      description?: string
      model?: string
      provider?: string
      config?: Partial<AgentConfig>
    },
  ): Promise<Agent | null> {
    loading.value = true
    error.value = null
    try {
      const body: Record<string, any> = { ...payload }
      if (payload.config) {
        body.config = mapConfigToApi(payload.config)
      }
      const res: any = await api.put(`/agents/${agentId}`, body)
      const data = res?.data ?? res
      const updated = mapAgentResponse(data)
      const idx = agents.value.findIndex((a) => a.id === agentId)
      if (idx !== -1) {
        agents.value[idx] = updated
      }
      return updated
    } catch (err: any) {
      error.value = err?.response?.data?.message || err?.message || 'Failed to update agent.'
      console.error('[AgentStore] updateAgent error:', err)
      return null
    } finally {
      loading.value = false
    }
  }

  /**
   * Delete an agent by ID.
   */
  async function deleteAgent(agentId: string): Promise<boolean> {
    loading.value = true
    error.value = null
    try {
      await api.delete(`/agents/${agentId}`)
      agents.value = agents.value.filter((a) => a.id !== agentId)
      if (currentAgentId.value === agentId) {
        currentAgentId.value = null
        isolationContext.value = { agent_id: null }
      }
      return true
    } catch (err: any) {
      error.value = err?.response?.data?.message || err?.message || 'Failed to delete agent.'
      console.error('[AgentStore] deleteAgent error:', err)
      return false
    } finally {
      loading.value = false
    }
  }

  /**
   * Set the currently active agent by ID.
   * Also updates the isolation context so that all pages have access
   * to the current agent_id portion of the three-level isolation key.
   */
  function setCurrentAgent(agentId: string): void {
    currentAgentId.value = agentId
    isolationContext.value = { agent_id: agentId }
  }

  /**
   * Get the full config for an agent (from local state or fetch from API).
   */
  async function getAgentConfig(agentId: string): Promise<AgentConfig | null> {
    // Try local state first
    const local = agents.value.find((a) => a.id === agentId)
    if (local?.config) return local.config

    // Fetch from API
    try {
      const res: any = await api.get(`/agents/${agentId}/config`)
      const data = res?.data ?? res
      if (data && typeof data === 'object') {
        return {
          systemPrompt: data.system_prompt ?? data.systemPrompt ?? '',
          temperature: data.temperature ?? 0.7,
          maxTokens: data.max_tokens ?? data.maxTokens ?? 4096,
          topP: data.top_p ?? data.topP ?? 1.0,
          ttsEnabled: data.tts_enabled ?? data.ttsEnabled ?? false,
          ttsVoice: data.tts_voice ?? data.ttsVoice ?? '',
          ttsSpeed: data.tts_speed ?? data.ttsSpeed ?? 1.0,
          ttsPitch: data.tts_pitch ?? data.ttsPitch ?? 1.0,
          tools: data.tools ?? [],
          skills: data.skills ?? [],
        }
      }
      return null
    } catch (err: any) {
      error.value = err?.response?.data?.message || err?.message || 'Failed to get agent config.'
      console.error('[AgentStore] getAgentConfig error:', err)
      return null
    }
  }

  return {
    // state
    agents,
    currentAgentId,
    isolationContext,
    loading,
    error,
    // computed
    currentAgent,
    agentOptions,
    currentIsolationKey,
    // actions
    loadAgents,
    createAgent,
    updateAgent,
    deleteAgent,
    setCurrentAgent,
    getAgentConfig,
  }
})
