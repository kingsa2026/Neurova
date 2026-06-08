<template>
  <div class="node-inspector">
    <!-- 未选中节点提示 -->
    <div v-if="!selectedNode" class="empty-state">
      <a-empty description="请选择一个节点" :image-style="{ height: '60px' }" />
    </div>
    
    <!-- 节点配置 -->
    <div v-else class="inspector-content">
      <!-- 节点头部 -->
      <div class="inspector-header">
        <div class="node-icon" :style="{ backgroundColor: getNodeColor(nodeDefinition) }">
          {{ getNodeIcon(nodeDefinition) }}
        </div>
        <div class="node-title">
          <div class="node-label">{{ selectedNode.label }}</div>
          <div class="node-type">{{ selectedNode.type }}</div>
        </div>
        <div class="node-actions">
          <a-tooltip title="复制节点">
            <a-button type="text" size="small" @click="handleCopy">
              <copy-outlined />
            </a-button>
          </a-tooltip>
          <a-tooltip title="删除节点">
            <a-button type="text" size="small" danger @click="handleDelete">
              <delete-outlined />
            </a-button>
          </a-tooltip>
        </div>
      </div>
      
      <!-- 基本信息 -->
      <div class="inspector-section">
        <div class="section-title">基本信息</div>
        <a-form layout="vertical" size="small">
          <a-form-item label="节点标签">
            <a-input
              v-model:value="localLabel"
              @change="handleLabelChange"
            />
          </a-form-item>
          
          <a-form-item label="节点备注">
            <a-textarea
              v-model:value="localNotes"
              :rows="2"
              placeholder="添加备注..."
              @change="handleNotesChange"
            />
          </a-form-item>
        </a-form>
      </div>
      
      <!-- 参数配置 -->
      <div v-if="nodeDefinition?.subBlocks?.length" class="inspector-section">
        <div class="section-title">参数配置</div>
        <SubBlockRenderer
          :blocks="nodeDefinition.subBlocks"
          :values="localSubBlocks"
          @update:values="handleSubBlocksChange"
          @change="handleSubBlockChange"
        />
      </div>
      
      <!-- 输入端口 -->
      <div v-if="nodeDefinition?.inputs?.length" class="inspector-section">
        <div class="section-title">输入端口</div>
        <div class="ports-list">
          <div
            v-for="port in nodeDefinition.inputs"
            :key="port.id"
            class="port-item"
          >
            <div class="port-info">
              <span class="port-name">{{ port.name }}</span>
              <a-tag size="small" color="blue">{{ port.type }}</a-tag>
            </div>
            <div v-if="port.description" class="port-description">
              {{ port.description }}
            </div>
            <a-input
              v-if="localInputs[port.id] !== undefined"
              v-model:value="localInputs[port.id]"
              size="small"
              placeholder="输入值或变量引用"
              @change="handleInputChange(port.id, $event)"
            />
          </div>
        </div>
      </div>
      
      <!-- 输出端口 -->
      <div v-if="nodeDefinition?.outputs?.length" class="inspector-section">
        <div class="section-title">输出端口</div>
        <div class="ports-list">
          <div
            v-for="port in nodeDefinition.outputs"
            :key="port.id"
            class="port-item"
          >
            <div class="port-info">
              <span class="port-name">{{ port.name }}</span>
              <a-tag size="small" color="green">{{ port.type }}</a-tag>
            </div>
            <div v-if="port.description" class="port-description">
              {{ port.description }}
            </div>
          </div>
        </div>
      </div>
      
      <!-- 节点信息 -->
      <div class="inspector-section">
        <div class="section-title">节点信息</div>
        <a-descriptions size="small" :column="1">
          <a-descriptions-item label="来源">
            <a-tag :color="getSourceColor(nodeDefinition?.source)">
              {{ getSourceLabel(nodeDefinition?.source) }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="分类">
            {{ getCategoryLabel(nodeDefinition?.category) }}
          </a-descriptions-item>
          <a-descriptions-item v-if="nodeDefinition?.version" label="版本">
            {{ nodeDefinition.version }}
          </a-descriptions-item>
          <a-descriptions-item v-if="nodeDefinition?.author" label="作者">
            {{ nodeDefinition.author }}
          </a-descriptions-item>
          <a-descriptions-item label="节点 ID">
            <a-typography-paragraph copyable :content="selectedNode.id" />
          </a-descriptions-item>
        </a-descriptions>
      </div>
      
      <!-- 标签 -->
      <div v-if="nodeDefinition?.tags?.length" class="inspector-section">
        <div class="section-title">标签</div>
        <div class="tags-container">
          <a-tag v-for="tag in nodeDefinition.tags" :key="tag" color="processing">
            {{ tag }}
          </a-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  CopyOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import type { WorkflowNode, NodeDefinition } from '../types'
import { nodeRegistry, getNodeColor, getNodeIcon } from '../registry'
import SubBlockRenderer from './SubBlockRenderer.vue'

// ==================== Props ====================

interface Props {
  selectedNode: WorkflowNode | null
  nodeDefinition: NodeDefinition | null
}

const props = defineProps<Props>()

// ==================== Emits ====================

const emit = defineEmits<{
  (e: 'update:node', node: WorkflowNode): void
  (e: 'copy', node: WorkflowNode): void
  (e: 'delete', nodeId: string): void
  (e: 'change', node: WorkflowNode): void
}>()

// ==================== 状态 ====================

const localLabel = ref('')
const localNotes = ref('')
const localSubBlocks = ref<Record<string, any>>({})
const localInputs = ref<Record<string, any>>({})

// ==================== 计算属性 ====================

// ==================== 方法 ====================

/**
 * 获取来源标签
 */
function getSourceLabel(source?: string): string {
  const labels: Record<string, string> = {
    builtin: '内置',
    tool: '工具',
    skill: '技能',
    mcp: 'MCP',
  }
  return labels[source || ''] || source || '未知'
}

/**
 * 获取来源颜色
 */
function getSourceColor(source?: string): string {
  const colors: Record<string, string> = {
    builtin: 'blue',
    tool: 'green',
    skill: 'orange',
    mcp: 'purple',
  }
  return colors[source || ''] || 'default'
}

/**
 * 获取分类标签
 */
function getCategoryLabel(category?: string): string {
  const labels: Record<string, string> = {
    input: '输入',
    output: '输出',
    llm: 'LLM',
    tool: '工具',
    skill: '技能',
    control: '控制',
    data: '数据',
    memory: '记忆',
    evolution: '进化',
    tdd: 'TDD',
    media: '媒体',
    integration: '集成',
    custom: '自定义',
  }
  return labels[category || ''] || category || '未知'
}

/**
 * 处理标签变化
 */
function handleLabelChange() {
  if (!props.selectedNode) return
  
  const updatedNode = {
    ...props.selectedNode,
    label: localLabel.value,
  }
  emit('update:node', updatedNode)
  emit('change', updatedNode)
}

/**
 * 处理备注变化
 */
function handleNotesChange() {
  if (!props.selectedNode) return
  
  const updatedNode = {
    ...props.selectedNode,
    notes: localNotes.value,
  }
  emit('update:node', updatedNode)
  emit('change', updatedNode)
}

/**
 * 处理子块变化
 */
function handleSubBlocksChange(values: Record<string, any>) {
  localSubBlocks.value = values
  updateNodeData()
}

/**
 * 处理单个子块变化
 */
function handleSubBlockChange(blockId: string, value: any) {
  localSubBlocks.value[blockId] = value
  updateNodeData()
}

/**
 * 处理输入变化
 */
function handleInputChange(portId: string, event: Event) {
  const target = event.target as HTMLInputElement
  localInputs.value[portId] = target.value
  updateNodeData()
}

/**
 * 更新节点数据
 */
function updateNodeData() {
  if (!props.selectedNode) return
  
  const updatedNode = {
    ...props.selectedNode,
    data: {
      ...props.selectedNode.data,
      subBlocks: { ...localSubBlocks.value },
      inputs: { ...localInputs.value },
    },
    subBlocks: { ...localSubBlocks.value },
    inputs: { ...localInputs.value },
  }
  emit('update:node', updatedNode)
  emit('change', updatedNode)
}

/**
 * 处理复制
 */
function handleCopy() {
  if (props.selectedNode) {
    emit('copy', props.selectedNode)
  }
}

/**
 * 处理删除
 */
function handleDelete() {
  if (props.selectedNode) {
    emit('delete', props.selectedNode.id)
  }
}

/**
 * 初始化本地状态
 */
function initializeLocalState() {
  if (!props.selectedNode) {
    localLabel.value = ''
    localNotes.value = ''
    localSubBlocks.value = {}
    localInputs.value = {}
    return
  }
  
  localLabel.value = props.selectedNode.label || ''
  localNotes.value = props.selectedNode.notes || ''
  localSubBlocks.value = { ...(props.selectedNode.subBlocks || props.selectedNode.data?.subBlocks || {}) }
  localInputs.value = { ...(props.selectedNode.inputs || props.selectedNode.data?.inputs || {}) }
}

// ==================== 监听器 ====================

watch(
  () => props.selectedNode,
  () => {
    initializeLocalState()
  },
  { immediate: true, deep: true }
)
</script>

<style scoped>
.node-inspector {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border-left: 1px solid #f0f0f0;
  overflow-y: auto;
}

.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}

.inspector-content {
  padding: 16px;
}

.inspector-header {
  display: flex;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid #f0f0f0;
  margin-bottom: 16px;
}

.node-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-size: 20px;
  color: #fff;
  margin-right: 12px;
}

.node-title {
  flex: 1;
}

.node-label {
  font-size: 16px;
  font-weight: 600;
  color: #262626;
}

.node-type {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 2px;
}

.node-actions {
  display: flex;
  gap: 4px;
}

.inspector-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #262626;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.ports-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.port-item {
  padding: 8px;
  background: #fafafa;
  border-radius: 6px;
}

.port-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.port-name {
  font-weight: 500;
  color: #262626;
}

.port-description {
  font-size: 12px;
  color: #8c8c8c;
  margin-bottom: 8px;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
