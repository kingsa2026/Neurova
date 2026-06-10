<template>
  <div class="collab-hist-page">
    <div class="page-header">
      <h2>{{ t('collab.history') }}</h2>
      <GlassButton variant="ghost" size="sm" @click="$router.back()">{{ t('common.back') }}</GlassButton>
    </div>

    <!-- Filters -->
    <GlassPanel variant="subtle" padding="16px 20px">
      <div class="filters">
        <a-input v-model:value="filters.keyword" :placeholder="t('common.search')" style="width: 200px" allow-clear />
        <a-select v-model:value="filters.status" :placeholder="t('common.status')" style="width: 140px" allow-clear>
          <a-select-option value="active">{{ t('common.active') }}</a-select-option>
          <a-select-option value="completed">{{ t('collab.completed') }}</a-select-option>
          <a-select-option value="failed">{{ t('collab.failed') }}</a-select-option>
        </a-select>
        <a-input v-model:value="filters.date" type="date" style="width: 160px" />
      </div>
    </GlassPanel>

    <!-- Timeline -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && filteredSessions.length === 0" :description="t('common.noData')" />
      <GlassPanel v-else variant="default" padding="20px 24px">
        <a-timeline mode="left">
          <a-timeline-item
            v-for="session in filteredSessions"
            :key="session.id"
            :color="session.status === 'completed' ? 'green' : session.status === 'active' ? 'blue' : 'red'"
          >
            <div class="timeline-entry" @click="handleView(session)">
              <div class="entry-header">
                <strong>{{ session.name }}</strong>
                <a-tag :color="session.status === 'completed' ? 'green' : session.status === 'active' ? 'blue' : 'red'">{{ session.status }}</a-tag>
              </div>
              <p class="entry-desc">{{ session.description }}</p>
              <span class="entry-date">{{ session.createdAt }}</span>
            </div>
          </a-timeline-item>
        </a-timeline>
      </GlassPanel>
    </a-spin>

    <!-- Detail modal -->
    <a-modal v-model:open="showDetail" :title="selectedSession?.name" :footer="null" width="600px">
      <div v-if="selectedSession" class="session-detail">
        <p><strong>{{ t('common.description') }}:</strong> {{ selectedSession.description }}</p>
        <p><strong>{{ t('common.status') }}:</strong> {{ selectedSession.status }}</p>
        <p><strong>{{ t('collab.members') }}:</strong> {{ selectedSession.participants?.join(', ') ?? '-' }}</p>
        <p><strong>{{ t('common.createdAt') }}:</strong> {{ selectedSession.createdAt }}</p>
        <p v-if="selectedSession.completedAt"><strong>{{ t('common.updatedAt') }}:</strong> {{ selectedSession.completedAt }}</p>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface Session {
  id: string
  name: string
  description: string
  status: string
  participants?: string[]
  createdAt: string
  completedAt?: string
}

const sessions = ref<Session[]>([])
const loading = ref(false)
const showDetail = ref(false)
const selectedSession = ref<Session | null>(null)
const filters = reactive({ keyword: '', status: undefined as string | undefined, date: '' })

const filteredSessions = computed(() =>
  sessions.value.filter((s) => {
    if (filters.keyword && !s.name.toLowerCase().includes(filters.keyword.toLowerCase())) return false
    if (filters.status && s.status !== filters.status) return false
    if (filters.date && !s.createdAt.startsWith(filters.date)) return false
    return true
  })
)

async function fetchHistory() {
  loading.value = true
  try {
    const res = await request.get('/collaboration/history') as unknown as Session[]
    sessions.value = res ?? []
  } catch {
    sessions.value = []
  } finally {
    loading.value = false
  }
}

function handleView(session: Session) {
  selectedSession.value = session
  showDetail.value = true
}

onMounted(fetchHistory)
</script>

<style scoped>
.collab-hist-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.filters { display: flex; gap: 10px; flex-wrap: wrap; }
.timeline-entry { cursor: pointer; padding: 4px 0; }
.timeline-entry:hover strong { color: var(--nr-primary-light, #6366f1); }
.entry-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.entry-header strong { color: var(--nr-text-primary); font-size: 14px; }
.entry-desc { color: var(--nr-text-tertiary); font-size: 13px; margin: 0; }
.entry-date { color: var(--nr-text-tertiary); font-size: 11px; }
.session-detail { display: flex; flex-direction: column; gap: 10px; }
.session-detail p { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }
</style>
