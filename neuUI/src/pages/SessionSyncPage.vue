<template>
  <div class="session-sync-page">
    <a-page-header
      title="跨渠道会话同步"
      sub-title="实时同步手机、电脑等多个渠道的对话内容"
    >
      <template #extra>
        <a-space>
          <a-button @click="handleBack">
            <ArrowLeftOutlined /> 返回
          </a-button>
        </a-space>
      </template>
    </a-page-header>

    <div class="page-content">
      <a-row :gutter="24">
        <!-- 左侧：同步面板 -->
        <a-col :span="16">
          <a-card title="实时同步" :bordered="false" class="sync-card">
            <SessionSyncPanel
              :user-id="userId"
              :agent-id="agentId"
              :session-id="sessionId"
              @session-created="handleSessionCreated"
              @event-received="handleEventReceived"
            />
          </a-card>
        </a-col>

        <!-- 右侧：会话列表 -->
        <a-col :span="8">
          <a-card title="会话列表" :bordered="false" class="sessions-card">
            <template #extra>
              <a-button type="primary" size="small" @click="loadSessions">
                <ReloadOutlined />
              </a-button>
            </template>

            <a-list
              :data-source="sessions"
              :loading="loading"
              :pagination="{ pageSize: 10 }"
            >
              <template #renderItem="{ item }">
                <a-list-item
                  :class="{ 'active-session': item.session_id === sessionId }"
                  @click="handleSelectSession(item)"
                >
                  <a-list-item-meta>
                    <template #title>
                      <div class="session-title">
                        <span>{{ item.conversation_id }}</span>
                        <a-tag :color="item.status === 'active' ? 'green' : 'default'" size="small">
                          {{ item.status }}
                        </a-tag>
                      </div>
                    </template>
                    <template #description>
                      <div class="session-desc">
                        <div>用户: {{ item.user_id }}</div>
                        <div>渠道: {{ item.active_channels.join(', ') || '无' }}</div>
                        <div>最后活动: {{ formatTime(item.last_activity) }}</div>
                      </div>
                    </template>
                    <template #avatar>
                      <a-avatar :style="{ backgroundColor: getStatusColor(item.status) }">
                        <MessageOutlined />
                      </a-avatar>
                    </template>
                  </a-list-item-meta>
                </a-list-item>
              </template>

              <template #empty>
                <a-empty description="暂无会话" />
              </template>
            </a-list>
          </a-card>

          <!-- 快速操作 -->
          <a-card title="快速操作" :bordered="false" class="actions-card" style="margin-top:16px">
            <a-space direction="vertical" style="width:100%">
              <a-button 
                type="primary" 
                block 
                @click="handleNewSession"
                :loading="creating"
              >
                <PlusOutlined /> 创建新会话
              </a-button>
              
              <a-button 
                block 
                @click="handleViewStats"
              >
                <BarChartOutlined /> 查看统计
              </a-button>
            </a-space>
          </a-card>
        </a-col>
      </a-row>
    </div>

    <!-- 统计模态框 -->
    <a-modal
      v-model:open="statsVisible"
      title="同步统计"
      :footer="null"
      width="600px"
    >
      <a-row :gutter="24">
        <a-col :span="8">
          <a-statistic title="总会话数" :value="stats.total_sessions || 0" />
        </a-col>
        <a-col :span="8">
          <a-statistic title="活跃会话" :value="stats.active_sessions || 0" />
        </a-col>
        <a-col :span="8">
          <a-statistic title="总事件数" :value="stats.total_events || 0" />
        </a-col>
      </a-row>
      
      <a-divider />
      
      <a-row :gutter="24">
        <a-col :span="12">
          <a-statistic title="活跃连接" :value="stats.active_connections || 0" />
        </a-col>
        <a-col :span="12">
          <a-statistic title="历史会话" :value="stats.expired_sessions || 0" />
        </a-col>
      </a-row>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  PlusOutlined,
  BarChartOutlined,
  MessageOutlined,
} from '@ant-design/icons-vue'
import SessionSyncPanel from '@/components/SessionSyncPanel.vue'
import { 
  sessionSyncAPI, 
  type SessionInfo, 
  type SessionEvent,
} from '@/api/modules/session-sync'

const router = useRouter()

// 状态
const sessions = ref<SessionInfo[]>([])
const loading = ref(false)
const creating = ref(false)
const statsVisible = ref(false)
const stats = ref({
  total_sessions: 0,
  active_sessions: 0,
  expired_sessions: 0,
  total_events: 0,
  active_connections: 0,
})

// 当前选中的会话
const sessionId = ref<string | undefined>(undefined)

// 从本地存储获取用户信息
const userId = computed(() => {
  const user = localStorage.getItem('user')
  if (user) {
    try {
      const parsed = JSON.parse(user)
      return parsed.id || parsed.user_id || 'anonymous'
    } catch {
      return 'anonymous'
    }
  }
  return 'anonymous'
})

const agentId = computed(() => {
  return localStorage.getItem('currentAgentId') || 'default'
})

// 方法
async function loadSessions() {
  loading.value = true
  try {
    const result = await sessionSyncAPI.listSessions({
      user_id: userId.value,
      status: 'active',
    })
    sessions.value = result.sessions || []
  } catch (error: any) {
    message.error('加载会话失败: ' + (error.message || error))
  } finally {
    loading.value = false
  }
}

async function handleNewSession() {
  creating.value = true
  try {
    const newSession = await sessionSyncAPI.createSession({
      user_id: userId.value,
      agent_id: agentId.value,
    })
    
    sessions.value.unshift(newSession)
    sessionId.value = newSession.session_id
    message.success('会话创建成功')
  } catch (error: any) {
    message.error('创建会话失败: ' + (error.message || error))
  } finally {
    creating.value = false
  }
}

function handleSelectSession(session: SessionInfo) {
  sessionId.value = session.session_id
}

function handleSessionCreated(session: SessionInfo) {
  // 添加到列表（如果不存在）
  const exists = sessions.value.some(s => s.session_id === session.session_id)
  if (!exists) {
    sessions.value.unshift(session)
  }
}

function handleEventReceived(event: SessionEvent) {
  console.log('Event received:', event)
}

async function handleViewStats() {
  try {
    const result = await sessionSyncAPI.getStatistics()
    stats.value = {
      total_sessions: result.total_sessions || 0,
      active_sessions: result.active_sessions || 0,
      expired_sessions: result.expired_sessions || 0,
      total_events: result.total_events || 0,
      active_connections: result.active_connections || 0,
    }
    statsVisible.value = true
  } catch (error: any) {
    message.error('获取统计失败: ' + (error.message || error))
  }
}

function handleBack() {
  router.back()
}

function getStatusColor(status: string): string {
  const colorMap: Record<string, string> = {
    active: '#52c41a',
    paused: '#faad14',
    ended: '#ff4d4f',
    expired: '#d9d9d9',
  }
  return colorMap[status] || '#1890ff'
}

function formatTime(isoString: string): string {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 生命周期
onMounted(() => {
  loadSessions()
})
</script>

<style scoped>
.session-sync-page {
  padding: 24px;
  background: #f0f2f5;
  min-height: 100vh;
}

.page-content {
  margin-top: 16px;
}

.sync-card,
.sessions-card,
.actions-card {
  background: #fff;
  border-radius: 8px;
}

.sync-card {
  height: calc(100vh - 200px);
}

.sync-card :deep(.ant-card-body) {
  height: calc(100% - 57px);
  padding: 0;
}

.sessions-card {
  height: calc(100vh - 350px);
}

.sessions-card :deep(.ant-card-body) {
  height: calc(100% - 57px);
  overflow-y: auto;
}

.session-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.session-desc {
  font-size: 12px;
  color: rgba(0, 0, 0, 0.45);
  line-height: 1.8;
}

.active-session {
  background: #e6f7ff;
  border-radius: 4px;
}

.ant-list-item {
  cursor: pointer;
  transition: background 0.3s;
}

.ant-list-item:hover {
  background: #f5f5f5;
}
</style>