<template>
  <div class="tool-node" :class="{ 'node-running': isRunning }">
    <!-- 节点头部 -->
    <div class="node-header tool-header">
      <div class="node-icon">
        <ToolOutlined />
      </div>
      <div class="node-title">{{ toolName }}</div>
      <div class="node-source">
        <a-tag color="orange" size="small">工具</a-tag>
      </div>
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
      
      <!-- 工具描述 -->
      <div v-if="toolDescription" class="tool-description">
        {{ toolDescription }}
      </div>
      
      <!-- 参数预览 -->
      <div v-if="hasParams" class="tool-params">
        <div class="params-header">参数:</div>
        <div
          v-for="(value, key) in previewParams"
          :key="key"
          class="param-item"
        >
          <span class="param-key">{{ key }}:</span>
          <span class="param-value">{{ formatParamValue(value) }}</span>
        </div>
      </div>
    </div>
    
    <!-- 输入端口 -->
    <div class="node-inputs">
      <Handle
        type="target"
        :position="Position.Left"
        id="input"
        style="background: #fa8c16"
      />
    </div>
    
    <!-- 输出端口 -->
    <div class="node-outputs">
      <Handle
        type="source"
        :position="Position.Right"
        id="output"
        style="background: #fa8c16"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  ToolOutlined,
  SettingOutlined,
  DeleteOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons-vue'
import type { WorkflowNode } from '../types'

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

const toolName = computed(() => {
  const type = props.node.type
  if (type.startsWith('tool:')) {
    return type.replace('tool:', '')
  }
  return props.data?.toolName || props.node.label || '未知工具'
})

const toolDescription = computed(() => {
  return props.data?.description || props.data?.toolDescription || ''
})

const hasParams = computed(() => {
  return props.data?.params && Object.keys(props.data.params).length > 0
})

const previewParams = computed(() => {
  if (!props.data?.params) return {}
  
  // 只显示前3个参数
  const entries = Object.entries(props.data.params).slice(0, 3)
  return Object.fromEntries(entries)
})

function formatParamValue(value: any): string {
  if (typeof value === 'string') {
    return value.length > 30 ? value.substring(0, 30) + '...' : value
  }
  if (typeof value === 'object') {
    return JSON.stringify(value).substring(0, 30) + '...'
  }
  return String(value)
}
</script>

<style scoped>
.tool-node {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  min-width: 180px;
  max-width: 250px;
  font-size: 12px;
  border: 2px solid #fa8c16;
}

.node-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px 6px 0 0;
  color: white;
}

.tool-header {
  background: #fa8c16;
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

.node-source {
  margin-right: 8px;
}

.node-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.tool-node:hover .node-actions {
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
  background: #fff7e6;
  color: #fa8c16;
}

.node-status.completed {
  background: #f6ffed;
  color: #52c41a;
}

.node-status.failed {
  background: #fff2f0;
  color: #ff4d4f;
}

.tool-description {
  color: #666;
  font-size: 11px;
  line-height: 1.4;
  margin-bottom: 8px;
  word-break: break-word;
}

.tool-params {
  background: #fafafa;
  border-radius: 4px;
  padding: 8px;
}

.params-header {
  font-weight: 500;
  color: #333;
  margin-bottom: 4px;
}

.param-item {
  display: flex;
  gap: 4px;
  margin-bottom: 2px;
}

.param-key {
  color: #666;
  font-weight: 500;
}

.param-value {
  color: #333;
  font-family: monospace;
  font-size: 11px;
}

.node-inputs,
.node-outputs {
  position: relative;
}

/* 运行状态动画 */
.node-running {
  box-shadow: 0 0 0 2px #fa8c16;
  animation: pulse-orange 2s infinite;
}

@keyframes pulse-orange {
  0% {
    box-shadow: 0 0 0 2px rgba(250, 140, 22, 0.4);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(250, 140, 22, 0.2);
  }
  100% {
    box-shadow: 0 0 0 2px rgba(250, 140, 22, 0.4);
  }
}
</style>