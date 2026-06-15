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
          v-for="task in pagedTasks"
          :key="task.id"
          :title="task.name"
          variant="default"
          padding="16px 20px"
        >
          <div class="task-meta">
            <a-tag color="blue">{{ task.schedule }}</a-tag>
            <a-badge :status="task.enabled ? 'processing' : 'default'" :text="task.enabled ? t('common.active') : t('common.inactive')" />
            <span class="meta-text" v-if="task.nextRun">{{ t('nav.scheduler') }}: {{ task.nextRun }}</span>
            <span class="meta-text" v-if="task.lastRun">{{ t('scheduler.lastRun') }}{{ task.lastRun }}</span>
          </div>
          <div class="task-actions">
            <a-switch :checked="task.enabled" size="small" @change="(val: boolean) => handleToggle(task.id, val)" />
            <GlassButton variant="secondary" size="sm" :loading="runningId === task.id" @click="handleRunNow(task.id)">{{ t('scheduler.runNow') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="openEdit(task)">{{ t('common.edit') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(task.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
      <a-pagination v-if="tasks.length > pageSize" v-model:current="currentPage" :pageSize="pageSize" :total="tasks.length" size="small" style="margin-top: 16px; text-align: center" />
    </a-spin>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving" width="520px">
      <a-form layout="vertical" :rules="{ name: [{ required: true, message: t('common.required') }] }">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('scheduler.scheduleType')">
          <a-select v-model:value="form.scheduleType">
            <a-select-option value="cron">{{ t('scheduler.cronExpression') }}</a-select-option>
            <a-select-option value="interval">{{ t('scheduler.intervalSeconds') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item v-if="form.scheduleType === 'cron'" :label="t('scheduler.cronExpression')">
          <a-input v-model:value="form.cron" placeholder="0 */5 * * *" />
        </a-form-item>
        <a-form-item v-if="form.scheduleType === 'interval'" :label="t('scheduler.intervalSeconds')">
          <a-input v-model:value="form.interval" type="number" placeholder="300" />
        </a-form-item>
        <a-form-item :label="t('scheduler.action')">
          <a-select v-model:value="form.action" :placeholder="t('common.actions')">
            <a-select-option value="send_message">{{ t('scheduler.sendMessage') }}</a-select-option>
            <a-select-option value="run_workflow">{{ t('scheduler.runWorkflow') }}</a-select-option>
            <a-select-option value="execute_skill">{{ t('scheduler.executeSkill') }}</a-select-option>
            <a-select-option value="custom">{{ t('scheduler.custom') }}</a-select-option>
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
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import * as schedulerApi from '@/api/modules/scheduler'
import { useAgentPage } from '@/composables/useAgentPage'

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

const { agentId } = useAgentPage()
const tasks = ref<ScheduledTask[]>([])
const loading = ref(false)
const showModal = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const runningId = ref<string | null>(null)
const schedulerRunning = ref(true)
const currentPage = ref(1)
const pageSize = ref(12)

const form = reactive({
  name: '',
  scheduleType: 'cron' as 'cron' | 'interval',
  cron: '',
  interval: '',
  action: '',
  description: '',
})

const pagedTasks = computed(() =>
  tasks.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value),
)

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
    const res = await schedulerApi.getScheduledTasks({ agent_id: agentId.value })
    const data = res?.data
    const items = data?.items ?? (Array.isArray(data) ? data : [])
    tasks.value = items.map((t: any) => ({
      id: t.id,
      name: t.name,
      schedule: t.cron_expr || t.schedule || '',
      enabled: t.enabled,
      nextRun: t.next_run,
      lastRun: t.last_run,
      action: t.action,
      description: t.description,
      cron: t.cron_expr,
    }))
  } catch { message.error(t('common.error')) } finally { loading.value = false }
}

async function handleSave() {
  saving.value = true
  try {
    const cronExpr = form.scheduleType === 'cron' ? form.cron : `*/${form.interval || 5} * * * *`
    if (editingId.value) {
      await schedulerApi.updateScheduledTask(editingId.value, {
        name: form.name,
        cron_expr: cronExpr,
        action: form.action,
        description: form.description,
      })
    } else {
      await schedulerApi.createScheduledTask({
        name: form.name,
        cron_expr: cronExpr,
        action: form.action,
        description: form.description,
        agent_id: agentId.value,
      })
    }
    showModal.value = false
    resetForm()
    await fetchTasks()
  } catch { message.error(t('common.error')) } finally { saving.value = false }
}

async function handleToggle(id: string, enabled: boolean) {
  try {
    await schedulerApi.updateScheduledTask(id, { enabled })
    await fetchTasks()
  } catch { message.error(t('common.error')) }
}

async function handleRunNow(_id: string) {
  // Run-now not directly in scheduler API; could trigger via console push
  // Placeholder: just refresh
  await fetchTasks()
}

async function handleDelete(id: string) {
  try {
    await schedulerApi.deleteScheduledTask(id)
    await fetchTasks()
  } catch { message.error(t('common.error')) }
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
