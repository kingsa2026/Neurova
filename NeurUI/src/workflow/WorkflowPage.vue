<template>
  <div class="workflow-page">
    <div class="page-header">
      <h2>{{ t('workflow.title') }}</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" @click="handleImport">{{ t('workflow.importWf') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="showCreateModal = true">{{ t('workflow.create') }}</GlassButton>
      </div>
    </div>

    <!-- Stats row -->
    <div class="stats-row">
      <GlassCard v-for="s in stats" :key="s.label" :title="s.label" variant="subtle" padding="14px 18px">
        <span class="stat-value">{{ s.value }}</span>
      </GlassCard>
    </div>

    <!-- Workflow list -->
    <a-spin :spinning="loading">
      <div v-if="!loading && workflows.length === 0" class="empty-state">
        <a-empty :description="t('common.noData')" />
      </div>
      <div v-else class="workflow-grid">
        <GlassCard
          v-for="wf in workflows"
          :key="wf.id"
          :title="wf.name"
          :subtitle="wf.description"
          variant="default"
          padding="18px 22px"
        >
          <div class="wf-meta">
            <a-tag :color="wf.status === 'published' ? 'green' : wf.status === 'draft' ? 'blue' : 'default'">{{ wf.status }}</a-tag>
            <span class="meta-text">{{ t('workflow.nodes') }}: {{ wf.nodeCount ?? 0 }}</span>
            <span v-if="wf.lastExecuted" class="meta-text">{{ t('workflow.execution') }}: {{ wf.lastExecuted }}</span>
          </div>
          <div class="wf-actions">
            <GlassButton variant="primary" size="sm" :loading="executingId === wf.id" @click="handleExecute(wf.id)">{{ t('workflow.execute') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="handleViewDetail(wf)">{{ t('common.open') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="handleDuplicate(wf.id)">{{ t('workflow.duplicate') }}</GlassButton>
            <GlassButton variant="ghost" size="sm" @click="handleExport(wf.id)">{{ t('workflow.exportWf') }}</GlassButton>
            <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDelete(wf.id)">
              <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
            </a-popconfirm>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Detail modal -->
    <a-modal v-model:open="showDetail" :title="detailWorkflow?.name" :footer="null" width="640px">
      <div v-if="detailWorkflow" class="detail-body">
        <p>{{ detailWorkflow.description }}</p>
        <h4>{{ t('workflow.nodes') }}</h4>
        <a-table
          :columns="nodeColumns"
          :data-source="detailWorkflow.nodes ?? []"
          :pagination="false"
          size="small"
          row-key="id"
        />
        <div class="detail-actions">
          <GlassButton variant="ghost" size="sm" @click="handleValidate(detailWorkflow!.id)">{{ t('workflow.validate') }}</GlassButton>
          <GlassButton variant="ghost" size="sm" @click="handlePublish(detailWorkflow!.id)">{{ t('workflow.publish') }}</GlassButton>
        </div>
      </div>
    </a-modal>

    <!-- Create modal -->
    <a-modal v-model:open="showCreateModal" :title="t('workflow.create')" @ok="handleCreate" :confirm-loading="creating">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="createForm.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-input v-model:value="createForm.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()

interface WorkflowNode {
  id: string
  name: string
  type: string
  status: string
}

interface Workflow {
  id: string
  name: string
  description: string
  status: string
  nodeCount?: number
  lastExecuted?: string
  nodes?: WorkflowNode[]
}

const workflows = ref<Workflow[]>([])
const loading = ref(false)
const executingId = ref<string | null>(null)
const creating = ref(false)
const showCreateModal = ref(false)
const showDetail = ref(false)
const detailWorkflow = ref<Workflow | null>(null)

const createForm = reactive({ name: '', description: '' })

const stats = computed(() => [
  { label: t('common.total'), value: workflows.value.length },
  { label: t('workflow.publish'), value: workflows.value.filter((w) => w.status === 'published').length },
  { label: t('common.status'), value: workflows.value.filter((w) => w.status === 'draft').length },
])

const nodeColumns = [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('common.type'), dataIndex: 'type', key: 'type' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
]

async function fetchWorkflows() {
  loading.value = true
  try {
    const res = await request.get('/neurflow/workflows') as unknown as Workflow[] | { data: Workflow[] }
    workflows.value = Array.isArray(res?.data) ? res.data : Array.isArray(res) ? res : []
  } catch {
    workflows.value = []
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!createForm.name) return
  creating.value = true
  try {
    await request.post('/neurflow/workflows', { name: createForm.name, description: createForm.description })
    showCreateModal.value = false
    createForm.name = ''
    createForm.description = ''
    await fetchWorkflows()
  } catch { /* handled by interceptor */ } finally {
    creating.value = false
  }
}

async function handleExecute(id: string) {
  executingId.value = id
  try {
    await request.post(`/neurflow/workflows/${id}/execute`)
    await fetchWorkflows()
  } catch { /* handled */ } finally {
    executingId.value = null
  }
}

function handleViewDetail(wf: Workflow) {
  detailWorkflow.value = wf
  showDetail.value = true
}

async function handleDuplicate(id: string) {
  try {
    await request.post(`/neurflow/workflows/${id}/duplicate`)
    await fetchWorkflows()
  } catch { /* handled */ }
}

async function handleExport(id: string) {
  try {
    await request.post(`/neurflow/workflows/${id}/export`)
  } catch { /* handled */ }
}

function handleImport() {
  /* placeholder for file upload trigger */
}

async function handleValidate(id: string) {
  try {
    await request.post(`/neurflow/workflows/${id}/validate`)
  } catch { /* handled */ }
}

async function handlePublish(id: string) {
  try {
    await request.post(`/neurflow/workflows/${id}/publish`)
    await fetchWorkflows()
  } catch { /* handled */ }
}

async function handleDelete(id: string) {
  try {
    await request.delete(`/neurflow/workflows/${id}`)
    await fetchWorkflows()
  } catch { /* handled */ }
}

onMounted(fetchWorkflows)
</script>

<style scoped>
.workflow-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.header-actions { display: flex; gap: 8px; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.workflow-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.wf-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.meta-text { font-size: 12px; color: var(--nr-text-tertiary); }
.wf-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.empty-state { padding: 48px 0; }
.detail-body { display: flex; flex-direction: column; gap: 16px; }
.detail-body p { color: var(--nr-text-secondary); font-size: 14px; }
.detail-body h4 { color: var(--nr-text-primary); margin: 0; }
.detail-actions { display: flex; gap: 8px; margin-top: 8px; }
</style>
