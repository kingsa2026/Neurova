<template>
  <div class="session-sync-page">
    <div class="page-header">
      <h2>{{ t('channel.session') }}</h2>
      <div class="header-actions">
        <div class="ws-indicator" :class="{ connected: wsConnected }">
          <span class="ws-dot" />
          <span class="ws-label">{{ wsConnected ? 'Connected' : 'Disconnected' }}</span>
        </div>
        <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
      </div>
    </div>

    <!-- Stats -->
    <div class="stats-row">
      <GlassCard v-for="s in stats" :key="s.label" :title="s.label" variant="subtle" padding="14px 18px">
        <span class="stat-value">{{ s.value }}</span>
      </GlassCard>
    </div>

    <!-- Active connections -->
    <GlassPanel variant="default" padding="20px 24px">
      <h3 class="section-title">{{ t('common.active') }} {{ t('system.connections') }}</h3>
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
              <a-badge :status="record.status === 'active' ? 'processing' : 'default'" :text="record.status" />
            </template>
            <template v-if="column.key === 'actions'">
              <GlassButton variant="secondary" size="sm" @click="openMessage(record)">{{ t('chat.send') }}</GlassButton>
              <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleClose(record.id)">
                <GlassButton variant="danger" size="sm">{{ t('common.close') }}</GlassButton>
              </a-popconfirm>
            </template>
          </template>
        </a-table>
      </a-spin>
    </GlassPanel>

    <!-- Create session modal -->
    <a-modal v-model:open="showCreateModal" :title="t('common.create')" @ok="handleCreate" :confirm-loading="creating">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="createForm.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="createForm.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Send message modal -->
    <a-modal v-model:open="showMessageModal" :title="t('chat.send')" @ok="handleSend" :confirm-loading="sending">
      <a-form layout="vertical">
        <a-form-item :label="t('chat.placeholder')">
          <a-input v-model:value="messageText" type="textarea" :rows="4" :placeholder="t('chat.placeholder')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface SyncSession {
  id: string
  name: string
  status: string
  createdAt: string
  lastSync?: string
}

const sessions = ref<SyncSession[]>([])
const loading = ref(false)
const wsConnected = ref(false)
const showCreateModal = ref(false)
const showMessageModal = ref(false)
const creating = ref(false)
const sending = ref(false)
const activeSessionId = ref<string | null>(null)
const messageText = ref('')

const createForm = reactive({ name: '', description: '' })

const columns = [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
  { title: t('common.createdAt'), dataIndex: 'createdAt', key: 'createdAt' },
  { title: t('common.actions'), key: 'actions', width: 200 },
]

const stats = computed(() => [
  { label: t('common.total'), value: sessions.value.length },
  { label: t('common.active'), value: sessions.value.filter((s) => s.status === 'active').length },
])

let pollTimer: ReturnType<typeof setInterval> | null = null

async function fetchSessions() {
  loading.value = true
  try {
    const res = await request.get('/sync/sessions') as unknown as SyncSession[] | { data: SyncSession[] }
    sessions.value = Array.isArray(res) ? res : Array.isArray(res.data) ? res.data : []
  } catch { sessions.value = [] } finally { loading.value = false }
}

function openCreate() {
  createForm.name = ''
  createForm.description = ''
  showCreateModal.value = true
}

function openMessage(session: SyncSession) {
  activeSessionId.value = session.id
  messageText.value = ''
  showMessageModal.value = true
}

async function handleCreate() {
  if (!createForm.name) return
  creating.value = true
  try {
    await request.post('/sync/sessions', { ...createForm })
    showCreateModal.value = false
    await fetchSessions()
  } catch { /* handled */ } finally { creating.value = false }
}

async function handleSend() {
  if (!activeSessionId.value || !messageText.value) return
  sending.value = true
  try {
    await request.post(`/sync/sessions/${activeSessionId.value}/message`, { message: messageText.value })
    showMessageModal.value = false
  } catch { /* handled */ } finally { sending.value = false }
}

async function handleClose(id: string) {
  try {
    await request.post(`/sync/sessions/${id}/close`)
    await fetchSessions()
  } catch { /* handled */ }
}

onMounted(() => {
  fetchSessions()
  wsConnected.value = true
  pollTimer = setInterval(fetchSessions, 15000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  wsConnected.value = false
})
</script>

<style scoped>
.session-sync-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.header-actions { display: flex; gap: 12px; align-items: center; }
.ws-indicator { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--nr-text-tertiary); }
.ws-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--nr-error); transition: background 0.3s; }
.ws-indicator.connected .ws-dot { background: var(--nr-success); }
.ws-indicator.connected .ws-label { color: var(--nr-success); }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.section-title { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 600; margin: 0 0 16px; font-size: 16px; }
</style>
