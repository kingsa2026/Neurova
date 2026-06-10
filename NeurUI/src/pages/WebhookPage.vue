<template>
  <div class="webhook-page">
    <div class="page-header">
      <h2>{{ t('system.webhooks') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Webhook list -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && webhooks.length === 0" :description="t('common.noData')" />
      <div v-else class="webhook-list">
        <GlassCard
          v-for="wh in webhooks"
          :key="wh.id"
          :title="wh.url"
          variant="default"
          padding="18px 22px"
        >
          <div class="wh-meta">
            <a-badge :status="wh.enabled ? 'processing' : 'default'" :text="wh.enabled ? t('common.active') : t('common.inactive')" />
            <div class="wh-events">
              <a-tag v-for="evt in (wh.events ?? []).slice(0, 4)" :key="evt" color="purple">{{ evt }}</a-tag>
              <a-tag v-if="(wh.events?.length ?? 0) > 4">+{{ wh.events!.length - 4 }}</a-tag>
            </div>
            <span v-if="wh.lastDelivery" class="meta-text">{{ wh.lastDelivery }}</span>
          </div>
          <div class="wh-actions">
            <GlassButton variant="secondary" size="sm" :loading="testingId === wh.id" @click="handleTest(wh.id)">{{ t('channel.test') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="openEdit(wh)">{{ t('common.edit') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="handleViewLogs(wh)">{{ t('system.logs') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(wh.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving" width="560px">
      <a-form layout="vertical">
        <a-form-item :label="t('system.url')">
          <a-input v-model:value="form.url" placeholder="https://example.com/webhook" />
        </a-form-item>
        <a-form-item :label="t('system.events')">
          <a-select v-model:value="form.events" mode="multiple" :placeholder="t('common.type')" style="width: 100%">
            <a-select-option v-for="evt in availableEvents" :key="evt" :value="evt">{{ evt }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('system.secret')">
          <a-input v-model:value="form.secret" type="password" :placeholder="t('system.secret')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="form.description" type="textarea" :rows="2" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Delivery logs modal -->
    <a-modal v-model:open="showLogs" :title="t('system.logs')" :footer="null" width="640px">
      <a-table
        :columns="logColumns"
        :data-source="deliveryLogs"
        :pagination="{ pageSize: 8 }"
        size="small"
        row-key="id"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.statusCode >= 200 && record.statusCode < 300 ? 'green' : 'red'">{{ record.statusCode }}</a-tag>
          </template>
        </template>
      </a-table>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface Webhook {
  id: string
  url: string
  events?: string[]
  enabled: boolean
  secret?: string
  description?: string
  lastDelivery?: string
}

interface DeliveryLog {
  id: string
  event: string
  statusCode: number
  timestamp: string
  duration?: string
}

const webhooks = ref<Webhook[]>([])
const loading = ref(false)
const showModal = ref(false)
const showLogs = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const testingId = ref<string | null>(null)
const deliveryLogs = ref<DeliveryLog[]>([])

const availableEvents = [
  'agent.created', 'agent.updated', 'agent.deleted',
  'chat.message', 'chat.completed',
  'workflow.started', 'workflow.completed', 'workflow.failed',
  'task.created', 'task.completed',
]

const logColumns = [
  { title: t('system.event'), dataIndex: 'event', key: 'event' },
  { title: t('common.status'), dataIndex: 'statusCode', key: 'status' },
  { title: t('common.createdAt'), dataIndex: 'timestamp', key: 'timestamp' },
  { title: t('system.duration'), dataIndex: 'duration', key: 'duration' },
]

const form = reactive({ url: '', events: [] as string[], secret: '', description: '' })

function resetForm() {
  form.url = ''
  form.events = []
  form.secret = ''
  form.description = ''
  editingId.value = null
}

function openCreate() { resetForm(); showModal.value = true }
function openEdit(wh: Webhook) {
  editingId.value = wh.id
  form.url = wh.url
  form.events = wh.events ? [...wh.events] : []
  form.secret = wh.secret ?? ''
  form.description = wh.description ?? ''
  showModal.value = true
}

async function fetchWebhooks() {
  loading.value = true
  try {
    const res = await request.get('/webhooks') as unknown as Webhook[]
    webhooks.value = res ?? []
  } catch { webhooks.value = [] } finally { loading.value = false }
}

async function handleSave() {
  if (!form.url) return
  saving.value = true
  try {
    if (editingId.value) {
      await request.put(`/webhooks/${editingId.value}`, { ...form })
    } else {
      await request.post('/webhooks', { ...form })
    }
    showModal.value = false
    resetForm()
    await fetchWebhooks()
  } catch { /* handled */ } finally { saving.value = false }
}

async function handleTest(id: string) {
  testingId.value = id
  try {
    await request.post(`/webhooks/${id}/test`)
  } catch { /* handled */ } finally { testingId.value = null }
}

async function handleDelete(id: string) {
  try {
    await request.delete(`/webhooks/${id}`)
    await fetchWebhooks()
  } catch { /* handled */ }
}

async function handleViewLogs(wh: Webhook) {
  try {
    const res = await request.get(`/webhooks/${wh.id}/deliveries`) as unknown as DeliveryLog[]
    deliveryLogs.value = res ?? []
  } catch { deliveryLogs.value = [] }
  showLogs.value = true
}

onMounted(fetchWebhooks)
</script>

<style scoped>
.webhook-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.webhook-list { display: flex; flex-direction: column; gap: 12px; }
.wh-meta { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.wh-events { display: flex; gap: 6px; flex-wrap: wrap; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.wh-actions { display: flex; gap: 6px; flex-wrap: wrap; }
</style>
