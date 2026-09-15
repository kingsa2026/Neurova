<template>
  <div class="workflow-page">
    <div class="page-header">
      <h2>{{ t('workflow.title') }}</h2>
      <div class="header-actions">
        <a-select
          v-model:value="workflowView"
          size="small"
          style="width: 120px"
          :options="viewOptions"
          @change="reloadAll"
        />
        <GlassButton variant="ghost" size="sm" @click="openTemplates">{{ t('workflow.fromTemplate') }}</GlassButton>
        <GlassButton variant="ghost" size="sm" @click="handleImportComfyui">{{ t('workflow.importWf') }}</GlassButton>
        <GlassButton variant="ghost" size="sm" @click="openCustomNodeModal">{{ t('workflow.registerNode') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="showCreateModal = true">{{ t('workflow.create') }}</GlassButton>
      </div>
    </div>

    <!-- 工作流 = 无限画布工作流：画布是可编辑形态，定义是执行内核 -->
    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="canvases" :tab="t('workflow.tabCanvases')">
        <a-spin :spinning="loadingCanvases">
          <div v-if="!loadingCanvases && visibleCanvases.length === 0" class="empty-state">
            <a-empty :description="t('common.noData')" />
          </div>
          <div v-else class="workflow-grid">
            <div class="canvas-filter">
              <span class="filter-label">{{ t('workflow.project') }}:</span>
              <a-select
                v-model:value="projectFilter"
                size="small"
                style="width: 200px"
                :options="filterOptions"
              />
            </div>
            <GlassCard
              v-for="cv in visibleCanvases"
              :key="cv.id"
              :title="cv.name"
              variant="default"
              padding="18px 22px"
            >
              <div class="wf-meta">
                <a-tag v-if="cv.project_id" color="blue">{{ projectNameOf(cv.project_id) }}</a-tag>
                <a-tag v-else-if="cv.agent_id" color="purple">{{ t('workflow.viewAgent') }}</a-tag>
                <a-tag v-else>{{ t('workflow.noProject') }}</a-tag>
                <a-tag v-if="cv.origin && cv.origin !== 'manual'" color="orange">{{ originLabel(cv.origin) }}</a-tag>
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
            ComfyUI: {{ comfyuiStatus.available ? t('ui.comfyuiConnected', { host: comfyuiStatus.host }) : t('ui.disconnected') }}
          </span>
          <GlassButton variant="ghost" size="sm" @click="fetchComfyuiStatus">{{ t('ui.detect') }}</GlassButton>
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
                <a-tag v-if="wf.project_id" color="cyan">{{ projectNameOf(wf.project_id) }}</a-tag>
                <a-tag v-else-if="wf.agent_id" color="purple">{{ t('workflow.viewAgent') }}</a-tag>
                <a-tag v-if="wf.origin && wf.origin !== 'manual'" color="orange">{{ originLabel(wf.origin) }}</a-tag>
                <span class="meta-text">{{ t('workflow.nodes') }}: {{ wf.nodes?.length ?? 0 }}</span>
              </div>
              <div class="wf-actions">
                <GlassButton variant="primary" size="sm" :loading="executingId === wf.id" @click="handleExecute(wf.id)">{{ t('workflow.execute') }}</GlassButton>
                <GlassButton variant="ghost" size="sm" @click="openDefinitionInCanvas(wf.id)">{{ t('common.open') }}</GlassButton>
                <GlassButton variant="ghost" size="sm" @click="handleViewDetail(wf)">{{ t('workflow.detail') }}</GlassButton>
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

    <!-- 批次4：从模板新建（GET /neurflow/templates 首次消费；短剧一键成片等内置模板入口） -->
    <a-modal v-model:open="showTemplatesModal" :title="t('workflow.fromTemplate')" :footer="null" width="560px">
      <a-spin :spinning="loadingTemplates">
        <div v-if="templateList.length" class="template-list">
          <div v-for="tpl in templateList" :key="tpl.id" class="template-item">
            <div class="template-info">
              <div class="template-name">{{ tpl.name }}</div>
              <div class="template-desc">{{ tpl.description }}</div>
            </div>
            <GlassButton variant="primary" size="sm" :loading="instantiatingId === tpl.id" @click="instantiateTpl(tpl)">
              {{ t('workflow.useTemplate') }}
            </GlassButton>
          </div>
        </div>
        <a-empty v-else :description="t('workflow.noTemplates')" />
      </a-spin>
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
      :title="t('ui.importComfyuiWorkflow')"
      :ok-text="comfyuiImporting ? t('ui.importing') : t('ui.import')"
      :confirm-loading="comfyuiImporting"
      @ok="handleComfyuiImportSubmit"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('ui.workflowName')" required>
          <a-input v-model:value="comfyuiImportForm.name" :placeholder="t('ui.egSdxl')" />
        </a-form-item>
        <a-form-item :label="t('ui.descriptionOptional')">
          <a-input v-model:value="comfyuiImportForm.description" type="textarea" :rows="2" :placeholder="t('ui.workflowDesc')" />
        </a-form-item>
        <a-form-item :label="t('ui.comfyuiJsonFile')" required>
          <input
            type="file"
            accept=".json,application/json"
            @change="handleComfyuiFileUpload"
          />
          <p v-if="comfyuiImportForm.fileName" class="file-name">{{ t('ui.selected', { name: comfyuiImportForm.fileName }) }}</p>
          <p v-else class="file-hint">{{ t('ui.selectJsonHint') }}</p>
        </a-form-item>
      </a-form>
    </a-modal>
    <!-- B5 自定义节点类型注册 -->
    <a-modal
      v-model:open="showCustomNodeModal"
      :title="t('workflow.registerNode')"
      :ok-text="t('workflow.create')"
      :confirm-loading="savingCustomNode"
      @ok="submitCustomNode"
    >
      <a-form layout="vertical" size="small">
        <a-form-item :label="t('workflow.nodeType')" required>
          <a-input v-model:value="customNodeForm.type" placeholder="custom:summarize" />
        </a-form-item>
        <a-form-item :label="t('common.name')" required>
          <a-input v-model:value="customNodeForm.label" />
        </a-form-item>
        <a-form-item :label="t('workflow.nodeTier')">
          <a-select
            v-model:value="customNodeForm.tier"
            :options="[
              { label: t('workflow.tierDeclarative'), value: 'declarative' },
              { label: t('workflow.tierComposite'), value: 'composite' },
            ]"
          />
        </a-form-item>
        <a-form-item v-if="customNodeForm.tier === 'declarative'" :label="t('workflow.nodeTemplate')">
          <a-input v-model:value="customNodeForm.template" type="textarea" :rows="2" placeholder="{{input}}" />
        </a-form-item>
        <a-form-item :label="t('workflow.nodeFormSchema')">
          <a-input
            v-model:value="customNodeForm.formSchemaJson"
            type="textarea"
            :rows="3"
            placeholder='[{"id":"input","label":"输入","type":"textarea"}]'
          />
        </a-form-item>
      </a-form>
      <a-divider style="margin: 8px 0" />
      <div v-if="customNodes.length" class="custom-node-list">
        <div v-for="n in customNodes" :key="String(n.type)" class="custom-node-item">
          <span>{{ n.label }} <code>{{ n.type }}</code></span>
          <a-popconfirm :title="t('common.confirm') + '?'" @confirm="removeCustomNode(String(n.type))">
            <GlassButton variant="danger" size="sm">{{ t('common.delete') }}</GlassButton>
          </a-popconfirm>
        </div>
      </div>
      <a-empty v-else :description="t('common.noData')" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import {
  getWorkflows,
  executeWorkflow,
  duplicateWorkflow,
  deleteWorkflow,
  updateWorkflow,
  validateWorkflow,
  publishWorkflow,
  getComfyuiStatus,
  getTemplates,
  instantiateTemplate,
  listCustomNodes,
  createCustomNode,
  deleteCustomNode,
  type WorkflowDefinition,
} from '@/api/modules/neurflow'
import { message } from 'ant-design-vue'
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
const route = useRoute()

const activeTab = ref<'canvases' | 'definitions'>('canvases')

// B1 三视图过滤：'' = 全部（含成员可见的项目工作流）, personal|project|agent
const workflowView = ref<'' | 'personal' | 'project' | 'agent'>('')
const viewOptions = computed(() => [
  { label: t('workflow.viewAll'), value: '' },
  { label: t('workflow.viewPersonal'), value: 'personal' },
  { label: t('workflow.viewProject'), value: 'project' },
  { label: t('workflow.viewAgent'), value: 'agent' },
])
function originLabel(origin?: string): string {
  const map: Record<string, string> = {
    nl_chat: t('workflow.originNlChat'),
    template: t('workflow.originTemplate'),
    comfyui: t('workflow.originComfyui'),
    evolution: t('workflow.originEvolution'),
    manual: t('workflow.originManual'),
  }
  return map[origin || 'manual'] || origin || ''
}
async function reloadAll() {
  await Promise.all([fetchCanvases(), fetchWorkflows()])
}
// B2：定义在无限画布编辑器中打开（保存回写定义本体）
function openDefinitionInCanvas(id: string) {
  router.push({ path: `/collaboration/canvas/${id}`, query: { source: 'definition' } })
}

/** 项目归属筛选：'' = 全部, 'none' = 未归属, project_id = 指定项目 */
const projectFilter = ref('')
const filterOptions = computed(() => [
  { label: t('common.all'), value: '' },
  { label: t('workflow.noProject'), value: 'none' },
  ...projects.value.map((p) => ({ label: p.name, value: p.project_id })),
])
const visibleCanvases = computed(() => {
  if (projectFilter.value === 'none') return canvases.value.filter((c) => !c.project_id)
  if (projectFilter.value) return canvases.value.filter((c) => c.project_id === projectFilter.value)
  return canvases.value
})
function projectNameOf(projectId: string): string {
  return projects.value.find((p) => p.project_id === projectId)?.name ?? projectId
}

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

// 批次4：从模板新建（模板端点的前端首个消费方）
const showTemplatesModal = ref(false)
const loadingTemplates = ref(false)
const templateList = ref<WorkflowDefinition[]>([])
const instantiatingId = ref('')

function unwrapTpl<T = unknown>(res: unknown): T {
  return ((res as { data?: T })?.data ?? res) as T
}

async function openTemplates() {
  showTemplatesModal.value = true
  loadingTemplates.value = true
  try {
    const raw = unwrapTpl<{ templates?: WorkflowDefinition[]; total?: number }>(await getTemplates())
    templateList.value = Array.isArray(raw?.templates) ? raw.templates : []
  } catch {
    templateList.value = []
  } finally {
    loadingTemplates.value = false
  }
}

async function instantiateTpl(tpl: WorkflowDefinition) {
  instantiatingId.value = String(tpl.id)
  try {
    await instantiateTemplate(String(tpl.id), { name: `${tpl.name} - ${Date.now().toString(36)}` })
    message.success(t('workflow.tplOk'))
    showTemplatesModal.value = false
    activeTab.value = 'definitions'
    await fetchWorkflows()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    message.error(detail || t('workflow.tplFail'))
  } finally {
    instantiatingId.value = ''
  }
}
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
    const res = await listCanvases(undefined, workflowView.value || undefined)
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
    const res = await getWorkflows(workflowView.value ? { view: workflowView.value } : undefined)
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

// ── B5 自定义节点注册 ──
const showCustomNodeModal = ref(false)
const savingCustomNode = ref(false)
const customNodes = ref<Array<Record<string, unknown>>>([])
const customNodeForm = reactive({
  type: '',
  label: '',
  tier: 'declarative' as 'declarative' | 'composite',
  template: '',
  formSchemaJson: '',
})
async function loadCustomNodes() {
  try {
    const res = await listCustomNodes()
    const data = (res as unknown as { nodes?: Array<Record<string, unknown>> })?.nodes
      ?? (res as unknown as { data?: { nodes?: Array<Record<string, unknown>> } })?.data?.nodes
    customNodes.value = Array.isArray(data) ? data : []
  } catch {
    customNodes.value = []
  }
}
async function openCustomNodeModal() {
  showCustomNodeModal.value = true
  await loadCustomNodes()
}
function nodeErrorDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  return d ? JSON.stringify(d) : t('common.error')
}
async function submitCustomNode() {
  if (!customNodeForm.type.trim() || !customNodeForm.label.trim()) return
  savingCustomNode.value = true
  try {
    let formSchema: Array<Record<string, unknown>> = []
    if (customNodeForm.formSchemaJson.trim()) {
      formSchema = JSON.parse(customNodeForm.formSchemaJson)
    }
    const executorBody =
      customNodeForm.tier === 'declarative'
        ? { template: customNodeForm.template }
        : { steps: [] }
    await createCustomNode({
      type: customNodeForm.type.trim(),
      label: customNodeForm.label.trim(),
      tier: customNodeForm.tier,
      executor_body: executorBody,
      form_schema: formSchema,
    })
    message.success(t('common.success'))
    customNodeForm.type = ''
    customNodeForm.label = ''
    customNodeForm.template = ''
    customNodeForm.formSchemaJson = ''
    await loadCustomNodes()
  } catch (e: unknown) {
    message.error(nodeErrorDetail(e))
  } finally {
    savingCustomNode.value = false
  }
}
async function removeCustomNode(type: string) {
  try {
    await deleteCustomNode(type)
    await loadCustomNodes()
  } catch (e: unknown) {
    message.error(nodeErrorDetail(e))
  }
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
      alert(t('ui.jsonParseFailed'))
    }
  }
  reader.readAsText(file)
}

async function handleComfyuiImportSubmit() {
  if (!comfyuiImportForm.name) {
    alert(t('ui.enterWorkflowName'))
    return
  }
  if (!comfyuiImportForm.workflow) {
    alert(t('ui.selectComfyuiJson'))
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
  // 项目详情页"新建工作流"跳转携带 ?project=<id>：创建表单预填，保证归属
  const qp = route.query.project
  if (typeof qp === 'string' && qp) createForm.projectId = qp
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

.template-list { display: flex; flex-direction: column; gap: 10px; }
.template-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
}
.template-name { font-size: 14px; color: var(--nr-text-primary); }
.template-desc { margin-top: 2px; font-size: 12px; color: var(--nr-text-secondary); }
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
/* 项目归属筛选 */
.canvas-filter { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.canvas-filter .filter-label { font-size: 12px; color: var(--nr-text-secondary); }
.custom-node-list { display: flex; flex-direction: column; gap: 8px; max-height: 260px; overflow-y: auto; }
.custom-node-item { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; }
.custom-node-item code { color: var(--nr-text-secondary); }
</style>
