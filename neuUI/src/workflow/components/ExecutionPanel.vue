<template>
  <div class="execution-panel">
    <!-- 面板头部 -->
    <div class="panel-header">
      <div class="header-title">
        <span class="title-icon">📋</span>
        <span>执行日志</span>
      </div>
      <div class="header-actions">
        <a-tooltip title="清空日志">
          <a-button type="text" size="small" @click="handleClear">
            <delete-outlined />
          </a-button>
        </a-tooltip>
        <a-tooltip title="自动滚动">
          <a-button
            type="text"
            size="small"
            :class="{ active: autoScroll }"
            @click="autoScroll = !autoScroll"
          >
            <vertical-align-bottom-outlined />
          </a-button>
        </a-tooltip>
        <a-tooltip title="导出日志">
          <a-button type="text" size="small" @click="handleExport">
            <export-outlined />
          </a-button>
        </a-tooltip>
      </div>
    </div>
    
    <!-- 执行状态 -->
    <div v-if="execution" class="execution-status">
      <div class="status-row">
        <span class="status-label">状态:</span>
        <a-tag :color="getStatusColor(execution.status)">
          {{ getStatusLabel(execution.status) }}
        </a-tag>
      </div>
      
      <div class="status-row">
        <span class="status-label">进度:</span>
        <a-progress
          :percent="progressPercent"
          :status="progressStatus"
          size="small"
          :show-info="true"
        />
      </div>
      
      <div class="status-row">
        <span class="status-label">耗时:</span>
        <span class="status-value">{{ formatDuration(execution.duration) }}</span>
      </div>
      
      <div class="status-row">
        <span class="status-label">节点:</span>
        <span class="status-value">
          {{ completedNodes }}/{{ totalNodes }} 完成
        </span>
      </div>
    </div>
    
    <!-- 事件过滤器 -->
    <div class="event-filters">
      <a-checkbox-group v-model:value="selectedEventTypes" :options="eventTypeOptions" />
    </div>
    
    <!-- 事件列表 -->
    <div ref="eventsContainer" class="events-container">
      <div
        v-for="event in filteredEvents"
        :key="event.timestamp"
        class="event-item"
        :class="[`event-${event.type}`, `level-${event.level || 'info'}`]"
      >
        <div class="event-header">
          <span class="event-time">{{ formatTime(event.timestamp) }}</span>
          <a-tag :color="getEventColor(event.type)" size="small">
            {{ getEventLabel(event.type) }}
          </a-tag>
          <span v-if="event.nodeId" class="event-node">{{ event.nodeId }}</span>
        </div>
        
        <div v-if="event.message" class="event-message">
          {{ event.message }}
        </div>
        
        <div v-if="event.data" class="event-data">
          <a-collapse size="small" :bordered="false">
            <a-collapse-panel key="data" header="数据">
              <pre class="data-preview">{{ formatData(event.data) }}</pre>
            </a-collapse-panel>
          </a-collapse>
        </div>
      </div>
      
      <!-- 空状态 -->
      <a-empty
        v-if="filteredEvents.length === 0"
        description="暂无执行日志"
        :image-style="{ height: '60px' }"
      />
    </div>
    
    <!-- 底部统计 -->
    <div class="panel-footer">
      <span class="event-count">{{ filteredEvents.length }} 条日志</span>
      <span v-if="execution" class="token-usage">
        Token: {{ execution.metadata?.tokenUsage?.total || 0 }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import {
  DeleteOutlined,
  VerticalAlignBottomOutlined,
  ExportOutlined,
} from '@ant-design/icons-vue'
import type { ExecutionInstance, ExecutionEvent, ExecutionEventType, ExecutionStatus } from '../types'

// ==================== Props ====================

interface Props {
  execution: ExecutionInstance | null
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
})

// ==================== Emits ====================

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'resume'): void
  (e: 'clear'): void
  (e: 'export', events: ExecutionEvent[]): void
}>()

// ==================== 状态 ====================

const eventsContainer = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const selectedEventTypes = ref<ExecutionEventType[]>([
  'started',
  'node_started',
  'node_completed',
  'node_failed',
  'completed',
  'failed',
  'cancelled',
  'error',
])

// ==================== 计算属性 ====================

/**
 * 事件类型选项
 */
const eventTypeOptions = [
  { label: '开始', value: 'started' },
  { label: '节点开始', value: 'node_started' },
  { label: '节点完成', value: 'node_completed' },
  { label: '节点失败', value: 'node_failed' },
  { label: '节点跳过', value: 'node_skipped' },
  { label: '暂停', value: 'paused' },
  { label: '恢复', value: 'resumed' },
  { label: '完成', value: 'completed' },
  { label: '失败', value: 'failed' },
  { label: '取消', value: 'cancelled' },
  { label: '日志', value: 'log' },
  { label: '警告', value: 'warning' },
  { label: '错误', value: 'error' },
]

/**
 * 过滤后的事件
 */
const filteredEvents = computed(() => {
  if (!props.execution) return []
  
  return props.execution.events.filter(event =>
    selectedEventTypes.value.includes(event.type)
  )
})

/**
 * 总节点数
 */
const totalNodes = computed(() => {
  if (!props.execution) return 0
  return Object.keys(props.execution.nodeStates).length
})

/**
 * 已完成节点数
 */
const completedNodes = computed(() => {
  if (!props.execution) return 0
  return Object.values(props.execution.nodeStates).filter(
    state => state.status === 'completed'
  ).length
})

/**
 * 进度百分比
 */
const progressPercent = computed(() => {
  if (totalNodes.value === 0) return 0
  return Math.round((completedNodes.value / totalNodes.value) * 100)
})

/**
 * 进度状态
 */
const progressStatus = computed(() => {
  if (!props.execution) return 'normal'
  
  switch (props.execution.status) {
    case 'completed':
      return 'success'
    case 'failed':
      return 'exception'
    case 'cancelled':
      return 'exception'
    default:
      return 'active'
  }
})

// ==================== 方法 ====================

/**
 * 获取状态颜色
 */
function getStatusColor(status: ExecutionStatus): string {
  const colors: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    paused: 'warning',
    completed: 'success',
    failed: 'error',
    cancelled: 'default',
  }
  return colors[status] || 'default'
}

/**
 * 获取状态标签
 */
function getStatusLabel(status: ExecutionStatus): string {
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return labels[status] || status
}

/**
 * 获取事件颜色
 */
function getEventColor(type: ExecutionEventType): string {
  const colors: Record<string, string> = {
    started: 'blue',
    node_started: 'cyan',
    node_completed: 'green',
    node_failed: 'red',
    node_skipped: 'orange',
    paused: 'yellow',
    resumed: 'blue',
    completed: 'green',
    failed: 'red',
    cancelled: 'default',
    log: 'default',
    warning: 'orange',
    error: 'red',
  }
  return colors[type] || 'default'
}

/**
 * 获取事件标签
 */
function getEventLabel(type: ExecutionEventType): string {
  const labels: Record<string, string> = {
    started: '开始',
    node_started: '节点开始',
    node_completed: '节点完成',
    node_failed: '节点失败',
    node_skipped: '节点跳过',
    paused: '暂停',
    resumed: '恢复',
    completed: '完成',
    failed: '失败',
    cancelled: '取消',
    log: '日志',
    warning: '警告',
    error: '错误',
  }
  return labels[type] || type
}

/**
 * 格式化时间
 */
function formatTime(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/**
 * 格式化持续时间
 */
function formatDuration(duration?: number): string {
  if (!duration) return '0秒'
  
  const seconds = Math.floor(duration / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  
  if (hours > 0) {
    return `${hours}小时${minutes % 60}分${seconds % 60}秒`
  } else if (minutes > 0) {
    return `${minutes}分${seconds % 60}秒`
  } else {
    return `${seconds}秒`
  }
}

/**
 * 格式化数据
 */
function formatData(data: any): string {
  try {
    if (typeof data === 'string') {
      return data
    }
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

/**
 * 处理清空
 */
function handleClear() {
  emit('clear')
}

/**
 * 处理导出
 */
function handleExport() {
  emit('export', filteredEvents.value)
}

/**
 * 滚动到底部
 */
function scrollToBottom() {
  if (autoScroll.value && eventsContainer.value) {
    nextTick(() => {
      eventsContainer.value!.scrollTop = eventsContainer.value!.scrollHeight
    })
  }
}

// ==================== 监听器 ====================

watch(
  () => props.execution?.events,
  () => {
    scrollToBottom()
  },
  { deep: true }
)

// ==================== 生命周期 ====================

onMounted(() => {
  scrollToBottom()
})
</script>

<style scoped>
.execution-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border-top: 1px solid #f0f0f0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #262626;
}

.title-icon {
  font-size: 16px;
}

.header-actions {
  display: flex;
  gap: 4px;
}

.header-actions .active {
  color: #1890ff;
  background: #e6f7ff;
}

.execution-status {
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
}

.status-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}

.status-row:last-child {
  margin-bottom: 0;
}

.status-label {
  width: 60px;
  color: #8c8c8c;
  font-size: 12px;
}

.status-value {
  color: #262626;
  font-size: 12px;
}

.event-filters {
  padding: 8px 16px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafafa;
}

.events-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.event-item {
  padding: 8px 12px;
  margin-bottom: 8px;
  border-radius: 6px;
  border-left: 3px solid #d9d9d9;
  background: #fafafa;
}

.event-item.event-started {
  border-left-color: #1890ff;
}

.event-item.event-node_started {
  border-left-color: #13c2c2;
}

.event-item.event-node_completed {
  border-left-color: #52c41a;
}

.event-item.event-node_failed {
  border-left-color: #ff4d4f;
}

.event-item.event-completed {
  border-left-color: #52c41a;
  background: #f6ffed;
}

.event-item.event-failed {
  border-left-color: #ff4d4f;
  background: #fff2f0;
}

.event-item.event-error {
  border-left-color: #ff4d4f;
  background: #fff2f0;
}

.event-item.event-warning {
  border-left-color: #faad14;
  background: #fffbe6;
}

.event-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.event-time {
  font-size: 12px;
  color: #8c8c8c;
  font-family: monospace;
}

.event-node {
  font-size: 12px;
  color: #1890ff;
  font-weight: 500;
}

.event-message {
  font-size: 13px;
  color: #262626;
  margin-top: 4px;
}

.event-data {
  margin-top: 8px;
}

.data-preview {
  margin: 0;
  padding: 8px;
  background: #f5f5f5;
  border-radius: 4px;
  font-size: 12px;
  font-family: monospace;
  overflow-x: auto;
  max-height: 200px;
  overflow-y: auto;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-top: 1px solid #f0f0f0;
  background: #fafafa;
}

.event-count {
  font-size: 12px;
  color: #8c8c8c;
}

.token-usage {
  font-size: 12px;
  color: #8c8c8c;
}
</style>
