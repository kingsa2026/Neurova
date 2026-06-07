<template>
  <div class="session-sync-panel">
    <div class="panel-header">
      <div class="header-title">
        <SyncOutlined style="font-size:18px;color:#1890ff" />
        <span>跨渠道会话同步</span>
      </div>
      
      <div class="header-actions">
        <a-tag :color="isConnected ? 'success' : 'error'" size="small">
          {{ isConnected ? '已连接' : '未连接' }}
        </a-tag>
        
        <a-button 
          v-if="!isConnected" 
          type="primary" 
          size="small" 
          @click="handleConnect"
          :loading="connecting"
        >
          <LinkOutlined /> 连接
        </a-button>
        
        <a-button 
          v-else 
          danger 
          size="small" 
          @click="handleDisconnect"
        >
          <DisconnectOutlined /> 断开
        </a-button>
        
        <a-button size="small" @click="handleRefresh">
          <ReloadOutlined />
        </a-button>
      </div>
    </div>

    <!-- 会话信息 -->
    <div v-if="session" class="session-info">
      <a-descriptions size="small" :column="2">
        <a-descriptions-item label="会话ID">
          <a-typography-text copyable :content="session.session_id" style="font-size:12px" />
        </a-descriptions-item>
        <a-descriptions-item label="状态">
          <a-tag :color="session.status === 'active' ? 'green' : 'default'">
            {{ session.status }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="活跃渠道">
          <a-tag v-for="ch in session.active_channels" :key="ch" color="blue" size="small">
            {{ ch }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="最后活动">
          {{ formatTime(session.last_activity) }}
        </a-descriptions-item>
      </a-descriptions>
    </div>

    <!-- 消息流 -->
    <div class="message-stream" ref="messageContainer">
      <div 
        v-for="event in events" 
        :key="event.event_id"
        :class="['message-item', `type-${event.event_type}`]"
      >
        <div class="message-header">
          <a-tag :color="getEventColor(event.event_type)" size="small">
            {{ getEventLabel(event.event_type) }}
          </a-tag>
          <span class="message-channel">{{ event.source_channel }}</span>
          <span class="message-time">{{ formatTime(event.timestamp) }}</span>
        </div>
        
        <div class="message-content">
          <!-- 用户消息 -->
          <template v-if="event.event_type === 'USER_MESSAGE'">
            <div class="user-message">
              <UserOutlined style="color:#1890ff" />
              <span>{{ event.payload?.content || '' }}</span>
            </div>
          </template>
          
          <!-- Agent 回复 -->
          <template v-else-if="event.event_type === 'AGENT_REPLY'">
            <div class="agent-message">
              <RobotOutlined style="color:#52c41a" />
              <div class="agent-content">
                <div v-if="event.payload?.reasoning" class="reasoning">
                  <div class="reasoning-header">
                    <BulbOutlined /> 思考过程
                  </div>
                  <div class="reasoning-text">{{ event.payload.reasoning }}</div>
                </div>
                <div class="reply-text">{{ event.payload?.content || '' }}</div>
              </div>
            </div>
          </template>
          
          <!-- 工具调用 -->
          <template v-else-if="event.event_type === 'AGENT_TOOL_CALL'">
            <div class="tool-message">
              <ToolOutlined style="color:#faad14" />
              <span>调用工具: {{ event.payload?.tool_name || '未知' }}</span>
            </div>
          </template>
          
          <!-- 工具结果 -->
          <template v-else-if="event.event_type === 'AGENT_TOOL_RESULT'">
            <div class="tool-result">
              <CheckCircleOutlined style="color:#52c41a" />
              <span>工具执行完成</span>
            </div>
          </template>
          
          <!-- Agent 思考 -->
          <template v-else-if="event.event_type === 'AGENT_THINKING'">
            <div class="thinking-message">
              <LoadingOutlined style="color:#1890ff" />
              <span>Agent 正在思考...</span>
            </div>
          </template>
          
          <!-- 其他事件 -->
          <template v-else>
            <div class="other-message">
              <InfoCircleOutlined style="color:#999" />
              <span>{{ event.event_type }}</span>
            </div>
          </template>
        </div>
      </div>
      
      <div v-if="events.length === 0" class="empty-state">
        <InboxOutlined style="font-size:48px;color:rgba(255,255,255,0.15)" />
        <p>暂无同步消息</p>
        <p class="hint">连接后，跨渠道的消息将实时显示在这里</p>
      </div>
    </div>

    <!-- 统计信息 -->
    <div class="statistics">
      <a-row :gutter="16">
        <a-col :span="8">
          <a-statistic title="消息总数" :value="statistics.total_events || 0" />
        </a-col>
        <a-col :span="8">
          <a-statistic title="活跃会话" :value="statistics.active_sessions || 0" />
        </a-col>
        <a-col :span="8">
          <a-statistic title="连接数" :value="statistics.active_connections || 0" />
        </a-col>
      </a-row>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  SyncOutlined,
  LinkOutlined,
  DisconnectOutlined,
  ReloadOutlined,
  UserOutlined,
  RobotOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  BulbOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
  InboxOutlined,
} from '@ant-design/icons-vue'
import { 
  sessionSyncAPI, 
  SessionWebSocket,
  type SessionInfo,
  type SessionEvent,
  type EventType,
} from '@/api/modules/session-sync'

const props = defineProps<{
  userId?: string
  agentId?: string
  sessionId?: string
}>()

const emit = defineEmits<{
  (e: 'session-created', session: SessionInfo): void
  (e: 'event-received', event: SessionEvent): void
}>()

// 状态
const isConnected = ref(false)
const connecting = ref(false)
const session = ref<SessionInfo | null>(null)
const events = ref<SessionEvent[]>([])
const statistics = ref({
  total_events: 0,
  active_sessions: 0,
  active_connections: 0,
})

const messageContainer = ref<HTMLElement | null>(null)

// WebSocket 实例
let ws: SessionWebSocket | null = null

// 计算属性
const currentSessionId = computed(() => {
  return props.sessionId || session.value?.session_id || ''
})

// 方法
async function handleConnect() {
  if (!props.userId) {
    message.warning('请先登录')
    return
  }

  connecting.value = true
  
  try {
    // 创建或获取会话
    if (!currentSessionId.value) {
      const newSession = await sessionSyncAPI.createSession({
        user_id: props.userId,
        agent_id: props.agentId || 'default',
      })
      session.value = newSession
      emit('session-created', newSession)
    } else {
      const existingSession = await sessionSyncAPI.getSession(currentSessionId.value)
      session.value = existingSession
    }

    // 建立 WebSocket 连接
    ws = new SessionWebSocket({
      sessionId: currentSessionId.value,
      channelType: 'web',
      onEvent: handleEvent,
      onConnect: () => {
        isConnected.value = true
        message.success('已连接到同步服务')
      },
      onDisconnect: () => {
        isConnected.value = false
      },
      onError: (error) => {
        message.error('连接错误: ' + error)
      },
    })

    await ws.connect()
    
    // 加载历史
    await loadHistory()
    
    // 加载统计
    await loadStatistics()
    
  } catch (error: any) {
    message.error('连接失败: ' + (error.message || error))
  } finally {
    connecting.value = false
  }
}

function handleDisconnect() {
  if (ws) {
    ws.disconnect()
    ws = null
  }
  isConnected.value = false
  message.info('已断开连接')
}

async function handleRefresh() {
  if (isConnected.value && currentSessionId.value) {
    await loadHistory()
    await loadStatistics()
  }
}

function handleEvent(event: SessionEvent) {
  events.value.push(event)
  emit('event-received', event)
  
  // 自动滚动到底部
  nextTick(() => {
    if (messageContainer.value) {
      messageContainer.value.scrollTop = messageContainer.value.scrollHeight
    }
  })
}

async function loadHistory() {
  if (!currentSessionId.value) return
  
  try {
    const history = await sessionSyncAPI.getHistory(currentSessionId.value, 100)
    events.value = history.events || []
    
    // 滚动到底部
    nextTick(() => {
      if (messageContainer.value) {
        messageContainer.value.scrollTop = messageContainer.value.scrollHeight
      }
    })
  } catch (error) {
    console.error('Failed to load history:', error)
  }
}

async function loadStatistics() {
  try {
    const stats = await sessionSyncAPI.getStatistics()
    statistics.value = {
      total_events: stats.total_events || 0,
      active_sessions: stats.active_sessions || 0,
      active_connections: stats.active_connections || 0,
    }
  } catch (error) {
    console.error('Failed to load statistics:', error)
  }
}

// 辅助函数
function getEventColor(type: EventType): string {
  const colorMap: Record<string, string> = {
    USER_MESSAGE: 'blue',
    AGENT_REPLY: 'green',
    AGENT_THINKING: 'cyan',
    AGENT_TOOL_CALL: 'orange',
    AGENT_TOOL_RESULT: 'lime',
    AGENT_COMMAND: 'purple',
    AGENT_ERROR: 'red',
    AGENT_STREAM_CHUNK: 'geekblue',
    SESSION_CREATED: 'gold',
    SESSION_RESUMED: 'green',
    SESSION_PAUSED: 'default',
    SESSION_ENDED: 'red',
    CHANNEL_CONNECTED: 'success',
    CHANNEL_DISCONNECTED: 'error',
  }
  return colorMap[type] || 'default'
}

function getEventLabel(type: EventType): string {
  const labelMap: Record<string, string> = {
    USER_MESSAGE: '用户消息',
    AGENT_REPLY: 'Agent 回复',
    AGENT_THINKING: 'Agent 思考',
    AGENT_TOOL_CALL: '工具调用',
    AGENT_TOOL_RESULT: '工具结果',
    AGENT_COMMAND: '命令执行',
    AGENT_ERROR: '错误',
    AGENT_STREAM_CHUNK: '流式输出',
    SESSION_CREATED: '会话创建',
    SESSION_RESUMED: '会话恢复',
    SESSION_PAUSED: '会话暂停',
    SESSION_ENDED: '会话结束',
    CHANNEL_CONNECTED: '渠道连接',
    CHANNEL_DISCONNECTED: '渠道断开',
  }
  return labelMap[type] || type
}

function formatTime(isoString: string): string {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleTimeString('zh-CN', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit'
  })
}

// 生命周期
onMounted(() => {
  if (props.sessionId) {
    handleConnect()
  }
  
  // 定期刷新统计
  const statsInterval = setInterval(loadStatistics, 30000)
  
  onUnmounted(() => {
    clearInterval(statsInterval)
    handleDisconnect()
  })
})
</script>

<style scoped>
.session-sync-panel {
  background: #1a1a2e;
  border-radius: 8px;
  padding: 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #fff;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-info {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 16px;
}

.message-stream {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
  min-height: 300px;
}

.message-item {
  margin-bottom: 12px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border-left: 3px solid transparent;
}

.message-item.type-USER_MESSAGE {
  border-left-color: #1890ff;
}

.message-item.type-AGENT_REPLY {
  border-left-color: #52c41a;
}

.message-item.type-AGENT_THINKING {
  border-left-color: #13c2c2;
}

.message-item.type-AGENT_TOOL_CALL {
  border-left-color: #faad14;
}

.message-item.type-AGENT_TOOL_RESULT {
  border-left-color: #a0d911;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
}

.message-channel {
  color: rgba(255, 255, 255, 0.5);
}

.message-time {
  color: rgba(255, 255, 255, 0.3);
  margin-left: auto;
}

.message-content {
  color: #fff;
}

.user-message,
.agent-message,
.tool-message,
.tool-result,
.thinking-message,
.other-message {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.agent-message {
  flex-direction: column;
}

.agent-content {
  flex: 1;
}

.reasoning {
  background: rgba(24, 144, 255, 0.1);
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
  font-size: 12px;
}

.reasoning-header {
  color: #1890ff;
  margin-bottom: 4px;
  font-weight: 500;
}

.reasoning-text {
  color: rgba(255, 255, 255, 0.7);
  white-space: pre-wrap;
}

.reply-text {
  white-space: pre-wrap;
  line-height: 1.6;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: rgba(255, 255, 255, 0.3);
}

.empty-state p {
  margin-top: 12px;
  font-size: 14px;
}

.empty-state .hint {
  font-size: 12px;
  margin-top: 4px;
}

.statistics {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.statistics :deep(.ant-statistic-title) {
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
}

.statistics :deep(.ant-statistic-content) {
  color: #fff;
  font-size: 20px;
}

/* 滚动条样式 */
.message-stream::-webkit-scrollbar {
  width: 6px;
}

.message-stream::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
}

.message-stream::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
}

.message-stream::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}
</style>