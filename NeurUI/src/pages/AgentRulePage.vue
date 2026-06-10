<template>
  <div class="rule-page">
    <div class="page-header">
      <h2>{{ t('system.rules') }}</h2>
      <GlassButton variant="primary" size="sm" @click="openCreate">{{ t('common.create') }}</GlassButton>
    </div>

    <!-- Rule list -->
    <a-spin :spinning="loading">
      <a-empty v-if="!loading && rules.length === 0" :description="t('common.noData')" />
      <div v-else class="rule-list">
        <GlassCard
          v-for="rule in rules"
          :key="rule.id"
          :title="rule.name"
          variant="default"
          padding="16px 20px"
        >
          <div class="rule-meta">
            <a-badge :status="rule.active ? 'processing' : 'default'" :text="rule.active ? t('common.active') : t('common.inactive')" />
            <span class="meta-text">{{ t('rule.conditionLabel') }}{{ rule.condition }}</span>
            <span class="meta-text">{{ t('rule.action') }}{{ rule.action }}</span>
            <span class="meta-text">{{ t('rule.executions') }}{{ rule.executionCount ?? 0 }}</span>
          </div>
          <div class="rule-actions">
            <a-switch :checked="rule.active" size="small" @change="() => handleToggle(rule.id)" />
            <GlassButton variant="secondary" size="sm" :loading="testingId === rule.id" @click="handleTest(rule.id)">{{ t('channel.test') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="openEdit(rule)">{{ t('common.edit') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="handleViewLogs(rule)">{{ t('system.logs') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(rule.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Create/Edit modal -->
    <a-modal v-model:open="showModal" :title="editingId ? t('common.edit') : t('common.create')" @ok="handleSave" :confirm-loading="saving" width="560px">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('rule.conditionLabel')">
          <a-input v-model:value="form.condition" type="textarea" :rows="3" :placeholder="t('rule.conditionPlaceholder')" />
        </a-form-item>
        <a-form-item :label="t('rule.action')">
          <a-select v-model:value="form.action" :placeholder="t('common.actions')">
            <a-select-option value="send_reply">{{ t('rule.sendReply') }}</a-select-option>
            <a-select-option value="trigger_workflow">{{ t('rule.triggerWorkflow') }}</a-select-option>
            <a-select-option value="notify">{{ t('rule.notify') }}</a-select-option>
            <a-select-option value="block">{{ t('rule.block') }}</a-select-option>
            <a-select-option value="transform">{{ t('rule.transform') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('rule.priority')">
          <a-select v-model:value="form.priority">
            <a-select-option value="low">{{ t('rule.low') }}</a-select-option>
            <a-select-option value="medium">{{ t('rule.medium') }}</a-select-option>
            <a-select-option value="high">{{ t('rule.high') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="form.description" type="textarea" :rows="2" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Execution logs modal -->
    <a-modal v-model:open="showLogs" :title="t('system.logs')" :footer="null" width="640px">
      <a-table
        :columns="logColumns"
        :data-source="executionLogs"
        :pagination="{ pageSize: 8 }"
        size="small"
        row-key="id"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'result'">
            <a-tag :color="record.success ? 'green' : 'red'">{{ record.success ? t('common.success') : t('common.error') }}</a-tag>
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

interface Rule {
  id: string
  name: string
  condition: string
  action: string
  active: boolean
  executionCount?: number
  priority?: string
  description?: string
}

interface ExecutionLog {
  id: string
  ruleId: string
  timestamp: string
  success: boolean
  detail?: string
}

const rules = ref<Rule[]>([])
const loading = ref(false)
const showModal = ref(false)
const showLogs = ref(false)
const saving = ref(false)
const editingId = ref<string | null>(null)
const testingId = ref<string | null>(null)
const executionLogs = ref<ExecutionLog[]>([])

const logColumns = [
  { title: t('common.createdAt'), dataIndex: 'timestamp', key: 'timestamp' },
  { title: t('common.status'), dataIndex: 'success', key: 'result' },
  { title: t('rule.detail'), dataIndex: 'detail', key: 'detail' },
]

const form = reactive({ name: '', condition: '', action: '', priority: 'medium', description: '' })

function resetForm() {
  form.name = ''
  form.condition = ''
  form.action = ''
  form.priority = 'medium'
  form.description = ''
  editingId.value = null
}

function openCreate() { resetForm(); showModal.value = true }
function openEdit(rule: Rule) {
  editingId.value = rule.id
  form.name = rule.name
  form.condition = rule.condition
  form.action = rule.action
  form.priority = rule.priority ?? 'medium'
  form.description = rule.description ?? ''
  showModal.value = true
}

async function fetchRules() {
  loading.value = true
  try {
    const res = await request.get('/rules') as unknown as Rule[]
    rules.value = res ?? []
  } catch { rules.value = [] } finally { loading.value = false }
}

async function handleSave() {
  if (!form.name) return
  saving.value = true
  try {
    if (editingId.value) {
      await request.put(`/rules/${editingId.value}`, { ...form })
    } else {
      await request.post('/rules', { ...form })
    }
    showModal.value = false
    resetForm()
    await fetchRules()
  } catch { /* handled */ } finally { saving.value = false }
}

async function handleToggle(id: string) {
  try {
    await request.put(`/rules/${id}/toggle`)
    await fetchRules()
  } catch { /* handled */ }
}

async function handleTest(id: string) {
  testingId.value = id
  try {
    await request.post(`/rules/${id}/test`)
  } catch { /* handled */ } finally { testingId.value = null }
}

async function handleDelete(id: string) {
  try {
    await request.delete(`/rules/${id}`)
    await fetchRules()
  } catch { /* handled */ }
}

async function handleViewLogs(rule: Rule) {
  try {
    const res = await request.get(`/rules/${rule.id}/logs`) as unknown as ExecutionLog[]
    executionLogs.value = res ?? []
  } catch { executionLogs.value = [] }
  showLogs.value = true
}

onMounted(fetchRules)
</script>

<style scoped>
.rule-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.rule-list { display: flex; flex-direction: column; gap: 12px; }
.rule-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.rule-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
</style>
