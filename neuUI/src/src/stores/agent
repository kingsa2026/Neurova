import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { request } from '@/api'
import type { Agent } from '@/types/agent'
import type { RawAgentData, RawAgentConfig, AgentConfig } from '@/types/api'
&nbsp;
export const useAgentStore = defineStore('agents', () =&gt; {
  const agents = ref&lt;Agent[]&gt;([])
  const currentAgentId = ref&lt;string&gt;(localStorage.getItem('currentAgentId') || '')
  const loading = ref&lt;boolean&gt;(false)
  const error = ref&lt;string | null&gt;(null)
&nbsp;
  const currentAgent = computed(() =&gt;
    agents.value.find(agent =&gt; agent.id === currentAgentId.value || agent.agentId === currentAgentId.value)
  )
&nbsp;
  const agentOptions = computed(() =&gt;
    agents.value.map(agent =&gt; ({ label: agent.name, value: agent.id || agent.agentId }))
  )
&nbsp;
  async function loadAgents() {
    loading.value = true
    error.value = null
    try {
      const response = await request.get&lt;{ agents?: RawAgentData[] } &amp; RawAgentData[]&gt;('/agents')
      if (response.code === 0) {
        const rawAgents = (Array.isArray(response.data) ? response.data : response.data?.agents) || []
        // 规范化字段名：agent_id → id，并映射TTS配置
        agents.value = rawAgents.map((a) =&gt; ({
          id: a.agent_id || a.id,
          agentId: a.agent_id || a.id,
          name: a.name || '',
          description: a.description || '',
          llmModel: a.llm_model || '',
          llmProvider: a.llm_provider || '',
          // 个性和宪法字段
          personality: a.personality || '',
          constitution: a.constitution || '',
          status: a.status || 'active',
          memoryCount: a.memory_count || 0,
          skillCount: a.skill_count || 0,
          // TTS 配置（扁平化字段）
          tts_enabled: a.tts_enabled,
          tts_voice: a.tts_voice || 'female',
          tts_speed: a.tts_speed || 1.0,
          tts_pitch: a.tts_pitch || 1.0,
          // TTS 配置（嵌套结构，用于兼容性）
          ttsConfig: {
            enabled: a.tts_enabled ?? false,
            voiceType: a.tts_voice || 'female',
            speed: a.tts_speed || 1.0,
            pitch: a.tts_pitch || 1.0,
          },
        }))
        if ((!currentAgentId.value || !agents.value.some(a =&gt; a.agentId === currentAgentId.value)) &amp;&amp; agents.value.length &gt; 0) {
          setCurrentAgent(agents.value[0].agentId)
        }
      } else {
        error.value = response.message || '加载失败'
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } }; message?: string }
      error.value = error.response?.data?.message || error.message || '加载 Agent 列表失败'
    } finally {
      loading.value = false
    }
  }
&nbsp;
  async function getAgentConfig(agentId: string): Promise&lt;AgentConfig | null&gt; {
    loading.value = true
    error.value = null
    try {
      const response = await request.get&lt;RawAgentConfig&gt;(`/agents/${agentId}/config`)
      if (response.code === 0) {
        const config = response.data as RawAgentConfig
        // 映射字段名：snake_case → camelCase
        return {
          agentId: config.agent_id || '',
          name: config.name || '',
          description: config.description || '',
          workspacePath: config.workspace_path || '',
          personality: config.personality || '',
          constitution: config.constitution || '',
          llmProvider: config.llm_provider || '',
          llmModel: config.llm_model || 'auto',
          llmBaseUrl: config.llm_base_url || '',
          llmTemperature: config.llm_temperature || 0.7,
          maxTokens: config.max_tokens || 2000,
          enableMemory: config.enable_memory !== undefined ? config.enable_memory : true,
          enableStreaming: config.enable_streaming || false,
          ttsEnabled: config.tts_enabled || false,
          ttsVoice: config.tts_voice || 'female',
          ttsSpeed: config.tts_speed || 1.0,
          ttsPitch: config.tts_pitch || 1.0,
          // 对话显示配置
          showThinking: config.show_thinking !== false,
          showToolMessages: config.show_tool_messages !== false,
          // 保留原始数据（可能包含其他字段）
          _raw: config
        }
      } else {
        error.value = response.message || '获取配置失败'
        return null
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } }; message?: string }
      error.value = error.response?.data?.message || error.message || '获取 Agent 配置失败'
      return null
    } finally {
      loading.value = false
    }
  }
&nbsp;
  async function createAgent(data: Partial&lt;Agent&gt;): Promise&lt;Agent | null&gt; {
    loading.value = true
    error.value = null
    try {
      const response = await request.post('/agents', data)
      if (response.code === 0) {
        agents.value.push(response.data)
        return response.data
      } else {
        error.value = response.message || '创建失败'
        return null
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } }; message?: string }
      error.value = error.response?.data?.message || error.message || '创建 Agent 失败'
      return null
    } finally {
      loading.value = false
    }
  }
&nbsp;
  async function updateAgent(id: string, data: Partial&lt;Agent&gt;): Promise&lt;boolean&gt; {
    loading.value = true
    error.value = null
    try {
      const response = await request.put(`/agents/${id}/config`, data)
      if (response.code === 0) {
        const index = agents.value.findIndex(a =&gt; a.id === id)
        if (index &gt; -1) agents.value[index] = response.data
        return true
      } else {
        error.value = response.message || '更新失败'
        return false
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } }; message?: string }
      error.value = error.response?.data?.message || error.message || '更新 Agent 失败'
      return false
    } finally {
      loading.value = false
    }
  }
&nbsp;
  async function deleteAgent(id: string): Promise&lt;boolean&gt; {
    loading.value = true
    error.value = null
    try {
      const response = await request.delete(`/agents/${id}`)
      if (response.code === 0) {
        agents.value = agents.value.filter(a =&gt; a.id !== id)
        if (currentAgentId.value === id &amp;&amp; agents.value.length &gt; 0) {
          setCurrentAgent(agents.value[0].id)
        }
        return true
      } else {
        error.value = response.message || '删除失败'
        return false
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { message?: string } }; message?: string }
      error.value = error.response?.data?.message || error.message || '删除 Agent 失败'
      return false
    } finally {
      loading.value = false
    }
  }
&nbsp;
  function setCurrentAgent(agentId: string) {
    currentAgentId.value = agentId
    localStorage.setItem('currentAgentId', agentId)
  }
&nbsp;
  return {
    agents, currentAgentId, currentAgent, agentOptions,
    loading, error,
    loadAgents, createAgent, updateAgent, deleteAgent, setCurrentAgent,
    getAgentConfig,
  }
})
&nbsp;