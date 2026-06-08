<template>
  <div class="workflow-canvas">
    <!-- 画布工具栏 -->
    <div class="canvas-toolbar">
      <div class="toolbar-left">
        <a-button-group size="small">
          <a-tooltip title="撤销">
            <a-button :disabled="!canUndo" @click="handleUndo">
              <undo-outlined />
            </a-button>
          </a-tooltip>
          <a-tooltip title="重做">
            <a-button :disabled="!canRedo" @click="handleRedo">
              <redo-outlined />
            </a-button>
          </a-tooltip>
        </a-button-group>
        
        <a-divider type="vertical" />
        
        <a-button-group size="small">
          <a-tooltip title="放大">
            <a-button @click="handleZoomIn">
              <zoom-in-outlined />
            </a-button>
          </a-tooltip>
          <a-tooltip title="缩小">
            <a-button @click="handleZoomOut">
              <zoom-out-outlined />
            </a-button>
          </a-tooltip>
          <a-tooltip title="适应画布">
            <a-button @click="handleFitView">
              <fullscreen-outlined />
            </a-button>
          </a-tooltip>
        </a-button-group>
        
        <a-divider type="vertical" />
        
        <a-button-group size="small">
          <a-tooltip title="删除选中">
            <a-button danger :disabled="!hasSelection" @click="handleDeleteSelected">
              <delete-outlined />
            </a-button>
          </a-tooltip>
          <a-tooltip title="复制选中">
            <a-button :disabled="!hasSelection" @click="handleCopySelected">
              <copy-outlined />
            </a-button>
          </a-tooltip>
          <a-tooltip title="粘贴">
            <a-button :disabled="!canPaste" @click="handlePaste">
              <snippets-outlined />
            </a-button>
          </a-tooltip>
        </a-button-group>
      </div>
      
      <div class="toolbar-right">
        <a-switch
          v-model:checked="showGrid"
          checked-children="网格"
          un-checked-children="网格"
          size="small"
        />
        <a-switch
          v-model:checked="showMinimap"
          checked-children="小地图"
          un-checked-children="小地图"
          size="small"
        />
        <a-switch
          v-model:checked="snapToGrid"
          checked-children="吸附"
          un-checked-children="吸附"
          size="small"
        />
      </div>
    </div>
    
    <!-- VueFlow 画布 -->
    <div class="canvas-container" @drop="handleDrop" @dragover="handleDragOver">
      <VueFlow
        ref="vueFlowRef"
        v-model:nodes="localNodes"
        v-model:edges="localEdges"
        :default-viewport="{ x: 0, y: 0, zoom: 1 }"
        :snap-to-grid="snapToGrid"
        :snap-grid="[gridSize, gridSize]"
        :min-zoom="0.1"
        :max-zoom="2"
        :fit-view-on-init="false"
        :nodes-draggable="!readonly"
        :nodes-connectable="!readonly"
        :edges-updatable="!readonly"
        :elements-selectable="true"
        :connection-line-type="ConnectionLineType.SmoothStep"
        @nodes-change="handleNodesChange"
        @edges-change="handleEdgesChange"
        @connect="handleConnect"
        @node-click="handleNodeClick"
        @edge-click="handleEdgeClick"
        @pane-click="handlePaneClick"
        @move-end="handleMoveEnd"
      >
        <!-- 背景 -->
        <Background v-if="showGrid" :variant="BackgroundVariant.Dots" :gap="gridSize" />
        
        <!-- 小地图 -->
        <MiniMap v-if="showMinimap" />
        
        <!-- 控制器 -->
        <Controls />
        
        <!-- 自定义节点 -->
        <template #node-default="nodeProps">
          <WorkflowNode v-bind="nodeProps" />
        </template>
        
        <!-- 自定义边 -->
        <template #edge-default="edgeProps">
          <WorkflowEdge v-bind="edgeProps" />
        </template>
      </VueFlow>
    </div>
    
    <!-- 选中节点信息 -->
    <div v-if="selectedNode" class="selection-info">
      <span class="selection-label">已选中:</span>
      <span class="selection-name">{{ selectedNode.label }}</span>
      <span class="selection-type">({{ selectedNode.type }})</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { VueFlow, ConnectionLineType, Background, BackgroundVariant, MiniMap, Controls } from '@vue-flow/core'
import type { NodeChange, EdgeChange, Connection } from '@vue-flow/core'
import {
  UndoOutlined,
  RedoOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  FullscreenOutlined,
  DeleteOutlined,
  CopyOutlined,
  SnippetsOutlined,
} from '@ant-design/icons-vue'
import type { WorkflowNode, WorkflowEdge, CanvasState } from '../types'
import { nodeRegistry, createEdgeFactory } from '../registry'
import WorkflowNode from './WorkflowNode.vue'
import WorkflowEdge from './WorkflowEdge.vue'

// ==================== Props ====================

interface Props {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  readonly?: boolean
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  readonly: false,
  loading: false,
})

// ==================== Emits ====================

const emit = defineEmits<{
  (e: 'update:nodes', nodes: WorkflowNode[]): void
  (e: 'update:edges', edges: WorkflowEdge[]): void
  (e: 'node-click', node: WorkflowNode): void
  (e: 'edge-click', edge: WorkflowEdge): void
  (e: 'pane-click'): void
  (e: 'selection-change', nodes: WorkflowNode[], edges: WorkflowEdge[]): void
  (e: 'viewport-change', viewport: { x: number; y: number; zoom: number }): void
  (e: 'save'): void
}>()

// ==================== 状态 ====================

const vueFlowRef = ref<any>(null)
const showGrid = ref(true)
const showMinimap = ref(false)
const snapToGrid = ref(true)
const gridSize = ref(20)
const selectedNode = ref<WorkflowNode | null>(null)

// 本地状态（用于双向绑定）
const localNodes = ref<WorkflowNode[]>([])
const localEdges = ref<WorkflowEdge[]>([])

// 历史记录
const history = ref<{
  past: Array<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }>
  future: Array<{ nodes: WorkflowNode[]; edges: WorkflowEdge[] }>
}>({
  past: [],
  future: [],
})

// 剪贴板
const clipboard = ref<{
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
} | null>(null)

// ==================== 计算属性 ====================

const canUndo = computed(() => history.value.past.length > 0)
const canRedo = computed(() => history.value.future.length > 0)
const hasSelection = computed(() => selectedNode.value !== null)
const canPaste = computed(() => clipboard.value !== null)

// ==================== 方法 ====================

/**
 * 保存当前状态到历史
 */
function saveToHistory() {
  history.value.past.push({
    nodes: [...localNodes.value],
    edges: [...localEdges.value],
  })
  history.value.future = []
  
  // 限制历史记录大小
  if (history.value.past.length > 50) {
    history.value.past.shift()
  }
}

/**
 * 撤销
 */
function handleUndo() {
  if (!canUndo.value) return
  
  const previous = history.value.past.pop()!
  history.value.future.push({
    nodes: [...localNodes.value],
    edges: [...localEdges.value],
  })
  
  localNodes.value = previous.nodes
  localEdges.value = previous.edges
  emitChanges()
}

/**
 * 重做
 */
function handleRedo() {
  if (!canRedo.value) return
  
  const next = history.value.future.pop()!
  history.value.past.push({
    nodes: [...localNodes.value],
    edges: [...localEdges.value],
  })
  
  localNodes.value = next.nodes
  localEdges.value = next.edges
  emitChanges()
}

/**
 * 放大
 */
function handleZoomIn() {
  vueFlowRef.value?.zoomIn()
}

/**
 * 缩小
 */
function handleZoomOut() {
  vueFlowRef.value?.zoomOut()
}

/**
 * 适应画布
 */
function handleFitView() {
  vueFlowRef.value?.fitView({ padding: 0.2 })
}

/**
 * 删除选中
 */
function handleDeleteSelected() {
  if (!selectedNode.value) return
  
  saveToHistory()
  
  const nodeId = selectedNode.value.id
  localNodes.value = localNodes.value.filter(n => n.id !== nodeId)
  localEdges.value = localEdges.value.filter(e => e.source !== nodeId && e.target !== nodeId)
  
  selectedNode.value = null
  emitChanges()
}

/**
 * 复制选中
 */
function handleCopySelected() {
  if (!selectedNode.value) return
  
  clipboard.value = {
    nodes: [selectedNode.value],
    edges: localEdges.value.filter(e => 
      e.source === selectedNode.value!.id || e.target === selectedNode.value!.id
    ),
  }
}

/**
 * 粘贴
 */
function handlePaste() {
  if (!clipboard.value) return
  
  saveToHistory()
  
  const offset = { x: 50, y: 50 }
  const nodeMap = new Map<string, string>()
  
  // 粘贴节点
  const newNodes = clipboard.value.nodes.map(node => {
    const newId = `${node.id}_copy_${Date.now()}`
    nodeMap.set(node.id, newId)
    
    return {
      ...node,
      id: newId,
      position: {
        x: node.position.x + offset.x,
        y: node.position.y + offset.y,
      },
    }
  })
  
  // 粘贴边
  const newEdges = clipboard.value.edges.map(edge => ({
    ...edge,
    id: `${edge.id}_copy_${Date.now()}`,
    source: nodeMap.get(edge.source) || edge.source,
    target: nodeMap.get(edge.target) || edge.target,
  }))
  
  localNodes.value = [...localNodes.value, ...newNodes]
  localEdges.value = [...localEdges.value, ...newEdges]
  
  emitChanges()
}

/**
 * 处理节点变化
 */
function handleNodesChange(changes: NodeChange[]) {
  // VueFlow 会自动处理节点变化
}

/**
 * 处理边变化
 */
function handleEdgesChange(changes: EdgeChange[]) {
  // VueFlow 会自动处理边变化
}

/**
 * 处理连接
 */
function handleConnect(connection: Connection) {
  saveToHistory()
  
  const edgeFactory = createEdgeFactory()
  const newEdge = edgeFactory(
    connection.source,
    connection.target,
    connection.sourceHandle,
    connection.targetHandle
  )
  
  localEdges.value = [...localEdges.value, newEdge]
  emitChanges()
}

/**
 * 处理节点点击
 */
function handleNodeClick(event: { node: WorkflowNode }) {
  selectedNode.value = event.node
  emit('node-click', event.node)
  emitSelectionChange()
}

/**
 * 处理边点击
 */
function handleEdgeClick(event: { edge: WorkflowEdge }) {
  emit('edge-click', event.edge)
}

/**
 * 处理画布点击
 */
function handlePaneClick() {
  selectedNode.value = null
  emit('pane-click')
  emitSelectionChange()
}

/**
 * 处理移动结束
 */
function handleMoveEnd(event: { viewport: { x: number; y: number; zoom: number } }) {
  emit('viewport-change', event.viewport)
}

/**
 * 处理拖拽进入
 */
function handleDragOver(event: DragEvent) {
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

/**
 * 处理拖拽放置
 */
function handleDrop(event: DragEvent) {
  event.preventDefault()
  
  const data = event.dataTransfer?.getData('application/neurflow-node')
  if (!data) return
  
  try {
    const nodeData = JSON.parse(data)
    const nodeDef = nodeRegistry.get(nodeData.type)
    if (!nodeDef) return
    
    // 计算放置位置
    const position = vueFlowRef.value?.screenToFlowCoordinate({
      x: event.clientX,
      y: event.clientY,
    }) || { x: event.clientX, y: event.clientY }
    
    // 创建新节点
    const newNode: WorkflowNode = {
      id: `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      type: nodeDef.type,
      label: nodeDef.label,
      position,
      data: {},
      subBlocks: {},
      inputs: {},
      outputs: {},
    }
    
    saveToHistory()
    localNodes.value = [...localNodes.value, newNode]
    emitChanges()
  } catch (error) {
    console.error('Failed to parse dropped node:', error)
  }
}

/**
 * 发出变化事件
 */
function emitChanges() {
  emit('update:nodes', localNodes.value)
  emit('update:edges', localEdges.value)
}

/**
 * 发出选择变化事件
 */
function emitSelectionChange() {
  emit('selection-change', selectedNode.value ? [selectedNode.value] : [], [])
}

// ==================== 监听器 ====================

watch(
  () => props.nodes,
  (newNodes) => {
    localNodes.value = [...newNodes]
  },
  { immediate: true, deep: true }
)

watch(
  () => props.edges,
  (newEdges) => {
    localEdges.value = [...newEdges]
  },
  { immediate: true, deep: true }
)

// ==================== 键盘快捷键 ====================

function handleKeyDown(event: KeyboardEvent) {
  // Ctrl+Z: 撤销
  if (event.ctrlKey && event.key === 'z') {
    event.preventDefault()
    handleUndo()
  }
  
  // Ctrl+Shift+Z: 重做
  if (event.ctrlKey && event.shiftKey && event.key === 'z') {
    event.preventDefault()
    handleRedo()
  }
  
  // Ctrl+C: 复制
  if (event.ctrlKey && event.key === 'c') {
    event.preventDefault()
    handleCopySelected()
  }
  
  // Ctrl+V: 粘贴
  if (event.ctrlKey && event.key === 'v') {
    event.preventDefault()
    handlePaste()
  }
  
  // Delete: 删除
  if (event.key === 'Delete' || event.key === 'Backspace') {
    if (selectedNode.value) {
      event.preventDefault()
      handleDeleteSelected()
    }
  }
  
  // Ctrl+S: 保存
  if (event.ctrlKey && event.key === 's') {
    event.preventDefault()
    emit('save')
  }
}

// ==================== 生命周期 ====================

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<style scoped>
.workflow-canvas {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}

.canvas-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.canvas-container {
  flex: 1;
  position: relative;
}

.selection-info {
  position: absolute;
  bottom: 16px;
  left: 16px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.75);
  color: #fff;
  border-radius: 6px;
  font-size: 12px;
}

.selection-label {
  margin-right: 8px;
  opacity: 0.7;
}

.selection-name {
  font-weight: 500;
}

.selection-type {
  margin-left: 4px;
  opacity: 0.7;
}
</style>
