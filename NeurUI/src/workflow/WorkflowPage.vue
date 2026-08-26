<template>
  <div class="workflow-page">
    <div class="page-header">
      <h2>{{ t('workflow.title') }}</h2>
      <div class="header-actions">
        <GlassButton variant="ghost" size="sm" @click="handleImportComfyui">{{ t('workflow.importWf') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="showCreateModal = true">{{ t('workflow.create') }}</GlassButton>
      </div>
    </div>

    <!-- 工作流 = 无限画布工作流：画布是可编辑形态，定义是执行内核 -->
    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="canvases" :tab="t('workflow.tabCanvases')">
        <a-spin :spinning="loadingCanvases">
          <div v-if="!loadingCanvases && canvases.length === 0" class="empty-state">
            <a-empty :description="t('common.noData')" />
          </div>
          <div v-else class="workflow-grid">
            <GlassCard
              v-for="cv in canvases"
              :key="cv.id"
              :title="cv.name"
              variant="default"
              padding="18px 22px"
            >
              <div class="wf-meta">
                <span class="meta-text">{{ t('workflow.nodes') }}: {{ cv.node_count ?? 0 }}</span>
                <span class="meta-text">{{ t('workflow.edges') }}: {{ cv.edge_count ?? 0 }}</span>
                <span v-if="cv.updated_at" class="meta-text">{{ t('workflow.updatedAt') }}: {{ formatTime(cv.updated_at) }}</span>
              </div>
              <div class="wf-actions">
                <GlassButton variant="primary" size="sm" @click="router.push(`/collaboration/canvas/${cv.id}`)">{{ t('common.open') }}</GlassButton>
                <GlassButton variant="ghost" size="sm" @click="openRename('canvas', cv.id, cv.name)">{{ t('common.rename') }}</GlassButton>
                <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDeleteCanvas(cv.id)">
                  <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
                </a-popconfirm>
              </div>
            </GlassCard>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="definitions" :tab="t('workflow.tabDefinitions')">
        <!-- ComfyUI 服务状态指示器 -->
        <div class="comfyui-status" :class="{ available: comfyuiStatus.available }">
          <span class="status-dot" />
          <span class="status-text">
            ComfyUI: {{ comfyuiStatus.available ? `已连接 (${comfyuiStatus.host})` : '未连接' }}
          </span>
          <GlassButton variant="ghost" size="sm" @click="fetchComfyuiStatus">检测</GlassButton>
        </div>

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
                <span class="meta-text">{{ t('workflow.nodes') }}: {{ wf.nodes?.length ?? 0 }}</span>
              </div>
              <div class="wf-actions">
                <GlassButton variant="primary" size="sm" :loading="executingId === wf.id" @click="handleExecute(wf.id)">{{ t('workflow.execute') }}</GlassButton>
                <GlassButton variant="ghost" size="sm" @click="handleViewDetail(wf)">{{ t('common.open') }}</GlassButton>
                <GlassButton variant="ghost" size="sm" @click="openRename('workflow', wf.id, wf.name)">{{ t('common.rename') }}</GlassButton>
                <GlassButton variant="ghost" size="sm" @click="handleDuplicate(wf.id)">{{ t('workflow.duplicate') }}</GlassButton>
                <a-popconfirm :title="t('common.confirm') + '?'" @confirm="handleDeleteWorkflow(wf.id)">
                  <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
                </a-popconfirm>
              </div>
            </GlassCard>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

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

    <!-- Create modal：工作流 = 画布工作流，创建即生成画布并进入编辑 -->
    <a-modal v-model:open="showCreateModal" :title="t('workflow.create')" @ok="handleCreate" :confirm-loading="creating">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="createForm.name" :placeholder="t('common.name')" @pressEnter="handleCreate" />
        </a-form-item>
        <a-form-item :label="t('workflow.project')">
          <a-select
            v-model:value="createForm.projectId"
            :options="projectOptions"
            allow-clear
            show-search
            option-filter-prop="label"
            size="small"
            :placeholder="t('workflow.projectOptional')"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Rename modal -->
    <a-modal
      v-model:open="showRenameModal"
      :title="t('common.rename')"
      :confirm-loading="renaming"
      @ok="confirmRename"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="renameTarget.name" :placeholder="t('common.name')" @pressEnter="confirmRename" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- ComfyUI 导入 modal（统一落为可编辑画布） -->
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
          <p v-else class="file-hint">选择 ComfyUI API 格式导出的 JSON 文件，导入后生成一张可编辑画布</p>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  getWorkflows,
  executeWorkflow,
  duplicateWorkflow,
  deleteWorkflow,
  updateWorkflow,
  validateWorkflow,
  publishWorkflow,
  getComfyuiStatus,
  type WorkflowDefinition,
} from '@/api/modules/neurflow'
import {
  listCanvases,
  deleteCanvas,
  importComfyuiCanvas,
  saveCanvas,
  getCanvas,
  updateCanvas,
  type CanvasSummary,
  type CanvasSnapshot,
} from '@/api/modules/collaboration'
import { listProjects, type ProjectInfo } from '@/api/modules/projects'
import { extractWorkflowList } from './workflowList'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()
const router = useRouter()

const activeTab = ref<'canvases' | 'definitions'>('canvases')

interface WorkflowNodeRow {
  id: string
  name?: string
  type: string
  status?: string
}

const workflows = ref<WorkflowDefinition[]>([])
const loading = ref(false)
const executingId = ref<string | null>(null)
const creating = ref(false)
const showCreateModal = ref(false)
const showDetail = ref(false)
const detailWorkflow = ref<WorkflowDefinition | null>(null)

// 画布列表（工作流的用户可编辑形态）
const canvases = ref<CanvasSummary[]>([])
const loadingCanvases = ref(false)

const createForm = reactive({ name: '', projectId: undefined as string | undefined })

// 项目归属下拉（轻量脚手架：画布可归属项目）
const projects = ref<ProjectInfo[]>([])
const projectOptions = computed(() =>
  projects.value.map((p) => ({ label: p.name, value: p.project_id })),
)
async function fetchProjects() {
  try {
    const res = await listProjects()
    const data = (res as unknown as { data?: ProjectInfo[] })?.data ?? res
    projects.value = Array.isArray(data) ? data : []
  } catch {
    projects.value = []
  }
}

// 重命名目标（画布 / 工作流定义通用）
const showRenameModal = ref(false)
const renaming = ref(false)
const renameTarget = reactive<{ type: 'canvas' | 'workflow'; id: string; name: string }>({
  type: 'canvas',
  id: '',
  name: '',
})

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

const nodeColumns = [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('common.type'), dataIndex: 'type', key: 'type' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
]

async function fetchCanvases() {
  loadingCanvases.value = true
  try {
    const res = await listCanvases()
    const data = (res as unknown as { data?: CanvasSummary[] })?.data ?? res
    canvases.value = Array.isArray(data) ? data : []
  } catch {
    canvases.value = []
  } finally {
    loadingCanvases.value = false
  }
}

async function fetchWorkflows() {
  loading.value = true
  try {
    const res = await getWorkflows()
    workflows.value = extractWorkflowList(res)
  } catch {
    workflows.value = []
  } finally {
    loading.value = false
  }
}

function unwrap<T>(res: unknown): T | null {
  const r = res as { data?: T } | null
  return (r?.data ?? (res as T)) as T | null
}

async function handleCreate() {
  if (!createForm.name.trim()) return
  creating.value = true
  try {
    // 工作流 = 无限画布工作流：创建即生成一张空画布，直接进入编辑
    const payload: Record<string, unknown> = { name: createForm.name.trim(), nodes: [], edges: [] }
    if (createForm.projectId) payload.project_id = createForm.projectId
    const record = unwrap<CanvasSnapshotRecord>(await saveCanvas(payload as never))
    showCreateModal.value = false
    createForm.name = ''
    createForm.projectId = undefined
    await fetchCanvases()
    if (record?.id) router.push(`/collaboration/canvas/${record.id}`)
  } catch { /* handled by interceptor */ } finally {
    creating.value = false
  }
}

function openRename(type: 'canvas' | 'workflow', id: string, name: string) {
  renameTarget.type = type
  renameTarget.id = id
  renameTarget.name = name
  showRenameModal.value = true
}

async function confirmRename() {
  const name = renameTarget.name.trim()
  if (!name || !renameTarget.id) return
  renaming.value = true
  try {
    if (renameTarget.type === 'canvas') {
      // 画布更新是整快照替换：先取全量，仅改名字
      const snap = unwrap<CanvasSnapshot>(await getCanvas(renameTarget.id))
      await updateCanvas(renameTarget.id, {
        name,
        nodes: snap?.nodes ?? [],
        edges: snap?.edges ?? [],
      })
      await fetchCanvases()
    } else {
      await updateWorkflow(renameTarget.id, { name })
      await fetchWorkflows()
    }
    showRenameModal.value = false
  } catch { /* handled by interceptor */ } finally {
    renaming.value = false
  }
}

async function handleExecute(id: string) {
  executingId.value = id
  try {
    await executeWorkflow(id)
    await fetchWorkflows()
  } catch { /* handled */ } finally {
    executingId.value = null
  }
}

function handleViewDetail(wf: WorkflowDefinition) {
  detailWorkflow.value = wf
  showDetail.value = true
}

async function handleDuplicate(id: string) {
  try {
    await duplicateWorkflow(id)
    await fetchWorkflows()
  } catch { /* handled */ }
}

async function handleDeleteWorkflow(id: string) {
  try {
    await deleteWorkflow(id)
    await fetchWorkflows()
  } catch { /* handled */ }
}

async function handleDeleteCanvas(id: string) {
  try {
    await deleteCanvas(id)
    await fetchCanvases()
  } catch { /* handled */ }
}

function handleImportComfyui() {
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
    const record = unwrap<CanvasSnapshotRecord>(await importComfyuiCanvas({
      name: comfyuiImportForm.name,
      description: comfyuiImportForm.description,
      workflow: comfyuiImportForm.workflow,
    }))
    showComfyuiImportModal.value = false
    activeTab.value = 'canvases'
    await fetchCanvases()
    if (record?.id) router.push(`/collaboration/canvas/${record.id}`)
  } catch {
    /* handled by interceptor */
  } finally {
    comfyuiImporting.value = false
  }
}

interface CanvasSnapshotRecord {
  id?: string
}

async function fetchComfyuiStatus() {
  try {
    const data = unwrap<{ available: boolean; host: string | null }>(await getComfyuiStatus())
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
    await validateWorkflow(id)
  } catch { /* handled */ }
}

async function handlePublish(id: string) {
  try {
    await publishWorkflow(id)
    await fetchWorkflows()
  } catch { /* handled */ }
}

function formatTime(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleString()
  } catch {
    return String(ts)
  }
}

onMounted(() => {
  fetchCanvases()
  fetchWorkflows()
  fetchComfyuiStatus()
  fetchProjects()
})
</script>

<style scoped>
.workflow-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.header-actions { display: flex; gap: 8px; }
.workflow-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; margin-top: 16px; }
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
