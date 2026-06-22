<template>
  <div class="agent-list-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('agent.title') }}</h2>
        <p class="page-subtitle">{{ t('agent.description') }}</p>
      </div>
      <GlassButton variant="primary" @click="$router.push('/agents/create')">
        {{ t('agent.create') }}
      </GlassButton>
    </div>

    <GlassCard>
      <div class="toolbar">
        <a-input-search
          v-model:value="searchQuery"
          :placeholder="t('common.search')"
          style="max-width: 320px"
          allow-clear
        />
        <a-segmented v-model:value="viewMode" :options="viewOptions" />
      </div>
    </GlassCard>

    <a-spin :spinning="agentStore.loading">
      <!-- Empty state -->
      <div v-if="filteredAgents.length === 0 && !agentStore.loading" class="empty-state">
        <GlassPanel padding="48px 24px">
          <a-empty :description="t('agent.noAgents')">
            <GlassButton variant="primary" @click="$router.push('/agents/create')">
              {{ t('agent.createFirst') }}
            </GlassButton>
          </a-empty>
        </GlassPanel>
      </div>

      <!-- Card view -->
      <div v-else-if="viewMode === 'card'" class="card-grid">
        <GlassCard
          v-for="agent in pagedFilteredAgents"
          :key="agent.id"
          :title="agent.name"
          :subtitle="'ID: ' + agent.id"
        >
          <div class="agent-meta">
            <div class="meta-row">
              <span class="meta-label">{{ t('agent.model') }}</span>
              <span class="meta-value">{{ agent.model || '-' }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">{{ t('agent.provider') }}</span>
              <span class="meta-value">{{ agent.provider || '-' }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-label">{{ t('agent.status') }}</span>
              <a-tag :color="statusColor(agent.status)">{{ t(`agent.${agent.status}`) }}</a-tag>
            </div>
          </div>
          <template #footer>
            <div class="card-actions">
              <GlassButton size="sm" variant="ghost" @click="$router.push(`/agents/${agent.id}`)">
                {{ t('common.edit') }}
              </GlassButton>
              <GlassButton size="sm" variant="secondary" @click="$router.push(`/agent/${agent.id}/chat`)">
                {{ t('nav.chat') }}
              </GlassButton>
              <a-popconfirm
                :title="t('agent.deleteConfirm')"
                @confirm="handleDelete(agent.id)"
                :ok-text="t('common.yes')"
                :cancel-text="t('common.no')"
              >
                <GlassButton size="sm" variant="danger">
                  {{ t('common.delete') }}
                </GlassButton>
              </a-popconfirm>
            </div>
          </template>
        </GlassCard>
        <a-pagination v-if="filteredAgents.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="filteredAgents.length" size="small" style="margin-top: 16px; text-align: center" />
      </div>

      <!-- Table view -->
      <GlassCard v-else>
        <a-table
          :columns="tableColumns"
          :data-source="filteredAgents"
          :pagination="{ pageSize: 12 }"
          row-key="id"
          size="middle"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="table-desc">{{ record.description }}</div>
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tag :color="statusColor(record.status)">{{ t(`agent.${record.status}`) }}</a-tag>
            </template>
            <template v-else-if="column.key === 'actions'">
              <div class="table-actions">
                <GlassButton size="sm" variant="ghost" @click="$router.push(`/agents/${record.id}`)">
                  {{ t('common.edit') }}
                </GlassButton>
                <GlassButton size="sm" variant="secondary" @click="$router.push(`/agent/${record.id}/chat`)">
                  {{ t('nav.chat') }}
                </GlassButton>
                <a-popconfirm
                  :title="t('agent.deleteConfirm')"
                  @confirm="handleDelete(record.id)"
                  :ok-text="t('common.yes')"
                  :cancel-text="t('common.no')"
                >
                  <GlassButton size="sm" variant="danger">
                    {{ t('common.delete') }}
                  </GlassButton>
                </a-popconfirm>
              </div>
            </template>
          </template>
        </a-table>
      </GlassCard>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassPanel from '@/components/GlassPanel.vue'
import { useAgentStore } from '@/stores/agents'

const { t } = useI18n()
const agentStore = useAgentStore()

const searchQuery = ref('')
const viewMode = ref<'card' | 'table'>('card')
const currentPage = ref(1)
const pageSize = ref(12)

const viewOptions = computed(() => [
  { label: t('common.viewCard'), value: 'card' },
  { label: t('common.viewTable'), value: 'table' },
])

const tableColumns = computed(() => [
  { title: t('common.name'), key: 'name', dataIndex: 'name' },
  { title: t('agent.model'), key: 'model', dataIndex: 'model' },
  { title: t('agent.provider'), key: 'provider', dataIndex: 'provider' },
  { title: t('common.status'), key: 'status' },
  { title: t('common.actions'), key: 'actions', width: 300 },
])

const filteredAgents = computed(() => {
  if (!searchQuery.value) return agentStore.agents
  const q = searchQuery.value.toLowerCase()
  return agentStore.agents.filter(
    (a) =>
      a.name.toLowerCase().includes(q) ||
      a.description?.toLowerCase().includes(q) ||
      a.model?.toLowerCase().includes(q),
  )
})

const pagedFilteredAgents = computed(() =>
  filteredAgents.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

const statusColor = (status: string) => {
  const map: Record<string, string> = {
    active: 'green',
    sleeping: 'blue',
    inactive: 'default',
    error: 'red',
  }
  return map[status] || 'default'
}

const handleDelete = async (id: string) => {
  const ok = await agentStore.deleteAgent(id)
  if (ok) {
    message.success(t('common.success'))
  } else {
    message.error(agentStore.error || t('common.error'))
  }
}

onMounted(() => {
  agentStore.loadAgents()
})
</script>

<style scoped>
.agent-list-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary);
  font-size: 13px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.empty-state {
  padding: 40px 0;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.agent-meta {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  font-size: 13px;
  gap: 12px;
}

.meta-label {
  color: var(--nr-text-secondary);
  flex-shrink: 0;
}

.meta-value {
  color: var(--nr-text-primary);
  font-weight: 500;
  text-align: right;
  overflow-wrap: break-word;
  word-break: break-word;
  min-width: 0;
}

.card-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.table-desc {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  margin-top: 2px;
}

.table-actions {
  display: flex;
  gap: 8px;
}
</style>
