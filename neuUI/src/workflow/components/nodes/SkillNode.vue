<template>
  <div class="skill-node" :class="{ 'node-running': isRunning }">
    <!-- 节点头部 -->
    <div class="node-header skill-header">
      <div class="node-icon">
        <ThunderboltOutlined />
      </div>
      <div class="node-title">{{ skillName }}</div>
      <div class="node-source">
        <a-tag color="purple" size="small">技能</a-tag>
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
      
      <!-- 技能描述 -->
      <div v-if="skillDescription" class="skill-description">
        {{ skillDescription }}
      </div>
      
      <!-- 技能信息 -->
      <div class="skill-info">
        <div v-if="skillVersion" class="skill-version">
          <span class="info-label">版本:</span>
          <span class="info-value">{{ skillVersion }}</span>
        </div>
        <div v-if="skillAuthor" class="skill-author">
          <span class="info-label">作者:</span>
          <span class="info-value">{{ skillAuthor }}</span>
        </div>
      </div>
      
      <!-- 输入参数预览 -->
      <div v-if="hasInputs" class="skill-inputs">
        <div class="inputs-header">输入:</div>
        <div
          v-for="input in previewInputs"
          :key="input.name"
          class="input-item"
        >
          <span class="input-name">{{ input.name }}</span>
          <span class="input-type">{{ input.type }}</span>
          <span v-if="input.required" class="input-required">*</span>
        </div>
      </div>
    </div>
    
    <!-- 输入端口 -->
    <div class="node-inputs">
      <Handle
        type="target"
        :position="Position.Left"
        id="input"
        style="background: #722ed1"
      />
    </div>
    
    <!-- 输出端口 -->
    <div class="node-outputs">
      <Handle
        type="source"
        :position="Position.Right"
        id="output"
        style="background: #722ed1"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  ThunderboltOutlined,
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

const skillName = computed(() => {
  const type = props.node.type
  if (type.startsWith('skill:')) {
    return type.replace('skill:', '')
  }
  return props.data?.skillName || props.node.label || '未知技能'
})

const skillDescription = computed(() => {
  return props.data?.description || props.data?.skillDescription || ''
})

const skillVersion = computed(() => {
  return props.data?.version || props.data?.skillVersion
})

const skillAuthor = computed(() => {
  return props.data?.author || props.data?.skillAuthor
})

const hasInputs = computed(() => {
  return props.data?.inputs && props.data.inputs.length > 0
})

const previewInputs = computed(() => {
  if (!props.data?.inputs) return []
  return props.data.inputs.slice(0, 3)
})
</script>

<style scoped>
.skill-node {
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  min-width: 180px;
  max-width: 250px;
  font-size: 12px;
  border: 2px solid #722ed1;
}

.node-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 6px 6px 0 0;
  color: white;
}

.skill-header {
  background: #722ed1;
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

.skill-node:hover .node-actions {
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
  background: #f9f0ff;
  color: #722ed1;
}

.node-status.completed {
  background: #f6ffed;
  color: #52c41a;
}

.node-status.failed {
  background: #fff2f0;
  color: #ff4d4f;
}

.skill-description {
  color: #666;
  font-size: 11px;
  line-height: 1.4;
  margin-bottom: 8px;
  word-break: break-word;
}

.skill-info {
  background: #fafafa;
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
}

.skill-version,
.skill-author {
  display: flex;
  gap: 4px;
  margin-bottom: 4px;
}

.skill-version:last-child,
.skill-author:last-child {
  margin-bottom: 0;
}

.info-label {
  color: #666;
  font-weight: 500;
}

.info-value {
  color: #333;
}

.skill-inputs {
  background: #f9f0ff;
  border-radius: 4px;
  padding: 8px;
}

.inputs-header {
  font-weight: 500;
  color: #722ed1;
  margin-bottom: 4px;
}

.input-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.input-name {
  font-weight: 500;
  color: #333;
}

.input-type {
  color: #666;
  font-size: 10px;
  background: rgba(114, 46, 209, 0.1);
  padding: 1px 6px;
  border-radius: 4px;
}

.input-required {
  color: #ff4d4f;
  font-weight: bold;
}

.node-inputs,
.node-outputs {
  position: relative;
}

/* 运行状态动画 */
.node-running {
  box-shadow: 0 0 0 2px #722ed1;
  animation: pulse-purple 2s infinite;
}

@keyframes pulse-purple {
  0% {
    box-shadow: 0 0 0 2px rgba(114, 46, 209, 0.4);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(114, 46, 209, 0.2);
  }
  100% {
    box-shadow: 0 0 0 2px rgba(114, 46, 209, 0.4);
  }
}
</style>