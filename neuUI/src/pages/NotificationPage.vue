<template>
  <div >
    <div >
      <div >
        <h2 >
          <BellOutlined style="color: #f59e0b" />
          通知中心
        </h2>
        <div >
          <a-tag color="blue">未读 <strong>{{ unreadCount }}</strong></a-tag>
          <a-tag>总计 <strong>{{ totalCount }}</strong></a-tag>
        </div>
      </div>
      <div >
        <a-button size="small" @click="markAllAsRead" :loading="markingAllAsRead">
          全部已读
        </a-button>
        <a-button size="small" danger @click="clearArchived" v-if="showArchived">
          清空已归档
        </a-button>
      </div>
    </div>
    <div >
      <a-radio-group v-model:value="currentFilter" button-style="solid" size="small">
        <a-radio-button value="all">全部</a-radio-button>
        <a-radio-button value="unread">未读</a-radio-button>
        <a-radio-button value="archived">已归档</a-radio-button>
      </a-radio-group>
      <a-select v-model:value="selectedType" style="width: 150px" placeholder="通知类型" allow-clear size="small">
        <a-select-option value="info">信息</a-select-option>
        <a-select-option value="success">成功</a-select-option>
        <a-select-option value="warning">警告</a-select-option>
        <a-select-option value="error">错误</a-select-option>
        <a-select-option value="system">系统</a-select-option>
        <a-select-option value="agent">Agent</a-select-option>
        <a-select-option value="task">任务</a-select-option>
      </a-select>
    </div>
    <div >
      <a-spin :spinning="loading">
        <a-empty v-if="notifications.length === 0 && !loading" description="暂无通知" />
        <template v-else>
          <div
            v-for="notification in notifications"
            :key="notification.id"
            :
          >
            <div  :style="{ background: getTypeColor(notification.type) + '20', color: getTypeColor(notification.type) }">
              <component :is="getTypeIcon(notification.type)" />
            </div>
            <div >
              <div >
                <span >{{ notification.title }}</span>
                <div >
                  <a-tag v-if="!notification.is_read" color="blue" size="small">新</a-tag>
                  <a-tag v-if="notification.is_archived" size="small">已归档</a-tag>
                  <a-tag :color="getPriorityColor(notification.priority)" size="small">{{ getPriorityText(notification.priority) }}</a-tag>
                </div>
              </div>
              <p >{{ notification.content }}</p>
              <span >{{ formatTime(notification.created_at) }}</span>
            </div>
            <div >
              <template v-if="!notification.is_archived">
                <a-tooltip v-if="!notification.is_read" title="标记已读">
                  <a-button type="link" size="small" @click="markAsRead(notification.id)">
                    <CheckOutlined />
                  </a-button>
                </a-tooltip>
                <a-tooltip v-else title="标记未读">
                  <a-button type="link" size="small" @click="markAsUnread(notification.id)">
                    <UndoOutlined />
                  </a-button>
                </a-tooltip>
                <a-tooltip title="归档">
                  <a-button type="link" size="small" @click="archiveNotification(notification.id)">
                    <InboxOutlined />
                  </a-button>
                </a-tooltip>
              </template>
              <template v-else>
                <a-tooltip title="取消归档">
                  <a-button type="link" size="small" @click="unarchiveNotification(notification.id)">
                    <RollbackOutlined />
                  </a-button>
                </a-tooltip>
              </template>
              <a-popconfirm
                title="确定要删除这条通知吗？"
                ok-text="确定"
                cancel-text="取消"
                @confirm="deleteNotification(notification.id)"
              >
                <a-tooltip title="删除">
                  <a-button type="link" danger size="small">
                    <DeleteOutlined />
                  </a-button>
                </a-tooltip>
              </a-popconfirm>
            </div>
          </div>
        </template>
      </a-spin>
      <a-pagination
        v-if="totalCount > pageSize"
        v-model:current="currentPage"
        v-model:page-size="pageSize"
        :total="totalCount"
        size="small"
        show-less-items
        show-size-changer
        :page-size-options="['10', '20', '50']"
        @change="loadNotifications"
      />
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  BellOutlined,
  InfoCircleOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  ThunderboltOutlined,
  UserOutlined,
  FolderOutlined,
  CheckOutlined,
  UndoOutlined,
  InboxOutlined,
  RollbackOutlined,
  DeleteOutlined,
} from '@ant-design/icons-vue'
import { notificationsAPI, type Notification } from '@/api/modules/notifications'
const notifications = ref<Notification[]>([])
const loading = ref(false)
const markingAllAsRead = ref(false)
const unreadCount = ref(0)
const totalCount = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const currentFilter = ref<'all' | 'unread' | 'archived'>('all')
const selectedType = ref<string | undefined>(undefined)
const showArchived = computed(() => currentFilter.value === 'archived')
const typeIcons: Record<string, Component> = {
  info: InfoCircleOutlined,
  success: CheckCircleOutlined,
  warning: WarningOutlined,
  error: WarningOutlined,
  system: ThunderboltOutlined,
  agent: UserOutlined,
  message: FolderOutlined,
  task: CheckCircleOutlined,
}
const typeColors: Record<string, string> = {
  info: '#3b82f6',
  success: '#34d399',
  warning: '#f59e0b',
  error: '#ef4444',
  system: '#8b5cf6',
  agent: '#60a5fa',
  message: '#10b981',
  task: '#f97316',
}
const priorityColors: Record<string, string> = {
  low: 'default',
  normal: 'blue',
  high: 'orange',
  urgent: 'red',
}
const priorityTexts: Record<string, string> = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}
function getTypeIcon(type: string) {
  return typeIcons[type] || InfoCircleOutlined
}
function getTypeColor(type: string) {
  return typeColors[type] || '#60a5fa'
}
function getPriorityColor(priority: string) {
  return priorityColors[priority] || 'default'
}
function getPriorityText(priority: string) {
  return priorityTexts[priority] || '普通'
}
function formatTime(timeStr: string) {
  const date = new Date(timeStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)} 天前`
  return date.toLocaleDateString('zh-CN')
}
async function loadNotifications() {
  loading.value = true
  try {
    const res = await notificationsAPI.getNotifications({
      page: currentPage.value,
      page_size: pageSize.value,
      type: selectedType.value as 'system' | 'agent' | 'message' | 'task' | undefined,
      unread_only: currentFilter.value === 'unread',
      archived: currentFilter.value === 'archived',
    })
    notifications.value = res.items || []
    totalCount.value = res.total || 0
    unreadCount.value = res.unread_count || 0
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '加载通知失败')
  } finally {
    loading.value = false
  }
}
async function loadUnreadCount() {
  try {
    const res = await notificationsAPI.getUnreadCount()
    unreadCount.value = res.count
  } catch (err) {
    console.error('Failed to load unread count:', err)
  }
}
async function markAsRead(id: string) {
  try {
    await notificationsAPI.markAsRead(id)
    message.success('已标记为已读')
    await loadNotifications()
    await loadUnreadCount()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '操作失败')
  }
}
async function markAsUnread(id: string) {
  try {
    await notificationsAPI.markAsUnread(id)
    message.success('已标记为未读')
    await loadNotifications()
    await loadUnreadCount()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '操作失败')
  }
}
async function markAllAsRead() {
  markingAllAsRead.value = true
  try {
    await notificationsAPI.markAllAsRead()
    message.success('全部已标记为已读')
    await loadNotifications()
    await loadUnreadCount()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '操作失败')
  } finally {
    markingAllAsRead.value = false
  }
}
async function archiveNotification(id: string) {
  try {
    await notificationsAPI.archiveNotification(id)
    message.success('已归档')
    await loadNotifications()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '操作失败')
  }
}
async function unarchiveNotification(id: string) {
  try {
    await notificationsAPI.unarchiveNotification(id)
    message.success('已取消归档')
    await loadNotifications()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '操作失败')
  }
}
async function deleteNotification(id: string) {
  try {
    await notificationsAPI.deleteNotification(id)
    message.success('已删除')
    await loadNotifications()
    await loadUnreadCount()
  } catch (err: unknown) {
    const e = err as { response?: { data?: { message?: string } } }
    message.error(e.response?.data?.message || '删除失败')
  }
}
async function clearArchived() {
  try {
    await notificationsAPI.clearArchived()
    message.success('已清空已归档通知')
    await loadNotifications()
  } catch (err: unknown) {
    const e = err as {response?:{data?:{message?:string}}}
    message.error(e.response?.data?.message || '操作失败')
  }
}
onMounted(async () => {
  await loadNotifications()
})
</script>
<style scoped>
.notification-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-radius: 12px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.page-title {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.stats {
  display: flex;
  gap: 8px;
}
.header-right {
  display: flex;
  gap: 8px;
}
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  border-radius: 12px;
}
.notification-list {
  padding: 16px;
  border-radius: 12px;
  min-height: 400px;
}
.notification-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 16px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 12px;
  background: rgba(255, 255, 255, 0.02);
  transition: all 0.2s;
}
.notification-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.1);
}
.notification-item.unread {
  border-left: 3px solid #60a5fa;
  background: rgba(96, 165, 250, 0.05);
}
.notification-item.archived {
  opacity: 0.6;
}
.notification-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  flex-shrink: 0;
}
.notification-content {
  flex: 1;
  min-width: 0;
}
.notification-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 4px;
}
.notification-title {
  color: #e2e8f0;
  font-weight: 500;
  font-size: 0.95rem;
}
.notification-meta {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.notification-desc {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.85rem;
  margin: 0 0 6px;
  line-height: 1.5;
}
.notification-time {
  color: rgba(255, 255, 255, 0.3);
  font-size: 0.75rem;
}
.notification-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
</style>
 