<template>
  <div class="session-sync-page">
    <div class="page-header">
      <h2>{{ t('channel.session') }}</h2>
      <div class="header-actions">
        <div class="poll-indicator">
          <span class="poll-dot" />
          <span class="poll-label">{{ t('channel.restPolling') }}</span>
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
          row-key="session_id"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-badge :status="record.status === 'active' ? 'processing' : 'default'" :text="record.status" />
            </template>
            <template v-if="column.key === 'actions'">
              <GlassButton variant="secondary" size="sm" @click="openMessage(record)">{{ t('chat.send') }}</GlassButton>
              <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleClose(record.session_id)">
                <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
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
import { message } from 'ant-design-vue'
import {
  listSyncSessions,
  createSyncSession,
  sendSyncSessionMessage,
  endSyncSession,
} from '@/api/modules/sessionSync'
import type { SyncSession } from '@/api/modules/sessionSync'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

const sessions = ref<SyncSession[]>([])
const loading = ref(false)
const showCreateModal = ref(false)
const showMessageModal = ref(false)
const creating = ref(false)
const sending = ref(false)
const activeSessionId = ref<string | null>(null)
const messageText = ref('')

const createForm = reactive({ name: '', description: '' })

const columns = [
  { title: t('common.id'), dataIndex: 'session_id', key: 'session_id' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
  { title: t('common.createdAt'), dataIndex: 'created_at', key: 'createdAt' },
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
    const res = await listSyncSessions()
    sessions.value = res?.sessions ?? []
  } catch {
    message.error(t('channel.sessionLoadFailed'))
    sessions.value = []
  } finally { loading.value = false }
}

function openCreate() {
  createForm.name = ''
  createForm.description = ''
  showCreateModal.value = true
}

function openMessage(session: SyncSession) {
  activeSessionId.value = session.session_id
  messageText.value = ''
  showMessageModal.value = true
}

async function handleCreate() {
  if (!createForm.name) return
  creating.value = true
  try {
    // 后端契约（session_sync.py CreateSessionRequest）：归属取 token 主体，
    // user_id 字段留空仅满足 schema；页面收集的名称/说明入 metadata。
    await createSyncSession({
      user_id: '',
      agent_id: 'default',
      metadata: { name: createForm.name, description: createForm.description },
    })
    showCreateModal.value = false
    await fetchSessions()
  } catch {
    message.error(t('channel.sessionCreateFailed'))
  } finally { creating.value = false }
}

async function handleSend() {
  if (!activeSessionId.value || !messageText.value) return
  sending.value = true
  try {
    // P1-8：REST 降级发消息走复数 /messages，正文字段名是 content。
    await sendSyncSessionMessage(activeSessionId.value, { content: messageText.value })
    showMessageModal.value = false
  } catch {
    message.error(t('channel.sessionSendFailed'))
  } finally { sending.value = false }
}

async function handleClose(id: string) {
  try {
    // P1-9：终结会话＝DELETE /sync/sessions/{id}（后端无 /close 端点）。
    await endSyncSession(id)
    await fetchSessions()
  } catch {
    message.error(t('channel.sessionDeleteFailed'))
  }
}

onMounted(() => {
  fetchSessions()
  // P3-15：本页没有 WebSocket，只有 15s REST 轮询——指示灯不再假报"已连接"。
  pollTimer = setInterval(fetchSessions, 15000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.session-sync-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.header-actions { display: flex; gap: 12px; align-items: center; }
.poll-indicator { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--nr-text-tertiary); }
.poll-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--nr-text-tertiary); }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.section-title { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 600; margin: 0 0 16px; font-size: 16px; }
</style>
