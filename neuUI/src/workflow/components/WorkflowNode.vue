<template>
  <div
    :class="[
      'workflow-node',
      `node-source-${nodeDef?.source || 'builtin'}`,
      `node-category-${nodeDef?.category || 'custom'}`,
      {
        'node-selected': selected,
        'node-disabled': data.disabled,
        'node-running': isRunning,
        'node-error': hasError,
      }
    ]"
    :style="nodeStyle"
    @click.stop="handleClick"
    @dblclick.stop="handleDoubleClick"
  >
    <!-- 节点头部 -->
    <div class="node-header" :style="headerStyle">
      <div class="node-icon">
        <component :is="iconComponent" v-if="iconComponent" />
        <span v-else class="node-emoji">{{ nodeDef?.icon || '⚙️' }}</span>
      </div>
      <div class="node-title">
        <span class="node-label">{{ data.label || nodeDef?.label || 'Node' }}</span>
        <span v-if="nodeDef?.source !== 'builtin'" class="node-source-badge">
          {{ sourceBadge }}
        </span>
      </div>
      <div class="node-actions">
        <a-tooltip title="配置">
          <a-button type="text" size="small" @click.stop="handleConfig">
            <template #icon>
              <SettingOutlined />
            </template>
          </a-button>
        </a-tooltip>
        <a-tooltip title="删除">
          <a-button type="text" size="small" danger @click.stop="handleDelete">
            <template #icon>
              <DeleteOutlined />
            </template>
          </a-button>
        </a-tooltip>
      </div>
    </div>

    <!-- 节点内容 -->
    <div class="node-content">
      <!-- 输入端口 -->
      <div class="node-inputs">
        <div
          v-for="port in nodeDef?.inputs || []"
          :key="port.id"
          class="node-port input-port"
        >
          <Handle
            :id="port.id"
            type="target"
            :position="Position.Left"
            :style="getPortStyle(port)"
          />
          <span class="port-label">{{ port.name }}</span>
        </div>
      </div>

      <!-- 节点主体 -->
      <div class="node-body">
        <!-- 状态指示器 -->
        <div v-if="isRunning || hasError" class="node-status">
          <LoadingOutlined v-if="isRunning" spin class="status-icon running" />
          <ExclamationCircleOutlined v-else-if="hasError" class="status-icon error" />
        </div>

        <!-- 节点预览 -->
        <div v-if="previewText" class="node-preview">
          {{ previewText }}
        </div>

        <!-- 端口数量指示 -->
        <div class="node-ports-summary">
          <span v-if="(nodeDef?.inputs || []).length > 0" class="ports-count">
            {{ (nodeDef?.inputs || []).length }} 输入
          </span>
          <span v-if="(nodeDef?.outputs || []).length > 0" class="ports-count">
            {{ (nodeDef?.outputs || []).length }} 输出
          </span>
        </div>
      </div>

      <!-- 输出端口 -->
      <div class="node-outputs">
        <div
          v-for="port in nodeDef?.outputs || []"
          :key="port.id"
          class="node-port output-port"
        >
          <span class="port-label">{{ port.name }}</span>
          <Handle
            :id="port.id"
            type="source"
            :position="Position.Right"
            :style="getPortStyle(port)"
          />
        </div>
      </div>
    </div>

    <!-- 节点标签（如果有） -->
    <div v-if="data.notes" class="node-notes">
      <FileTextOutlined />
      <span>{{ data.notes }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  SettingOutlined,
  DeleteOutlined,
  LoadingOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
} from '@ant-design/icons-vue'
import { nodeRegistry, getNodeColor } from '../registry'
import type { WorkflowNode, NodeDefinition, NodePort } from '../types'

// ==================== Props ====================

interface Props {
  id: string
  data: WorkflowNode['data']
  type: string
  selected?: boolean
  sourcePosition?: Position
  targetPosition?: Position
  isConnectable?: boolean
  zIndex?: number
  dimensions?: { width: number; height: number }
  parentNode?: string
  dragging?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  selected: false,
  isConnectable: true,
  zIndex: 1,
  dragging: false,
})

// ==================== Emits ====================

const emit = defineEmits<{
  (e: 'click', node: WorkflowNode): void
  (e: 'dblclick', node: WorkflowNode): void
  (e: 'config', node: WorkflowNode): void
  (e: 'delete', nodeId: string): void
  (e: 'update:data', data: Record<string, any>): void
}>()

// ==================== 状态 ====================

const isRunning = ref(false)
const hasError = ref(false)

// ==================== 计算属性 ====================

/**
 * 获取节点定义
 */
const nodeDef = computed<NodeDefinition | undefined>(() => {
  return nodeRegistry.get(props.type)
})

/**
 * 节点样式
 */
const nodeStyle = computed(() => {
  const color = nodeDef.value ? getNodeColor(nodeDef.value) : '#8c8c8c'
  return {
    '--node-color': color,
    '--node-color-light': `${color}20`,
    '--node-color-dark': `${color}cc`,
  }
})

/**
 * 头部样式
 */
const headerStyle = computed(() => {
  const color = nodeDef.value ? getNodeColor(nodeDef.value) : '#8c8c8c'
  return {
    backgroundColor: color,
  }
})

/**
 * 图标组件
 */
const iconComponent = computed(() => {
  // 这里可以根据 icon 名称返回对应的图标组件
  // 目前返回 undefined，使用 emoji 回退
  return undefined
})

/**
 * 来源徽章
 */
const sourceBadge = computed(() => {
  const source = nodeDef.value?.source
  switch (source) {
    case 'tool': return 'T'
    case 'skill': return 'S'
    case 'mcp': return 'M'
    case 'builtin': return 'B'
    default: return '?'
  }
})

/**
 * 预览文本
 */
const previewText = computed(() => {
  const data = props.data
  if (!data) return ''

  // 根据节点类型显示不同的预览
  const type = props.type
  if (type === 'llm') {
    const model = data.model || data.subBlocks?.model
    if (model) return `模型: ${model}`
    const prompt = data.prompt || data.subBlocks?.prompt
    if (prompt) return prompt.substring(0, 50) + (prompt.length > 50 ? '...' : '')
  }
  if (type === 'condition') {
    const field = data.field || data.subBlocks?.field
    if (field) return `字段: ${field}`
  }
  if (type === 'code') {
    const language = data.language || data.subBlocks?.language
    if (language) return `语言: ${language}`
  }
  if (type === 'http') {
    const url = data.url || data.subBlocks?.url
    if (url) return url.substring(0, 40) + (url.length > 40 ? '...' : '')
  }

  // 默认显示第一个子块的值
  const firstBlock = nodeDef.value?.subBlocks?.[0]
  if (firstBlock) {
    const value = data[firstBlock.id] || data.subBlocks?.[firstBlock.id]
    if (value !== undefined && value !== null) {
      const strValue = String(value)
      return strValue.substring(0, 50) + (strValue.length > 50 ? '...' : '')
    }
  }

  return ''
})

// ==================== 方法 ====================

/**
 * 获取端口样式
 */
function getPortStyle(port: NodePort) {
  const color = nodeDef.value ? getNodeColor(nodeDef.value) : '#8c8c8c'
  return {
    backgroundColor: color,
    borderColor: color,
    width: '12px',
    height: '12px',
  }
}

/**
 * 处理点击
 */
function handleClick() {
  emit('click', {
    id: props.id,
    type: props.type,
    label: props.data?.label || nodeDef.value?.label || 'Node',
    position: { x: 0, y: 0 },
    data: props.data,
  })
}

/**
 * 处理双击
 */
function handleDoubleClick() {
  emit('dblclick', {
    id: props.id,
    type: props.type,
    label: props.data?.label || nodeDef.value?.label || 'Node',
    position: { x: 0, y: 0 },
    data: props.data,
  })
}

/**
 * 处理配置
 */
function handleConfig() {
  emit('config', {
    id: props.id,
    type: props.type,
    label: props.data?.label || nodeDef.value?.label || 'Node',
    position: { x: 0, y: 0 },
    data: props.data,
  })
}

/**
 * 处理删除
 */
function handleDelete() {
  emit('delete', props.id)
}

// ==================== 生命周期 ====================

onMounted(() => {
  // 可以在这里添加初始化逻辑
})
</script>

<style scoped>
.workflow-node {
  background: #fff;
  border: 2px solid var(--node-color, #8c8c8c);
  border-radius: 8px;
  min-width: 200px;
  max-width: 300px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
  cursor: pointer;
  position: relative;
}

.workflow-node:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transform: translateY(-2px);
}

.workflow-node.node-selected {
  border-color: #1890ff;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
}

.workflow-node.node-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.workflow-node.node-running {
  border-color: #1890ff;
  animation: pulse 1.5s infinite;
}

.workflow-node.node-error {
  border-color: #ff4d4f;
}

@keyframes pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(24, 144, 255, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(24, 144, 255, 0);
  }
}

.node-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px 6px 0 0;
  color: white;
}

.node-icon {
  margin-right: 8px;
  font-size: 16px;
}

.node-emoji {
  font-size: 18px;
}

.node-title {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.node-label {
  font-weight: 500;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-source-badge {
  background: rgba(255, 255, 255, 0.3);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}

.node-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.workflow-node:hover .node-actions {
  opacity: 1;
}

.node-content {
  display: flex;
  padding: 12px;
  gap: 12px;
}

.node-inputs,
.node-outputs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 80px;
}

.node-inputs {
  align-items: flex-start;
}

.node-outputs {
  align-items: flex-end;
}

.node-port {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
}

.input-port {
  flex-direction: row;
}

.output-port {
  flex-direction: row-reverse;
}

.port-label {
  font-size: 12px;
  color: #666;
  white-space: nowrap;
}

.node-body {
  flex: 1;
  min-width: 0;
}

.node-status {
  margin-bottom: 8px;
}

.status-icon {
  font-size: 16px;
}

.status-icon.running {
  color: #1890ff;
}

.status-icon.error {
  color: #ff4d4f;
}

.node-preview {
  font-size: 12px;
  color: #666;
  background: #f5f5f5;
  padding: 6px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
  word-break: break-all;
}

.node-ports-summary {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.ports-count {
  font-size: 11px;
  color: #999;
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
}

.node-notes {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-top: 1px solid #f0f0f0;
  font-size: 12px;
  color: #666;
  background: #fafafa;
  border-radius: 0 0 6px 6px;
}

/* VueFlow 样式覆盖 */
:deep(.vue-flow__handle) {
  width: 12px;
  height: 12px;
  border: 2px solid white;
}

:deep(.vue-flow__handle-left) {
  left: -6px;
}

:deep(.vue-flow__handle-right) {
  right: -6px;
}

:deep(.vue-flow__handle-top) {
  top: -6px;
}

:deep(.vue-flow__handle-bottom) {
  bottom: -6px;
}

/* 节点类型特殊样式 */
.node-source-tool {
  border-style: solid;
}

.node-source-skill {
  border-style: dashed;
}

.node-source-mcp {
  border-style: dotted;
}

/* 节点类别特殊样式 */
.node-category-input {
  border-left: 4px solid #52c41a;
}

.node-category-output {
  border-right: 4px solid #faad14;
}

.node-category-control {
  border-left: 4px solid #eb2f96;
}

.node-category-ai {
  border-left: 4px solid #722ed1;
}

.node-category-memory {
  border-left: 4px solid #2f54eb;
}
</style>