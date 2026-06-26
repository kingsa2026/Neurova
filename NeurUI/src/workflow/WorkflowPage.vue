<template>
  <div class="workflow-page">
    <div class="page-header">
      <h2>{{ t('workflow.title') }}</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" @click="handleImportComfyui">{{ t('workflow.importWf') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="showCreateModal = true">{{ t('workflow.create') }}</GlassButton>
      </div>
    </div>

    <!-- ComfyUI 服务状态指示器 -->
    <div class="comfyui-status" :class="{ available: comfyuiStatus.available }">
      <span class="status-dot" />
      <span class="status-text">
        ComfyUI: {{ comfyuiStatus.available ? `已连接 (${comfyuiStatus.host})` : '未连接' }}
      </span>
      <GlassButton variant="ghost" size="sm" @click="fetchComfyuiStatus">检测</GlassButton>
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

    <!-- ComfyUI 导入 modal -->
    <a-modal
      v-model:open="showComfyuiImportModal"
      title="导入 ComfyUI 工作流"
      :ok-text="comfyuiImporting ? '导入中…' : '导入'"
      :confirm-loading="comfyuiImporting"
      @ok="handleComfyuiImportSubmit"
    >
      <a-form layout="vertical">
        <a-form-item label="工作流名称" required>
          <a-input v-model:value="comfyuiImportForm.name" placeholder="例如：SDXL 文生图" />
        </a-form-item>
        <a-form-item label="描述（可选）">
          <a-input v-model:value="comfyuiImportForm.description" type="textarea" :rows="2" placeholder="工作流描述" />
        </a-form-item>
        <a-form-item label="ComfyUI 工作流 JSON 文件" required>
          <input
            type="file"
            accept=".json,application/json"
            @change="handleComfyuiFileUpload"
          />
          <p v-if="comfyuiImportForm.fileName" class="file-name">已选择: {{ comfyuiImportForm.fileName }}</p>
          <p v-else class="file-hint">选择 ComfyUI API 格式导出的 JSON 文件</p>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import { importComfyuiWorkflow, getComfyuiStatus } from '@/api/modules/neurflow'
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

// ComfyUI 整合状态
const comfyuiStatus = reactive<{ available: boolean; host: string | null }>({
  available: false,
  host: null,
})
const showComfyuiImportModal = ref(false)
const comfyuiImporting = ref(false)
const comfyuiImportForm = reactive<{
  name: string
  description: string
  fileName: string
  workflow: Record<string, unknown> | null
}>({ name: '', description: '', fileName: '', workflow: null })

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

function handleImportComfyui() {
  /* 打开 ComfyUI 导入 modal */
  comfyuiImportForm.name = ''
  comfyuiImportForm.description = ''
  comfyuiImportForm.fileName = ''
  comfyuiImportForm.workflow = null
  showComfyuiImportModal.value = true
}

function handleComfyuiFileUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  comfyuiImportForm.fileName = file.name
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const text = String(e.target?.result ?? '')
      comfyuiImportForm.workflow = JSON.parse(text) as Record<string, unknown>
    } catch {
      comfyuiImportForm.workflow = null
      alert('JSON 文件解析失败，请检查文件格式')
    }
  }
  reader.readAsText(file)
}

async function handleComfyuiImportSubmit() {
  if (!comfyuiImportForm.name) {
    alert('请输入工作流名称')
    return
  }
  if (!comfyuiImportForm.workflow) {
    alert('请选择 ComfyUI 工作流 JSON 文件')
    return
  }
  comfyuiImporting.value = true
  try {
    await importComfyuiWorkflow({
      name: comfyuiImportForm.name,
      description: comfyuiImportForm.description,
      workflow: comfyuiImportForm.workflow,
    })
    showComfyuiImportModal.value = false
    await fetchWorkflows()
  } catch {
    /* handled by interceptor */
  } finally {
    comfyuiImporting.value = false
  }
}

async function fetchComfyuiStatus() {
  try {
    const res = await getComfyuiStatus() as unknown as
      | { data?: { available: boolean; host: string | null } }
      | { available: boolean; host: string | null }
    // 兼容两种响应包装：{ data: {...} } 或直接 {...}
    const data = ('data' in res && res.data) ? res.data : (res as { available: boolean; host: string | null })
    if (data) {
      comfyuiStatus.available = data.available
      comfyuiStatus.host = data.host
    }
  } catch {
    comfyuiStatus.available = false
    comfyuiStatus.host = null
  }
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

onMounted(() => {
  fetchWorkflows()
  fetchComfyuiStatus()
})
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

/* ComfyUI 状态指示器 */
.comfyui-status {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-radius: 8px;
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  font-size: 13px;
  color: var(--nr-text-secondary);
}
.comfyui-status .status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff4d4f;
  transition: background 0.2s;
}
.comfyui-status.available .status-dot {
  background: #52c41a;
}
.comfyui-status .status-text {
  flex: 1;
  font-family: var(--nr-font-display, sans-serif);
}
.file-name { color: var(--nr-text-primary); font-size: 13px; margin-top: 6px; }
.file-hint { color: var(--nr-text-tertiary); font-size: 12px; margin-top: 6px; }
</style>
