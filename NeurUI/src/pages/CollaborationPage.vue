<template>
  <div class="collab-page">
    <div class="page-header">
      <h2>{{ t('collab.title') }}</h2>
      <GlassButton variant="primary" size="sm" @click="$router.push('/collaboration/initiate')">{{ t('collab.initiate') }}</GlassButton>
    </div>

    <!-- Stats -->
    <div class="stats-row">
      <GlassCard v-for="s in stats" :key="s.label" :title="s.label" variant="subtle" padding="14px 18px">
        <span class="stat-value">{{ s.value }}</span>
      </GlassCard>
    </div>

    <!-- Quick start -->
    <GlassPanel variant="subtle" padding="20px 24px">
      <h3 class="section-title">{{ t('dashboard.quickActions') }}</h3>
      <div class="quick-actions">
        <GlassButton variant="secondary" size="sm" @click="$router.push('/collaboration/templates')">{{ t('collab.templates') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/collaboration/history')">{{ t('collab.history') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/projects')">{{ t('collab.projects') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/teams')">{{ t('collab.teams') }}</GlassButton>
        <GlassButton variant="secondary" size="sm" @click="$router.push('/tasks')">{{ t('collab.tasks') }}</GlassButton>
      </div>
    </GlassPanel>

    <!-- Active sessions -->
    <GlassPanel variant="default" padding="20px 24px">
      <h3 class="section-title">{{ t('common.active') }} {{ t('collab.title') }}</h3>
      <a-spin :spinning="loading">
        <a-empty v-if="!loading && sessions.length === 0" :description="t('common.noData')" />
        <a-table
          v-else
          :columns="columns"
          :data-source="sessions"
          :pagination="{ pageSize: 10 }"
          size="small"
          row-key="id"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-badge :status="record.status === 'active' ? 'processing' : record.status === 'completed' ? 'success' : 'default'" :text="record.status" />
            </template>
            <template v-if="column.key === 'actions'">
              <GlassButton variant="ghost" size="sm" @click="handleViewSession(record)">{{ t('common.open') }}</GlassButton>
            </template>
          </template>
        </a-table>
      </a-spin>
    </GlassPanel>

    <!-- Session detail modal -->
    <a-modal v-model:open="showDetail" :title="selectedSession?.name" :footer="null">
      <div v-if="selectedSession" class="session-detail">
        <p><strong>{{ t('common.description') }}:</strong> {{ selectedSession.description }}</p>
        <p><strong>{{ t('common.status') }}:</strong> {{ selectedSession.status }}</p>
        <p><strong>{{ t('collab.members') }}:</strong> {{ selectedSession.participants?.join(', ') }}</p>
        <p><strong>{{ t('common.createdAt') }}:</strong> {{ selectedSession.createdAt }}</p>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface Session {
  id: string
  name: string
  description: string
  status: string
  participants?: string[]
  createdAt: string
}

const sessions = ref<Session[]>([])
const loading = ref(false)
const showDetail = ref(false)
const selectedSession = ref<Session | null>(null)

const columns = [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
  { title: t('common.createdAt'), dataIndex: 'createdAt', key: 'createdAt' },
  { title: t('common.actions'), key: 'actions', width: 120 },
]

const stats = computed(() => [
  { label: t('common.total'), value: sessions.value.length },
  { label: t('common.active'), value: sessions.value.filter((s) => s.status === 'active').length },
  { label: t('collab.history'), value: sessions.value.filter((s) => s.status === 'completed').length },
])

async function fetchSessions() {
  loading.value = true
  try {
    const res = await request.get('/collaboration/templates') as unknown as Session[]
    sessions.value = res ?? []
  } catch {
    sessions.value = []
  } finally {
    loading.value = false
  }
}

function handleViewSession(record: Session) {
  selectedSession.value = record
  showDetail.value = true
}

onMounted(fetchSessions)
</script>

<style scoped>
.collab-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.section-title { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 600; margin: 0 0 16px; font-size: 16px; }
.quick-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.session-detail { display: flex; flex-direction: column; gap: 10px; }
.session-detail p { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }
</style>
