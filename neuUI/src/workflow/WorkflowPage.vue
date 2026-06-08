<template>
  <div class="workflow-page">
    <!-- 顶栏 -->
    <div class="workflow-header">
      <div class="header-left">
        <a-input
          v-model:value="workflowName"
          class="workflow-name-input"
          placeholder="工作流名称"
          @change="handleNameChange"
        />
        <a-tag v-if="workflowStatus" :color="statusColor">{{ workflowStatus }}</a-tag>
      </div>
      
      <div class="header-center">
        <a-button-group size="small">
          <a-button @click="handleSave" :loading="saving">
            <save-outlined />
            保存
          </a-button>
          <a-button @click="handlePublish" :loading="publishing">
            <upload-outlined />
            发布
          </a-button>
          <a-button type="primary" @click="handleExecute" :loading="executing">
            <play-outlined />
            执行
          </a-button>
        </a-button-group>
      </div>
      
      <div class="header-right">
        <a-button-group size="small">
          <a-button @click="handleValidate">
            <check-circle-outlined />
            验证
          </a-button>
          <a-button @click="handleExport">
            <export-outlined />
            导出
          </a-button>
          <a-button @click="handleImport">
            <import-outlined />
            导入
          </a-button>
        </a-button-group>
      </div>
    </div>
    
    <!-- 主要内容区域 -->
    <div class="workflow-content">
      <!-- 左侧节点面板 -->
      <div class="node-palette-container">
        <NodePalette
          @node-drag-start="handleNodeDragStart"
          @node-click="handleNodeClick"
        />
      </div>
      
      <!-- 中间画布 -->
      <div class="canvas-container">
        <WorkflowCanvas
          ref="canvasRef"
          :nodes="nodes"
          :edges="edges"
          @nodes-change="handleNodesChange"
          @edges-change="handleEdgesChange"
          @node-click="handleCanvasNodeClick"
          @edge-click="handleCanvasEdgeClick"
          @pane-click="handlePaneClick"
        />
      </div>
      
      <!-- 右侧配置面板 -->
      <div class="inspector-container">
        <NodeInspector
          v-if="selectedNode"
          :node="selectedNode"
          @update="handleNodeUpdate"
          @close="handleInspectorClose"
        />
        <div v-else class="inspector-empty">
          <div class="empty-icon">
            <setting-outlined />
          </div>
          <div class="empty-text">选择节点以查看配置</div>
        </div>
      </div>
    </div>
    
    <!-- 底部执行面板 -->
    <div class="execution-panel-container" :class="{ expanded: showExecutionPanel }">
      <div class="panel-header" @click="toggleExecutionPanel">
        <div class="panel-title">
          <dashboard-outlined />
          执行面板
        </div>
        <div class="panel-actions">
          <a-badge :count="errorCount" :offset="[-5, 0]">
            <a-button size="small" @click.stop="clearLogs">
              清空
            </a-button>
          </a-badge>
          <a-button size="small" @click.stop="toggleExecutionPanel">
            <up-outlined v-if="showExecutionPanel" />
            <down-outlined v-else />
          </a-button>
        </div>
      </div>
      
      <div v-show="showExecutionPanel" class="panel-content">
        <ExecutionPanel
          :logs="executionLogs"
          :status="executionStatus"
          :progress="executionProgress"
          :current-node="currentNode"
          @cancel="handleCancelExecution"
          @resume="handleResumeExecution"
          @clear="clearLogs"
        />
      </div>
    </div>
    
    <!-- 验证结果对话框 -->
    <a-modal
      v-model:open="showValidationModal"
      title="验证结果"
      :footer="null"
      width="600px"
    >
      <ValidationResult :result="validationResult" />
    </a-modal>
    
    <!-- 导入对话框 -->
    <a-modal
      v-model:open="showImportModal"
      title="导入工作流"
      @ok="handleImportConfirm"
      @cancel="showImportModal = false"
    >
      <a-form layout="vertical">
        <a-form-item label="选择文件">
          <a-upload
            :before-upload="handleFileUpload"
            :show-upload-list="false"
          >
            <a-button>
              <upload-outlined />
              选择文件
            </a-button>
          </a-upload>
        </a-form-item>
        <a-form-item v-if="importFile" label="文件信息">
          <div>文件名: {{ importFile.name }}</div>
          <div>大小: {{ formatFileSize(importFile.size) }}</div>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  SaveOutlined,
  UploadOutlined,
  PlayOutlined,
  CheckCircleOutlined,
  ExportOutlined,
  ImportOutlined,
  SettingOutlined,
  DashboardOutlined,
  UpOutlined,
  DownOutlined,
} from '@ant-design/icons-vue'
import WorkflowCanvas from './components/WorkflowCanvas.vue'
import NodePalette from './components/NodePalette.vue'
import NodeInspector from './components/NodeInspector.vue'
import ExecutionPanel from './components/ExecutionPanel.vue'
import { useWorkflowStore } from './composables/useWorkflowStore'
import { useExecutionState } from './composables/useExecution'
import { validateWorkflow } from './validation'
import { exportWorkflow, importWorkflow } from './serializer'
import type { WorkflowNode, WorkflowEdge, ValidationResult } from './types'

// Store
const workflowStore = useWorkflowStore()
const executionState = useExecutionState()

// 状态
const canvasRef = ref<InstanceType<typeof WorkflowCanvas>>()
const workflowName = ref('')
const workflowStatus = ref('')
const selectedNode = ref<WorkflowNode | null>(null)
const showExecutionPanel = ref(false)
const showValidationModal = ref(false)
const showImportModal = ref(false)
const validationResult = ref<ValidationResult | null>(null)
const importFile = ref<File | null>(null)
const saving = ref(false)
const publishing = ref(false)
const executing = ref(false)

// 计算属性
const nodes = computed(() => workflowStore.nodes)
const edges = computed(() => workflowStore.edges)
const statusColor = computed(() => {
  switch (workflowStatus.value) {
    case 'draft': return 'default'
    case 'published': return 'green'
    case 'archived': return 'orange'
    default: return 'default'
  }
})

const errorCount = computed(() => {
  return executionState.logs.value.filter(log => log.level === 'error').length
})

const executionLogs = computed(() => executionState.logs.value)
const executionStatus = computed(() => {
  if (executionState.isRunning.value) return 'running'
  if (executionState.isPaused.value) return 'paused'
  if (executionState.isCompleted.value) return 'completed'
  if (executionState.isFailed.value) return 'failed'
  return 'idle'
})
const executionProgress = computed(() => executionState.progress.value)
const currentNode = computed(() => executionState.currentNodeId.value)

// 初始化
onMounted(async () => {
  try {
    await workflowStore.loadWorkflow()
    workflowName.value = workflowStore.currentWorkflow?.name || '未命名工作流'
    workflowStatus.value = workflowStore.currentWorkflow?.status || 'draft'
  } catch (error) {
    message.error('加载工作流失败')
    console.error(error)
  }
})

// 监听工作流变化
watch(() => workflowStore.currentWorkflow, (workflow) => {
  if (workflow) {
    workflowName.value = workflow.name
    workflowStatus.value = workflow.status
  }
})

// 节点拖拽开始
function handleNodeDragStart(nodeType: string) {
  // 这里可以添加拖拽视觉反馈
  console.log('Node drag started:', nodeType)
}

// 节点点击（从面板）
function handleNodeClick(nodeType: string) {
  // 可以预览节点信息
  console.log('Node clicked:', nodeType)
}

// 画布节点变化
function handleNodesChange(changes: any[]) {
  workflowStore.applyNodeChanges(changes)
}

// 画布边变化
function handleEdgesChange(changes: any[]) {
  workflowStore.applyEdgeChanges(changes)
}

// 画布节点点击
function handleCanvasNodeClick(node: WorkflowNode) {
  selectedNode.value = node
}

// 画布边点击
function handleCanvasEdgeClick(edge: WorkflowEdge) {
  // 可以显示边配置
  console.log('Edge clicked:', edge)
}

// 画布空白区域点击
function handlePaneClick() {
  selectedNode.value = null
}

// 节点更新
function handleNodeUpdate(updatedNode: WorkflowNode) {
  workflowStore.updateNode(updatedNode)
}

// 关闭检查器
function handleInspectorClose() {
  selectedNode.value = null
}

// 名称变化
function handleNameChange() {
  if (workflowStore.currentWorkflow) {
    workflowStore.currentWorkflow.name = workflowName.value
  }
}

// 切换执行面板
function toggleExecutionPanel() {
  showExecutionPanel.value = !showExecutionPanel.value
}

// 清空日志
function clearLogs() {
  executionState.resetState()
}

// 保存工作流
async function handleSave() {
  saving.value = true
  try {
    await workflowStore.saveWorkflow()
    message.success('保存成功')
  } catch (error) {
    message.error('保存失败')
    console.error(error)
  } finally {
    saving.value = false
  }
}

// 发布工作流
async function handlePublish() {
  publishing.value = true
  try {
    await workflowStore.publishWorkflow()
    workflowStatus.value = 'published'
    message.success('发布成功')
  } catch (error) {
    message.error('发布失败')
    console.error(error)
  } finally {
    publishing.value = false
  }
}

// 执行工作流
async function handleExecute() {
  executing.value = true
  showExecutionPanel.value = true
  
  try {
    const workflowId = workflowStore.currentWorkflow?.id
    if (!workflowId) {
      throw new Error('工作流未保存')
    }
    
    await executionState.startExecution(workflowId)
    message.success('执行已开始')
  } catch (error) {
    message.error('执行失败')
    console.error(error)
  } finally {
    executing.value = false
  }
}

// 取消执行
async function handleCancelExecution() {
  try {
    await executionState.cancelExecution()
    message.success('执行已取消')
  } catch (error) {
    message.error('取消失败')
    console.error(error)
  }
}

// 恢复执行
async function handleResumeExecution() {
  try {
    await executionState.resumeExecution()
    message.success('执行已恢复')
  } catch (error) {
    message.error('恢复失败')
    console.error(error)
  }
}

// 验证工作流
function handleValidate() {
  const workflow = workflowStore.currentWorkflow
  if (!workflow) {
    message.warning('没有可验证的工作流')
    return
  }
  
  validationResult.value = validateWorkflow(workflow)
  showValidationModal.value = true
  
  if (validationResult.value.valid) {
    message.success('验证通过')
  } else {
    message.warning(`发现 ${validationResult.value.errors.length} 个错误`)
  }
}

// 导出工作流
function handleExport() {
  const workflow = workflowStore.currentWorkflow
  if (!workflow) {
    message.warning('没有可导出的工作流')
    return
  }
  
  try {
    const json = exportWorkflow(workflow, 'json')
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${workflow.name || 'workflow'}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('导出成功')
  } catch (error) {
    message.error('导出失败')
    console.error(error)
  }
}

// 导入工作流
function handleImport() {
  importFile.value = null
  showImportModal.value = true
}

// 文件上传
function handleFileUpload(file: File) {
  importFile.value = file
  return false
}

// 确认导入
async function handleImportConfirm() {
  if (!importFile.value) {
    message.warning('请选择文件')
    return
  }
  
  try {
    const text = await importFile.value.text()
    const workflow = importWorkflow(text)
    
    Modal.confirm({
      title: '导入确认',
      content: `确定要导入工作流 "${workflow.name}" 吗？这将覆盖当前工作流。`,
      onOk: async () => {
        await workflowStore.loadWorkflowData(workflow)
        workflowName.value = workflow.name
        workflowStatus.value = workflow.status
        showImportModal.value = false
        message.success('导入成功')
      },
    })
  } catch (error) {
    message.error('导入失败: ' + (error as Error).message)
    console.error(error)
  }
}

// 格式化文件大小
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
.workflow-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f5f5;
}

.workflow-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: white;
  border-bottom: 1px solid #e8e8e8;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.workflow-name-input {
  width: 200px;
  font-size: 16px;
  font-weight: 500;
}

.header-center {
  display: flex;
  align-items: center;
}

.header-right {
  display: flex;
  align-items: center;
}

.workflow-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.node-palette-container {
  width: 280px;
  background: white;
  border-right: 1px solid #e8e8e8;
  overflow-y: auto;
}

.canvas-container {
  flex: 1;
  position: relative;
}

.inspector-container {
  width: 320px;
  background: white;
  border-left: 1px solid #e8e8e8;
  overflow-y: auto;
}

.inspector-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #999;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-text {
  font-size: 14px;
}

.execution-panel-container {
  background: white;
  border-top: 1px solid #e8e8e8;
  transition: height 0.3s ease;
}

.execution-panel-container.expanded {
  height: 300px;
}

.execution-panel-container:not(.expanded) {
  height: 40px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  cursor: pointer;
  border-bottom: 1px solid #e8e8e8;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-content {
  height: calc(100% - 40px);
  overflow: hidden;
}
</style>