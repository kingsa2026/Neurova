&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;h2 &gt;
          &lt;BellOutlined style="color: #f59e0b" /&gt;
          通知中心
        &lt;/h2&gt;
        &lt;div &gt;
          &lt;a-tag color="blue"&gt;未读 &lt;strong&gt;{{ unreadCount }}&lt;/strong&gt;&lt;/a-tag&gt;
          &lt;a-tag&gt;总计 &lt;strong&gt;{{ totalCount }}&lt;/strong&gt;&lt;/a-tag&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;a-button size="small" @click="markAllAsRead" :loading="markingAllAsRead"&gt;
          全部已读
        &lt;/a-button&gt;
        &lt;a-button size="small" danger @click="clearArchived" v-if="showArchived"&gt;
          清空已归档
        &lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-radio-group v-model:value="currentFilter" button-style="solid" size="small"&gt;
        &lt;a-radio-button value="all"&gt;全部&lt;/a-radio-button&gt;
        &lt;a-radio-button value="unread"&gt;未读&lt;/a-radio-button&gt;
        &lt;a-radio-button value="archived"&gt;已归档&lt;/a-radio-button&gt;
      &lt;/a-radio-group&gt;
      &lt;a-select v-model:value="selectedType" style="width: 150px" placeholder="通知类型" allow-clear size="small"&gt;
        &lt;a-select-option value="info"&gt;信息&lt;/a-select-option&gt;
        &lt;a-select-option value="success"&gt;成功&lt;/a-select-option&gt;
        &lt;a-select-option value="warning"&gt;警告&lt;/a-select-option&gt;
        &lt;a-select-option value="error"&gt;错误&lt;/a-select-option&gt;
        &lt;a-select-option value="system"&gt;系统&lt;/a-select-option&gt;
        &lt;a-select-option value="agent"&gt;Agent&lt;/a-select-option&gt;
        &lt;a-select-option value="task"&gt;任务&lt;/a-select-option&gt;
      &lt;/a-select&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;a-spin :spinning="loading"&gt;
        &lt;a-empty v-if="notifications.length === 0 &amp;&amp; !loading" description="暂无通知" /&gt;
        &lt;template v-else&gt;
          &lt;div
            v-for="notification in notifications"
            :key="notification.id"
            :
          &gt;
            &lt;div  :style="{ background: getTypeColor(notification.type) + '20', color: getTypeColor(notification.type) }"&gt;
              &lt;component :is="getTypeIcon(notification.type)" /&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;div &gt;
                &lt;span &gt;{{ notification.title }}&lt;/span&gt;
                &lt;div &gt;
                  &lt;a-tag v-if="!notification.is_read" color="blue" size="small"&gt;新&lt;/a-tag&gt;
                  &lt;a-tag v-if="notification.is_archived" size="small"&gt;已归档&lt;/a-tag&gt;
                  &lt;a-tag :color="getPriorityColor(notification.priority)" size="small"&gt;{{ getPriorityText(notification.priority) }}&lt;/a-tag&gt;
                &lt;/div&gt;
              &lt;/div&gt;
              &lt;p &gt;{{ notification.content }}&lt;/p&gt;
              &lt;span &gt;{{ formatTime(notification.created_at) }}&lt;/span&gt;
            &lt;/div&gt;
            &lt;div &gt;
              &lt;template v-if="!notification.is_archived"&gt;
                &lt;a-tooltip v-if="!notification.is_read" title="标记已读"&gt;
                  &lt;a-button type="link" size="small" @click="markAsRead(notification.id)"&gt;
                    &lt;CheckOutlined /&gt;
                  &lt;/a-button&gt;
                &lt;/a-tooltip&gt;
                &lt;a-tooltip v-else title="标记未读"&gt;
                  &lt;a-button type="link" size="small" @click="markAsUnread(notification.id)"&gt;
                    &lt;UndoOutlined /&gt;
                  &lt;/a-button&gt;
                &lt;/a-tooltip&gt;
                &lt;a-tooltip title="归档"&gt;
                  &lt;a-button type="link" size="small" @click="archiveNotification(notification.id)"&gt;
                    &lt;InboxOutlined /&gt;
                  &lt;/a-button&gt;
                &lt;/a-tooltip&gt;
              &lt;/template&gt;
              &lt;template v-else&gt;
                &lt;a-tooltip title="取消归档"&gt;
                  &lt;a-button type="link" size="small" @click="unarchiveNotification(notification.id)"&gt;
                    &lt;RollbackOutlined /&gt;
                  &lt;/a-button&gt;
                &lt;/a-tooltip&gt;
              &lt;/template&gt;
              &lt;a-popconfirm
                title="确定要删除这条通知吗？"
                ok-text="确定"
                cancel-text="取消"
                @confirm="deleteNotification(notification.id)"
              &gt;
                &lt;a-tooltip title="删除"&gt;
                  &lt;a-button type="link" danger size="small"&gt;
                    &lt;DeleteOutlined /&gt;
                  &lt;/a-button&gt;
                &lt;/a-tooltip&gt;
              &lt;/a-popconfirm&gt;
            &lt;/div&gt;
          &lt;/div&gt;
        &lt;/template&gt;
      &lt;/a-spin&gt;
      &lt;a-pagination
        v-if="totalCount &gt; pageSize"
        v-model:current="currentPage"
        v-model:page-size="pageSize"
        :total="totalCount"
        size="small"
        show-less-items
        show-size-changer
        :page-size-options="['10', '20', '50']"
        @change="loadNotifications"
      /&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
const notifications = ref&lt;Notification[]&gt;([])
const loading = ref(false)
const markingAllAsRead = ref(false)
const unreadCount = ref(0)
const totalCount = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const currentFilter = ref&lt;'all' | 'unread' | 'archived'&gt;('all')
const selectedType = ref&lt;string | undefined&gt;(undefined)
const showArchived = computed(() =&gt; currentFilter.value === 'archived')
const typeIcons: Record&lt;string, Component&gt; = {
  info: InfoCircleOutlined,
  success: CheckCircleOutlined,
  warning: WarningOutlined,
  error: WarningOutlined,
  system: ThunderboltOutlined,
  agent: UserOutlined,
  message: FolderOutlined,
  task: CheckCircleOutlined,
}
const typeColors: Record&lt;string, string&gt; = {
  info: '#3b82f6',
  success: '#34d399',
  warning: '#f59e0b',
  error: '#ef4444',
  system: '#8b5cf6',
  agent: '#60a5fa',
  message: '#10b981',
  task: '#f97316',
}
const priorityColors: Record&lt;string, string&gt; = {
  low: 'default',
  normal: 'blue',
  high: 'orange',
  urgent: 'red',
}
const priorityTexts: Record&lt;string, string&gt; = {
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
  if (diff &lt; 60000) return '刚刚'
  if (diff &lt; 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff &lt; 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  if (diff &lt; 604800000) return `${Math.floor(diff / 86400000)} 天前`
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
onMounted(async () =&gt; {
  await loadNotifications()
})
&lt;/script&gt;
&lt;style scoped&gt;
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
&lt;/style&gt;
&nbsp;