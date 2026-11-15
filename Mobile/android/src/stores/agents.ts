/** Agent 列表与当前选中 Agent（跨会话持久化；服务端按属主过滤，设计方案 §2.1） */
import { defineStore } from 'pinia'
import { listAgents, type AgentItem } from '@/api/misc'
import { STORAGE_KEYS, storageGetJson, storageSetJson } from '@/utils/session'

interface AgentsState {
  agents: AgentItem[]
  currentId: string
}

export const useAgentsStore = defineStore('agents', {
  state: (): AgentsState => ({ agents: [], currentId: 'default' }),
  getters: {
    currentName(state): string {
      const found = state.agents.find((a) => a.agent_id === state.currentId)
      return found?.name ?? state.currentId
    },
  },
  actions: {
    async load() {
      const saved = await storageGetJson<AgentsState>(STORAGE_KEYS.user + '.agents')
      if (saved?.currentId) this.currentId = saved.currentId
      try {
        this.agents = await listAgents()
      } catch {
        // 列表拉取失败不阻塞进入（ChatView 有兜底 agent_id=default）
      }
      if (!this.agents.some((a) => a.agent_id === this.currentId)) {
        this.currentId = this.agents[0]?.agent_id ?? 'default'
      }
      await this.persist()
    },
    async switchTo(agentId: string) {
      this.currentId = agentId
      await this.persist()
    },
    async persist() {
      await storageSetJson(STORAGE_KEYS.user + '.agents', {
        agents: this.agents,
        currentId: this.currentId,
      } satisfies AgentsState)
    },
  },
})
