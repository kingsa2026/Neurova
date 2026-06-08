<template>
  <g
    :class="[
      'workflow-edge',
      `edge-type-${type}`,
      {
        'edge-selected': selected,
        'edge-animated': animated,
        'edge-error': hasError,
      }
    ]"
    @click.stop="handleClick"
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
  >
    <!-- 边路径 -->
    <path
      :id="`${id}-path`"
      :d="edgePath"
      :stroke="strokeColor"
      :stroke-width="strokeWidth"
      :stroke-dasharray="strokeDasharray"
      fill="none"
      :marker-end="markerEnd"
      class="edge-path"
    />

    <!-- 边标签 -->
    <EdgeLabelRenderer v-if="label">
      <div
        :style="{
          position: 'absolute',
          transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          pointerEvents: 'all',
        }"
        class="edge-label-container"
        @click.stop="handleLabelClick"
      >
        <div class="edge-label" :style="labelStyle">
          {{ label }}
        </div>
      </div>
    </EdgeLabelRenderer>

    <!-- 边操作按钮 -->
    <EdgeLabelRenderer v-if="selected || isHovered">
      <div
        :style="{
          position: 'absolute',
          transform: `translate(-50%, -50%) translate(${buttonX}px, ${buttonY}px)`,
          pointerEvents: 'all',
        }"
        class="edge-button-container"
      >
        <a-button
          type="text"
          size="small"
          danger
          class="edge-delete-button"
          @click.stop="handleDelete"
        >
          <template #icon>
            <DeleteOutlined />
          </template>
        </a-button>
      </div>
    </EdgeLabelRenderer>

    <!-- 条件分支标签 -->
    <EdgeLabelRenderer v-if="sourceHandle && sourceHandle !== 'default'">
      <div
        :style="{
          position: 'absolute',
          transform: `translate(-50%, -50%) translate(${handleLabelX}px, ${handleLabelY}px)`,
          pointerEvents: 'none',
        }"
        class="handle-label"
      >
        {{ getHandleLabel(sourceHandle) }}
      </div>
    </EdgeLabelRenderer>
  </g>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { getBezierPath, EdgeLabelRenderer } from '@vue-flow/core'
import { DeleteOutlined } from '@ant-design/icons-vue'

// ==================== Props ====================

interface Props {
  id: string
  source: string
  target: string
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
  sourcePosition?: any
  targetPosition?: any
  data?: Record<string, any>
  style?: Record<string, any>
  selected?: boolean
  animated?: boolean
  label?: string
  sourceHandle?: string
  targetHandle?: string
  markerEnd?: string
  interactionWidth?: number
}

const props = withDefaults(defineProps<Props>(), {
  selected: false,
  animated: false,
  interactionWidth: 20,
})

// ==================== Emits ====================

const emit = defineEmits<{
  (e: 'click', edge: any): void
  (e: 'delete', edgeId: string): void
  (e: 'label-click', edge: any): void
}>()

// ==================== 状态 ====================

const isHovered = ref(false)
const hasError = ref(false)

// ==================== 计算属性 ====================

/**
 * 边类型
 */
const type = computed(() => {
  return props.data?.type || 'default'
})

/**
 * 边路径
 */
const edgePath = computed(() => {
  const [path] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    sourcePosition: props.sourcePosition,
    targetPosition: props.targetPosition,
  })
  return path
})

/**
 * 标签位置
 */
const labelX = computed(() => {
  return (props.sourceX + props.targetX) / 2
})

const labelY = computed(() => {
  return (props.sourceY + props.targetY) / 2
})

/**
 * 按钮位置（在边的 1/4 处）
 */
const buttonX = computed(() => {
  return props.sourceX + (props.targetX - props.sourceX) * 0.25
})

const buttonY = computed(() => {
  return props.sourceY + (props.targetY - props.sourceY) * 0.25
})

/**
 * 句柄标签位置（在边的 1/3 处）
 */
const handleLabelX = computed(() => {
  return props.sourceX + (props.targetX - props.sourceX) * 0.33
})

const handleLabelY = computed(() => {
  return props.sourceY + (props.targetY - props.sourceY) * 0.33
})

/**
 * 描边颜色
 */
const strokeColor = computed(() => {
  if (hasError.value) return '#ff4d4f'
  if (props.selected) return '#1890ff'
  if (isHovered.value) return '#40a9ff'
  
  // 根据类型设置颜色
  switch (type.value) {
    case 'smoothstep': return '#1890ff'
    case 'step': return '#52c41a'
    case 'bezier': return '#722ed1'
    default: return '#b1b1b7'
  }
})

/**
 * 描边宽度
 */
const strokeWidth = computed(() => {
  if (props.selected) return 3
  if (isHovered.value) return 2.5
  return 2
})

/**
 * 虚线样式
 */
const strokeDasharray = computed(() => {
  if (props.animated) return '5 5'
  if (type.value === 'dashed') return '8 4'
  return undefined
})

/**
 * 标签样式
 */
const labelStyle = computed(() => {
  return {
    backgroundColor: props.selected ? '#1890ff' : '#fff',
    color: props.selected ? '#fff' : '#333',
    borderColor: props.selected ? '#1890ff' : '#d9d9d9',
  }
})

// ==================== 方法 ====================

/**
 * 获取句柄标签
 */
function getHandleLabel(handle: string): string {
  const labels: Record<string, string> = {
    'true': '真',
    'false': '假',
    'loop_body': '循环体',
    'loop_done': '完成',
    'approved': '批准',
    'rejected': '拒绝',
    'default': '默认',
  }
  return labels[handle] || handle
}

/**
 * 处理点击
 */
function handleClick() {
  emit('click', {
    id: props.id,
    source: props.source,
    target: props.target,
    sourceHandle: props.sourceHandle,
    targetHandle: props.targetHandle,
    data: props.data,
  })
}

/**
 * 处理鼠标进入
 */
function handleMouseEnter() {
  isHovered.value = true
}

/**
 * 处理鼠标离开
 */
function handleMouseLeave() {
  isHovered.value = false
}

/**
 * 处理标签点击
 */
function handleLabelClick() {
  emit('label-click', {
    id: props.id,
    source: props.source,
    target: props.target,
    label: props.label,
  })
}

/**
 * 处理删除
 */
function handleDelete() {
  emit('delete', props.id)
}
</script>

<style scoped>
.workflow-edge {
  pointer-events: all;
}

.edge-path {
  transition: stroke 0.2s ease, stroke-width 0.2s ease;
}

.edge-path:hover {
  stroke-width: 3;
}

.workflow-edge.edge-animated .edge-path {
  animation: dash-animation 0.5s linear infinite;
}

@keyframes dash-animation {
  to {
    stroke-dashoffset: -10;
  }
}

.edge-label-container {
  pointer-events: all;
}

.edge-label {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
  border: 1px solid #d9d9d9;
  background: #fff;
  color: #333;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
}

.edge-label:hover {
  transform: scale(1.05);
}

.edge-button-container {
  pointer-events: all;
}

.edge-delete-button {
  background: #fff;
  border: 1px solid #ff4d4f;
  color: #ff4d4f;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
}

.edge-delete-button:hover {
  background: #ff4d4f;
  color: #fff;
}

.handle-label {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  white-space: nowrap;
}

/* 边类型特殊样式 */
.workflow-edge.edge-type-smoothstep .edge-path {
  stroke-linecap: round;
}

.workflow-edge.edge-type-step .edge-path {
  stroke-linejoin: round;
}

.workflow-edge.edge-type-bezier .edge-path {
  stroke-linecap: round;
}

/* 边状态特殊样式 */
.workflow-edge.edge-error .edge-path {
  stroke: #ff4d4f;
  stroke-dasharray: 4 2;
}

.workflow-edge.edge-selected .edge-path {
  filter: drop-shadow(0 0 4px rgba(24, 144, 255, 0.5));
}

/* 响应式调整 */
@media (max-width: 768px) {
  .edge-label {
    font-size: 10px;
    padding: 2px 6px;
  }
  
  .handle-label {
    font-size: 9px;
  }
}
</style>