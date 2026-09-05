<template>
  <!-- Trigger button (sits in the sidebar) -->
  <div class="nr-as-trigger" :class="{ collapsed }" @click.stop="togglePanel">
    <div class="nr-as-trigger-avatar" :style="{ background: currentAgentColor }">
      <span>{{ currentAgentInitial }}</span>
    </div>
    <div v-if="!collapsed" class="nr-as-trigger-info">
      <span class="nr-as-trigger-name">{{ currentAgentName }}</span>
      <span class="nr-as-trigger-hint">{{ currentAgentRole }}</span>
    </div>
    <SwapOutlined v-if="!collapsed" class="nr-as-trigger-icon" />
    <span v-if="collapsed" class="nr-as-trigger-badge">{{ agentStore.agents.length }}</span>
  </div>

  <!-- Floating panel (teleported to body so it overlays everything) -->
  <Teleport to="body">
    <div v-show="panelOpen" class="nr-as-overlay" @click.self="closePanel">
      <div class="nr-as-panel">
        <!-- Panel header -->
        <div class="nr-as-panel-header">
          <span class="nr-as-panel-title">{{ t('agent.selectAgent') }}</span>
          <span class="nr-as-panel-count">{{ agentStore.agents.length }}</span>
          <button class="nr-as-close" @click="closePanel"><CloseOutlined /></button>
        </div>

        <!-- Search -->
        <div class="nr-as-search">
          <SearchOutlined class="nr-as-search-icon" />
          <input
            ref="searchInput"
            v-model="searchQuery"
            class="nr-as-search-input"
            :placeholder="t('agent.selectAgent')"
          />
        </div>

        <!-- Agent list -->
        <div class="nr-as-list">
          <div
            v-for="agent in filteredAgents"
            :key="agent.id"
            class="nr-as-item"
            :class="{ active: agent.id === agentStore.currentAgentId }"
            @click="handleSelect(agent)"
          >
            <div class="nr-as-item-avatar" :style="{ background: getAgentColor(agent) }">
              <span>{{ getAgentInitial(agent) }}</span>
            </div>
            <div class="nr-as-item-info">
              <span class="nr-as-item-name">{{ agent.name }}</span>
              <span class="nr-as-item-desc">{{ truncate(agent.system_prompt || agent.role || '', 60) }}</span>
            </div>
            <div v-if="agent.id === agentStore.currentAgentId" class="nr-as-item-active-badge">
              <CheckCircleFilled />
            </div>
          </div>
          <div v-if="filteredAgents.length === 0 && !loading" class="nr-as-empty">
            {{ t('agent.noAgents') }}
          </div>
          <div v-if="loading" class="nr-as-empty">
            <LoadingOutlined />
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAgentStore } from '@/stores/agents'
import type { Agent } from '@/types/agent'
import {
  SwapOutlined, CloseOutlined, SearchOutlined,
  CheckCircleFilled, LoadingOutlined,
} from '@ant-design/icons-vue'

const props = withDefaults(defineProps<{
  collapsed?: boolean
  autoNavigate?: boolean
  navigateTo?: string
}>(), {
  collapsed: false,
  autoNavigate: false,
  navigateTo: 'chat',
})

const emit = defineEmits<{
  (e: 'select', agent: Agent): void
}>()

const router = useRouter()
const { t } = useI18n()
const agentStore = useAgentStore()

const panelOpen = ref(false)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement>()
const loading = ref(false)

// --- Computed ---
const currentAgentName = computed(() =>
  agentStore.currentAgent?.name || t('agent.selectAgent'),
)
const currentAgentRole = computed(() =>
  truncate(agentStore.currentAgent?.system_prompt || agentStore.currentAgent?.role || '', 30),
)
const currentAgentInitial = computed(() =>
  (agentStore.currentAgent?.name || 'A').charAt(0).toUpperCase(),
)
const currentAgentColor = computed(() =>
  agentStore.currentAgent ? getAgentColor(agentStore.currentAgent) : '#0A84FF',
)

const filteredAgents = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return agentStore.agents
  return agentStore.agents.filter(a =>
    a.name.toLowerCase().includes(q) ||
    (a.system_prompt || '').toLowerCase().includes(q) ||
    (a.role || '').toLowerCase().includes(q),
  )
})

// --- Lifecycle ---
onMounted(async () => {
  if (agentStore.agents.length === 0) {
    loading.value = true
    await agentStore.loadAgents()
    loading.value = false
  }
})

// --- Methods ---
// iOS 系统色板（Accent 蓝 / 绿 / 橙 / 红 / Cyan / 紫 / 粉 / 靛 / 黄 / Teal）
const colors = [
  '#0A84FF', '#30D158', '#FF9F0A', '#FF453A', '#64D2FF',
  '#BF5AF2', '#FF375F', '#5E5CE6', '#FFD60A', '#32ADE6',
]

function getAgentColor(agent: Agent): string {
  const id = agent.id || agent.name || 'A'
  const hash = id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0)
  return colors[hash % colors.length]
}

function getAgentInitial(agent: Agent): string {
  return (agent.name || 'A').charAt(0).toUpperCase()
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + '...' : str
}

function togglePanel() {
  panelOpen.value = !panelOpen.value
  if (panelOpen.value) {
    searchQuery.value = ''
    nextTick(() => searchInput.value?.focus())
  }
}

function closePanel() {
  panelOpen.value = false
  searchQuery.value = ''
}

function handleSelect(agent: Agent) {
  const id = agent.id || ''
  if (!id) return
  agentStore.setCurrentAgent(id)
  closePanel()
  emit('select', agent)

  if (props.autoNavigate) {
    const target = props.navigateTo === 'chat'
      ? `/agent/${id}/chat`
      : props.navigateTo.replace(':agentId', id)
    router.push(target)
  }
}

// Close on Escape
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && panelOpen.value) closePanel()
}
watch(panelOpen, (val) => {
  if (val) document.addEventListener('keydown', onKeydown)
  else document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
/* ========== Trigger Button ========== */
.nr-as-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 4px;
}
.nr-as-trigger:hover {
  background: var(--nr-glass-bg-hover);
}

.nr-as-trigger-avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 14px;
  flex-shrink: 0;
}

.nr-as-trigger-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.nr-as-trigger-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-as-trigger-hint {
  font-size: 10px;
  color: var(--nr-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nr-as-trigger-icon {
  color: var(--nr-text-muted);
  font-size: 12px;
  flex-shrink: 0;
}

.nr-as-trigger-badge {
  position: absolute;
  bottom: -2px;
  right: -2px;
  background: var(--nr-primary);
  color: white;
  font-size: 9px;
  font-weight: 700;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.nr-as-trigger.collapsed {
  justify-content: center;
  position: relative;
}
.nr-as-trigger.collapsed .nr-as-trigger-avatar {
  width: 28px;
  height: 28px;
  font-size: 12px;
}

/* ========== Floating Overlay ========== */
.nr-as-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  padding: 60px 12px 12px 12px;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  animation: nr-fade-in 0.2s ease;
}

.nr-as-panel {
  width: 340px;
  max-height: calc(100vh - 84px);
  background: var(--nr-bg-overlay);
  backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid var(--nr-glass-border);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow:
    0 24px 48px rgba(0, 0, 0, 0.3),
    0 8px 16px rgba(0, 0, 0, 0.2);
  animation: nr-slide-in 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes nr-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes nr-slide-in {
  from { transform: translateX(-16px) scale(0.96); opacity: 0; }
  to { transform: translateX(0) scale(1); opacity: 1; }
}

.nr-as-panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--nr-glass-border);
}
.nr-as-panel-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--nr-text-primary);
  flex: 1;
}
.nr-as-panel-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--nr-text-muted);
  background: var(--nr-glass-bg-hover);
  padding: 2px 8px;
  border-radius: 10px;
}
.nr-as-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--nr-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: all 0.15s;
}
.nr-as-close:hover {
  background: var(--nr-glass-bg-active);
  color: var(--nr-text-primary);
}

/* Search */
.nr-as-search {
  padding: 8px 12px;
  position: relative;
}
.nr-as-search-icon {
  position: absolute;
  left: 22px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--nr-text-muted);
  font-size: 13px;
  pointer-events: none;
}
.nr-as-search-input {
  width: 100%;
  padding: 8px 12px 8px 32px;
  border: 1px solid var(--nr-glass-border);
  border-radius: 8px;
  background: var(--nr-glass-bg);
  color: var(--nr-text-primary);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}
.nr-as-search-input::placeholder {
  color: var(--nr-text-muted);
}
.nr-as-search-input:focus {
  border-color: var(--nr-primary);
  background: var(--nr-glass-bg-hover);
}

/* List */
.nr-as-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px 8px;
}

.nr-as-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.nr-as-item:hover {
  background: var(--nr-glass-bg-hover);
}
.nr-as-item.active {
  background: var(--nr-glass-bg-hover);
  border: 1px solid var(--nr-glass-border);
}
.nr-as-item:not(.active) {
  border: 1px solid transparent;
}

.nr-as-item-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 15px;
  flex-shrink: 0;
  box-shadow: inset 0 0.5px 0 rgba(255, 255, 255, 0.25);
}

.nr-as-item-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  gap: 2px;
}
.nr-as-item-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--nr-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-as-item-desc {
  font-size: 11px;
  color: var(--nr-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nr-as-item-active-badge {
  color: var(--nr-primary);
  font-size: 16px;
  flex-shrink: 0;
}

.nr-as-empty {
  padding: 24px;
  text-align: center;
  color: var(--nr-text-muted);
  font-size: 13px;
}

/* Scrollbar */
.nr-as-list::-webkit-scrollbar { width: 4px; }
.nr-as-list::-webkit-scrollbar-track { background: transparent; }
.nr-as-list::-webkit-scrollbar-thumb { background: var(--nr-glass-border); border-radius: 2px; }
</style>
