<template>
  <div class="builtin-node" :class="[`node-${nodeType}`, { 'node-running': isRunning }]">
    <!-- 节点头部 -->
    <div class="node-header" :style="{ backgroundColor: nodeColor }">
      <div class="node-icon">
        <component :is="nodeIcon" />
      </div>
      <div class="node-title">{{ node.label }}</div>
      <div class="node-actions">
        <a-button type="text" size="small" @click="$emit('config')">
          <template #icon><SettingOutlined /></template>
        </a-button>
        <a-button type="text" size="small" danger @click="$emit('delete')">
          <template #icon><DeleteOutlined /></template>
        </a-button>
      </div>
    </div>
    
    <!-- 节点内容 -->
    <div class="node-content">
      <!-- 状态指示器 -->
      <div v-if="isRunning" class="node-status running">
        <LoadingOutlined spin />
        <span>执行中...</span>
      </div>
      
      <div v-else-if="isCompleted" class="node-status completed">
        <CheckCircleOutlined />
        <span>已完成</span>
      </div>
      
      <div v-else-if="isFailed" class="node-status failed">
        <CloseCircleOutlined />
        <span>失败</span>
      </div>
      
      <!-- 预览文本 -->
      <div v-if="previewText" class="node-preview">
        {{ previewText }}
      </div>
      
      <!-- LLM 节点特殊显示 -->
      <div v-if="nodeType === 'llm'" class="node-llm-info">
        <div class="model-name">{{ nodeData.model || '默认模型' }}</div>
        <div v-if="nodeData.temperature" class="temperature">
          温度: {{ nodeData.temperature }}
        </div>
      </div>
      
      <!-- 条件节点特殊显示 -->
      <div v-if="nodeType === 'condition'" class="node-condition">
        <div class="condition-expression">
          {{ nodeData.expression || '未设置条件' }}
        </div>
      </div>
    </div>
    
    <!-- 输入端口 -->
    <div class="node-inputs">
      <Handle
        v-for="port in node.inputs"
        :key="port.id"
        type="target"
        :position="Position.Left"
        :id="port.id"
        :style="getPortStyle(port)"
      />
    </div>
    
    <!-- 输出端口 -->
    <div class="node-outputs">
      <Handle
        v-for="port in node.outputs"
        :key="port.id"
        type="source"
        :position="Position.Right"
        :id="port.id"
        :style="getPortStyle(port)"
      />
      
      <!-- 条件节点的分支标签 -->
      <div v-if="nodeType === 'condition'" class="condition-branches">
        <div
          v-for="(branch, index) in conditionBranches"
          :key="index"
          class="branch-label"
          :style="{ top: `${30 + index * 30}px` }"
        >
          {{ branch }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  SettingOutlined,
  DeleteOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  MessageOutlined,
  BranchesOutlined,
  ReloadOutlined,
  CodeOutlined,
  GlobalOutlined,
  ClockOutlined,
  UserOutlined,
  DatabaseOutlined,
  SwapOutlined,
} from '@ant-design/icons-vue'
import type { WorkflowNode, NodePort } from '../types'

interface Props {
  node: WorkflowNode
  data: any
  isRunning?: boolean
  isCompleted?: boolean
  isFailed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isRunning: false,
  isCompleted: false,
  isFailed: false,
})

defineEmits<{
  'config': []
  'delete': []
}>()

const nodeType = computed(() => {
  const type = props.node.type
  if (type.startsWith('builtin:')) {
    return type.replace('builtin:', '')
  }
  return type
})

const nodeData = computed(() => props.node.data || {})

const nodeColor = computed(() => {
  const colors: Record<string, string> = {
    'input': '#52c41a',
    'output': '#faad14',
    'llm': '#1890ff',
    'condition': '#722ed1',
    'loop': '#eb2f96',
    'memory_search': '#13c2c2',
    'memory_save': '#13c2c2',
    'code': '#2f54eb',
    'http': '#fa8c16',
    'wait': '#8c8c8c',
    'human_approval': '#f5222d',
    'set_variable': '#597ef7',
    'transform': '#9254de',
    'emotion': '#ff4d4f',
    'evolution': '#52c41a',
  }
  return colors[nodeType.value] || '#1890ff'
})

const nodeIcon = computed(() => {
  const icons: Record<string, any> = {
    'input': MessageOutlined,
    'output': MessageOutlined,
    'llm': MessageOutlined,
    'condition': BranchesOutlined,
    'loop': ReloadOutlined,
    'memory_search': DatabaseOutlined,
    'memory_save': DatabaseOutlined,
    'code': CodeOutlined,
    'http': GlobalOutlined,
    'wait': ClockOutlined,
    'human_approval': UserOutlined,
    'set_variable': SwapOutlined,
    'transform': SwapOutlined,
  }
  return icons[nodeType.value] || MessageOutlined
})

const previewText = computed(() => {
  const data = nodeData.value
  
  switch (nodeType.value) {
    case 'input':
      return data.description || '用户输入'
    case 'output':
      return data.description || '输出结果'
    case 'llm':
      return data.prompt?.substring(0, 50) || 'LLM 调用'
    case 'condition':
      return data.expression?.substring(0, 50) || '条件判断'
    case 'code':
      return `代码 (${data.language || 'python'})`
    case 'http':
      return `${data.method || 'GET'} ${data.url?.substring(0, 30) || ''}`
    case 'wait':
      return `等待 ${data.duration || 0}ms`
    case 'memory_search':
      return `搜索: ${data.query?.substring(0, 30) || ''}`
    default:
      return data.description || data.label || ''
  }
})

const conditionBranches = computed(() => {
  if (nodeType.value !== 'condition') return []
  return ['True', 'False']
})

function getPortStyle(port: NodePort) {
  return {
    backgroundColor: port.type === 'string' ? '#1890ff' : 
                     port.type === 'number' ? '#52c41a' :
                     port.type === 'boolean' ? '#faad14' : '#722ed1',
    width: '10px',
    height: '10px',
  }
}
</script>

<style scoped>
.builtin-node {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  min-width: 180px;
  max-width: 250px;
  font-size: 12px;
}

.node-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 8px 8px 0 0;
  color: white;
}

.node-icon {
  margin-right: 8px;
  font-size: 14px;
}

.node-title {
  flex: 1;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.builtin-node:hover .node-actions {
  opacity: 1;
}

.node-actions .ant-btn {
  color: white;
  width: 24px;
  height: 24px;
}

.node-content {
  padding: 8px 12px;
}

.node-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
  font-size: 12px;
}

.node-status.running {
  background: #e6f7ff;
  color: #1890ff;
}

.node-status.completed {
  background: #f6ffed;
  color: #52c41a;
}

.node-status.failed {
  background: #fff2f0;
  color: #ff4d4f;
}

.node-preview {
  color: #666;
  font-size: 11px;
  line-height: 1.4;
  word-break: break-word;
}

.node-llm-info {
  margin-top: 8px;
  padding: 8px;
  background: #f5f5f5;
  border-radius: 4px;
}

.model-name {
  font-weight: 500;
  color: #1890ff;
}

.temperature {
  font-size: 11px;
  color: #666;
  margin-top: 4px;
}

.node-condition {
  margin-top: 8px;
  padding: 8px;
  background: #f9f0ff;
  border-radius: 4px;
}

.condition-expression {
  font-family: monospace;
  font-size: 11px;
  color: #722ed1;
  word-break: break-word;
}

.node-inputs,
.node-outputs {
  position: relative;
}

.condition-branches {
  position: absolute;
  right: -40px;
  top: 0;
}

.branch-label {
  position: absolute;
  font-size: 10px;
  color: #666;
  white-space: nowrap;
}

/* 运行状态动画 */
.node-running {
  box-shadow: 0 0 0 2px #1890ff;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.4);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(24, 144, 255, 0.2);
  }
  100% {
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.4);
  }
}
</style>