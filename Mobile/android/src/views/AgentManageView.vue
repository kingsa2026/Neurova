<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listAgents, switchAgent, type AgentInfo } from '@/api/manage'
import { useAgentsStore } from '@/stores/agents'

const store = useAgentsStore()
const agents = ref<AgentInfo[]>([])
const loading = ref(true)
const error = ref('')

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    agents.value = await listAgents()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function activate(a: AgentInfo) {
  await switchAgent(a.agent_id)
  await store.switchTo(a.agent_id)
  await load()
}
</script>

<template>
  <div>
    <div class="head-row">
      <h2 class="page-title">智能体管理</h2>
      <button class="ghost" @click="load">刷新</button>
    </div>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error-text">{{ error }}</p>
    <p v-else-if="!agents.length" class="muted">暂无智能体</p>
    <div v-for="a in agents" :key="a.agent_id" class="card">
      <div class="item-title">{{ a.name || a.agent_id }}</div>
      <div class="muted">{{ a.status ?? '' }}{{ a.model ? ` · ${a.model}` : '' }}</div>
      <button class="switch-btn" @click="activate(a)">切换到此智能体</button>
    </div>
  </div>
</template>

<style scoped>
.head-row { display: flex; justify-content: space-between; align-items: center; }
.page-title { font-size: 18px; margin: 4px 0 14px; }
.item-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.switch-btn {
  margin-top: 8px; background: var(--bg-elev); color: var(--primary);
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
.ghost {
  background: var(--bg-card); border: 1px solid var(--border); color: var(--text-dim);
  border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
</style>
