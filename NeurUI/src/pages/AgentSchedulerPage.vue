<template>
  <div class="scheduler-page">
    <div class="page-header">
      <h2>{{ t('nav.scheduler') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Scheduler status -->
    <GlassPanel variant="subtle" padding="16px 20px">
      <div class="scheduler-status">
        <a-badge :status="schedulerRunning ? 'processing' : 'default'" :text="schedulerRunning ? t('common.active') : t('common.inactive')" />
        <span class="meta-text">{{ t('common.total') }}: {{ tasks.length }}</span>
      </div>
    </GlassPanel>

    <!-- Task list -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && tasks.length === 0" :description="t('common.noData')" />
      <div v-else class="task-list">
        <GlassCard
          v-for="task in tasks"
          :key="task.id"
          :title="task.name"
          variant="default"
          padding="16px 20px"
        >
          <div class="task-meta">
            <a-tag color="blue">{{ task.schedule }}</a-tag>
            <a-badge :status="task.enabled ? 'processing' : 'default'" :text="task.enabled ? t('common.active') : t('common.inactive')" />
            <span class="meta-text" v-if="task.nextRun">{{ t('nav.scheduler') }}: {{ task.nextRun }}</span>
            <span class="meta-text" v-if="task.lastRun">Last: {{ task.lastRun }}</span>
          </div>
          <div class="task-actions">
            <a-switch :checked="task.enabled" size="small" @change="(val: boolean) => handleToggle(task.id, val)" />
            <GlassButton variant="secondary" size="sm" :loading="runningId === task.id" @click="handleRunNow(task.id)">Run Now</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="openEdit(task)">{{ t('common.edit') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(task.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving" width="520px">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item label="Schedule Type">
          <a-select v-model:value="form.scheduleType">
            <a-select-option value="cron">Cron Expression</a-select-option>
            <a-select-option value="interval">Interval (seconds)</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item v-if="form.scheduleType === 'cron'" label="Cron Expression">
          <a-input v-model:value="form.cron" placeholder="0 */5 * * *" />
        </a-form-item>
        <a-form-item v-if="form.scheduleType === 'interval'" label="Interval (seconds)">
          <a-input v-model:value="form.interval" type="number" placeholder="300" />
        </a-form-item>
        <a-form-item label="Action">
          <a-select v-model:value="form.action" :placeholder="t('common.actions')">
            <a-select-option value="send_message">Send Message</a-select-option>
            <a-select-option value="run_workflow">Run Workflow</a-select-option>
            <a-select-option value="execute_skill">Execute Skill</a-select-option>
            <a-select-option value="custom">Custom</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="form.description" type="textarea" :rows="2" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface ScheduledTask {
  id: string
  name: string
  schedule: string
  enabled: boolean
  nextRun?: string
  lastRun?: string
  action?: string
  description?: string
  cron?: string
  interval?: number
}

const tasks = ref<ScheduledTask[]>([])
const loading = ref(false)
const showModal = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const runningId = ref<string | null>(null)
const schedulerRunning = ref(true)

const form = reactive({
  name: '',
  scheduleType: 'cron' as 'cron' | 'interval',
  cron: '',
  interval: '',
  action: '',
  description: '',
})

function resetForm() {
  form.name = ''
  form.scheduleType = 'cron'
  form.cron = ''
  form.interval = ''
  form.action = ''
  form.description = ''
  editingId.value = null
}

function openCreate() { resetForm(); showModal.value = true }
function openEdit(task: ScheduledTask) {
  editingId.value = task.id
  form.name = task.name
  form.scheduleType = task.cron ? 'cron' : 'interval'
  form.cron = task.cron ?? ''
  form.interval = task.interval?.toString() ?? ''
  form.action = task.action ?? ''
  form.description = task.description ?? ''
  showModal.value = true
}

async function fetchTasks() {
  loading.value = true
  try {
    const res = await request.get('/scheduler/tasks') as unknown as ScheduledTask[]
    tasks.value = res ?? []
  } catch { tasks.value = [] } finally { loading.value = false }
}

async function handleSave() {
  if (!form.name) return
  saving.value = true
  try {
    const payload = {
      name: form.name,
      scheduleType: form.scheduleType,
      cron: form.scheduleType === 'cron' ? form.cron : undefined,
      interval: form.scheduleType === 'interval' ? Number(form.interval) : undefined,
      action: form.action,
      description: form.description,
    }
    if (editingId.value) {
      await request.put(`/scheduler/tasks/${editingId.value}`, payload)
    } else {
      await request.post('/scheduler/tasks', payload)
    }
    showModal.value = false
    resetForm()
    await fetchTasks()
  } catch { /* handled */ } finally { saving.value = false }
}

async function handleToggle(id: string, enabled: boolean) {
  try {
    await request.put(`/scheduler/tasks/${id}`, { enabled })
    await fetchTasks()
  } catch { /* handled */ }
}

async function handleRunNow(id: string) {
  runningId.value = id
  try {
    await request.post(`/scheduler/tasks/${id}/run`)
    await fetchTasks()
  } catch { /* handled */ } finally { runningId.value = null }
}

async function handleDelete(id: string) {
  try {
    await request.delete(`/scheduler/tasks/${id}`)
    await fetchTasks()
  } catch { /* handled */ }
}

onMounted(fetchTasks)
</script>

<style scoped>
.scheduler-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.scheduler-status { display: flex; gap: 16px; align-items: center; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.task-list { display: flex; flex-direction: column; gap: 12px; }
.task-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.task-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
