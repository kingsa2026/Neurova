&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;HookIcon :style="{ color: '#8b5cf6' }" /&gt; Webhook 管理&lt;/h2&gt;
      &lt;div &gt;
        &lt;a-button @click="loadWebhooks" :loading="loading"&gt;&lt;ReloadOutlined /&gt; 刷新&lt;/a-button&gt;
        &lt;a-button type="primary" @click="openAddWebhook"&gt;&lt;PlusOutlined /&gt; 创建 Webhook&lt;/a-button&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;HookIcon  /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ webhooks.length }}&lt;/div&gt;
          &lt;div &gt;Webhook 总数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;CheckCircleOutlined  style="color: #34d399" /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ webhooks.filter(w =&gt; w.is_active !== false).length }}&lt;/div&gt;
          &lt;div &gt;已启用&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;ExclamationCircleOutlined  style="color: #f59e0b" /&gt;
        &lt;div &gt;
          &lt;div &gt;{{ failedCount }}&lt;/div&gt;
          &lt;div &gt;失败投递&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" /&gt;
    &lt;a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" /&gt;
    &lt;div v-if="!loading" &gt;
      &lt;a-table :columns="columns" :data-source="webhooks" row-key="id" size="middle" :pagination="pagination"&gt;
        &lt;template #bodyCell="{ column, record }"&gt;
          &lt;template v-if="column.key === 'name'"&gt;
            &lt;div &gt;
              &lt;HookIcon style="color: #8b5cf6" /&gt;
              &lt;span&gt;{{ record.name }}&lt;/span&gt;
            &lt;/div&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'url'"&gt;
            &lt;a-tooltip :title="record.url"&gt;
              &lt;span &gt;{{ record.url }}&lt;/span&gt;
            &lt;/a-tooltip&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'events'"&gt;
            &lt;a-tag v-for="event in (record.events || [])" :key="event" size="small" color="blue"&gt;
              {{ getEventLabel(event) }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'is_active'"&gt;
            &lt;a-tag :color="record.is_active !== false ? 'green' : 'default'"&gt;
              {{ record.is_active !== false ? '启用' : '禁用' }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'stats'"&gt;
            &lt;a-space&gt;
              &lt;a-badge :count="record.success_count || 0" :number-style="{ backgroundColor: '#34d399' }" /&gt;
              &lt;a-badge :count="record.failure_count || 0" :number-style="{ backgroundColor: '#ef4444' }" /&gt;
            &lt;/a-space&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'action'"&gt;
            &lt;a-space&gt;
              &lt;a-button type="link" size="small" @click="openEdit(record)"&gt;编辑&lt;/a-button&gt;
              &lt;a-button type="link" size="small" @click="handleTest(record)"&gt;测试&lt;/a-button&gt;
              &lt;a-button type="link" size="small" @click="openDeliveries(record)"&gt;投递&lt;/a-button&gt;
              &lt;a-popconfirm title="删除此 Webhook?" @confirm="handleDelete(record.id)"&gt;
                &lt;a-button type="link" size="small" danger&gt;删除&lt;/a-button&gt;
              &lt;/a-popconfirm&gt;
            &lt;/a-space&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
    &lt;!-- 添加/编辑弹窗 --&gt;
    &lt;a-modal
      v-model:open="formOpen"
      :title="editingWebhook ? '编辑 Webhook' : '创建 Webhook'"
      @ok="handleSave"
      :confirm-loading="saving"
      ok-text="保存"
      cancel-text="取消"
      width="600px"
    &gt;
      &lt;a-form layout="vertical"&gt;
        &lt;a-form-item label="名称" required&gt;
          &lt;a-input v-model:value="form.name" placeholder="输入 Webhook 名称" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="URL" required&gt;
          &lt;a-input v-model:value="form.url" placeholder="https://your-server.com/webhook" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="事件类型" required&gt;
          &lt;a-select v-model:value="form.events" mode="multiple" placeholder="选择要监听的事件" style="width: 100%"&gt;
            &lt;a-select-option value="CHAT_MESSAGE_RECEIVED"&gt;聊天消息&lt;/a-select-option&gt;
            &lt;a-select-option value="AGENT_CREATED"&gt;Agent 创建&lt;/a-select-option&gt;
            &lt;a-select-option value="AGENT_UPDATED"&gt;Agent 更新&lt;/a-select-option&gt;
            &lt;a-select-option value="SKILL_INSTALLED"&gt;技能安装&lt;/a-select-option&gt;
            &lt;a-select-option value="MEMORY_CREATED"&gt;记忆创建&lt;/a-select-option&gt;
            &lt;a-select-option value="WORKFLOW_STARTED"&gt;工作流启动&lt;/a-select-option&gt;
            &lt;a-select-option value="WORKFLOW_COMPLETED"&gt;工作流完成&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="过滤条件 - Agent IDs"&gt;
          &lt;a-select v-model:value="form.filter_agents" mode="tags" placeholder="输入 Agent ID" style="width: 100%" allow-clear /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="最大重试次数"&gt;
          &lt;a-input-number v-model:value="form.max_retries" :min="0" :max="10" style="width: 100%" /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="启用状态"&gt;
          &lt;a-switch v-model:checked="form.is_active" /&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/a-modal&gt;
    &lt;!-- 投递记录弹窗 --&gt;
    &lt;a-modal v-model:open="deliveriesOpen" title="投递记录" :footer="null" width="800px"&gt;
      &lt;a-spin v-if="loadingDeliveries" /&gt;
      &lt;a-list v-else :data-source="deliveries" size="small" bordered&gt;
        &lt;template #renderItem="{ item }"&gt;
          &lt;a-list-item&gt;
            &lt;a-list-item-meta
              :title="formatTime(item.created_at)"
              :description="item.response_status ? '响应状态: ' + item.response_status : '等待响应'"
            &gt;
              &lt;template #avatar&gt;
                &lt;a-badge :status="getDeliveryStatus(item)" /&gt;
              &lt;/template&gt;
            &lt;/a-list-item-meta&gt;
            &lt;template #actions&gt;
              &lt;a-button type="link" size="small" @click="viewDeliveryDetail(item)"&gt;详情&lt;/a-button&gt;
              &lt;a-button
                v-if="item.status === 'failed'"
                type="link"
                size="small"
                @click="handleRetryDelivery(item)"
              &gt;
                重试
              &lt;/a-button&gt;
            &lt;/template&gt;
          &lt;/a-list-item&gt;
        &lt;/template&gt;
      &lt;/a-list&gt;
    &lt;/a-modal&gt;
    &lt;!-- 投递详情弹窗 --&gt;
    &lt;a-modal v-model:open="detailOpen" title="投递详情" :footer="null" width="700px"&gt;
      &lt;a-descriptions bordered :column="1" v-if="currentDelivery"&gt;
        &lt;a-descriptions-item label="投递 ID"&gt;{{ currentDelivery.id }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="创建时间"&gt;{{ currentDelivery.created_at }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="状态"&gt;
          &lt;a-tag :color="getDeliveryColor(currentDelivery.status)"&gt;{{ currentDelivery.status }}&lt;/a-tag&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="事件类型"&gt;{{ getEventLabel(currentDelivery.event_type) }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="响应状态"&gt;{{ currentDelivery.response_status || '-' }}&lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="响应体"&gt;
          &lt;pre style="white-space: pre-wrap"&gt;{{ currentDelivery.response_body || '无' }}&lt;/pre&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="错误信息"&gt;
          &lt;span v-if="currentDelivery.error"&gt;{{ currentDelivery.error }}&lt;/span&gt;
          &lt;span v-else&gt;-&lt;/span&gt;
        &lt;/a-descriptions-item&gt;
      &lt;/a-descriptions&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import {
  ReloadOutlined,
  PlusOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons-vue'
import { webhooksAPI } from '@/api/modules/webhooks'
import { h } from 'vue'
const HookIcon = () =&gt; h('span', { style: 'font-size: 1.2rem' }, '🔗')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
interface WebhookData {
  id: string
  name: string
  url: string
  events?: string[]
  filter_agents?: string[]
  max_retries?: number
  is_active?: boolean
  success_count?: number
  failure_count?: number
}
interface DeliveryData {
  id: string
  status?: string
  created_at?: string
  response_status?: number | string
  response_body?: string
  event_type?: string
  error?: string
}
const webhooks = ref&lt;WebhookData[]&gt;([])
const failedCount = ref(0)
const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: 'URL', dataIndex: 'url', key: 'url', ellipsis: true },
  { title: '事件', dataIndex: 'events', key: 'events' },
  { title: '状态', dataIndex: 'is_active', key: 'is_active', width: 100 },
  { title: '统计', key: 'stats', width: 120 },
  { title: '操作', key: 'action', width: 280, fixed: 'right' },
]
const pagination = reactive({
  current: 1,
  pageSize: 10,
  total: 0,
  showSizeChanger: true,
  showQuickJumper: true,
})
const formOpen = ref(false)
const editingWebhook = ref&lt;WebhookData | null&gt;(null)
const form = reactive({
  name: '',
  url: '',
  events: [] as string[],
  filter_agents: [] as string[],
  max_retries: 3,
  is_active: true,
})
const deliveriesOpen = ref(false)
const loadingDeliveries = ref(false)
const currentWebhookId = ref('')
const deliveries = ref&lt;DeliveryData[]&gt;([])
const detailOpen = ref(false)
const currentDelivery = ref&lt;DeliveryData | null&gt;(null)
const eventLabels: Record&lt;string, string&gt; = {
  CHAT_MESSAGE_RECEIVED: '聊天消息',
  AGENT_CREATED: 'Agent 创建',
  AGENT_UPDATED: 'Agent 更新',
  SKILL_INSTALLED: '技能安装',
  MEMORY_CREATED: '记忆创建',
  WORKFLOW_STARTED: '工作流启动',
  WORKFLOW_COMPLETED: '工作流完成',
}
function getEventLabel(event: string) {
  return eventLabels[event] || event
}
async function loadWebhooks() {
  loading.value = true
  error.value = ''
  try {
    const res = await webhooksAPI.list({ page_size: 100 })
    if (res.data) {
      webhooks.value = res.data.items || res.data.webhooks || []
      pagination.total = res.data.total || webhooks.value.length
      failedCount.value = webhooks.value.reduce((sum, w) =&gt; sum + (w.failure_count || 0), 0)
    }
  } catch (e: unknown) {
    const err = e as { message?: string }
    error.value = err?.message || '加载 Webhooks 失败'
  } finally {
    loading.value = false
  }
}
function openAddWebhook() {
  editingWebhook.value = null
  form.name = ''
  form.url = ''
  form.events = []
  form.filter_agents = []
  form.max_retries = 3
  form.is_active = true
  formOpen.value = true
}
function openEdit(webhook: WebhookData) {
  editingWebhook.value = webhook
  form.name = webhook.name
  form.url = webhook.url
  form.events = webhook.events || []
  form.filter_agents = webhook.filter_agents || []
  form.max_retries = webhook.max_retries || 3
  form.is_active = webhook.is_active !== false
  formOpen.value = true
}
async function handleSave() {
  if (!form.name.trim() || !form.url.trim() || !form.events.length) {
    message.warning('请填写完整信息')
    return
  }
  saving.value = true
  try {
    const data = {
      name: form.name,
      url: form.url,
      events: form.events,
      filter_agents: form.filter_agents,
      max_retries: form.max_retries,
      is_active: form.is_active,
    }
    let res
    if (editingWebhook.value) {
      res = await webhooksAPI.update(editingWebhook.value.id, data)
    } else {
      res = await webhooksAPI.create(data)
    }
    if (res.data?.success || res.data?.code === 0) {
      message.success(editingWebhook.value ? '已更新' : '已创建')
      formOpen.value = false
      await loadWebhooks()
    } else {
      message.error(res.data?.message || '保存失败')
    }
  } catch (e: unknown) {
    message.error((e as Error).message || '保存失败')
  } finally {
    saving.value = false
  }
}
async function handleDelete(id: string) {
  try {
    const res = await webhooksAPI.delete(id)
    if (res.data?.success || res.data?.code === 0) {
      message.success('已删除')
      await loadWebhooks()
    } else {
      message.error(res.data?.message || '删除失败')
    }
  } catch (e: unknown) {
    message.error((e as Error).message || '删除失败')
  }
}
async function handleTest(webhook: WebhookData) {
  try {
    const res = await webhooksAPI.test(webhook.id)
    if (res.data?.success || res.data?.code === 0) {
      message.success('测试请求已发送')
    } else {
      message.error(res.data?.message || '测试失败')
    }
  } catch (e: unknown) {
    message.error((e as Error).message || '测试失败')
  }
}
async function openDeliveries(webhook: WebhookData) {
  currentWebhookId.value = webhook.id
  deliveriesOpen.value = true
  loadingDeliveries.value = true
  try {
    const res = await webhooksAPI.getDeliveries(webhook.id)
    if (res.data) {
      deliveries.value = res.data.items || res.data.deliveries || []
    }
  } catch (e: unknown) {
    message.error((e as Error).message || '加载投递记录失败')
  } finally {
    loadingDeliveries.value = false
  }
}
function viewDeliveryDetail(delivery: DeliveryData) {
  currentDelivery.value = delivery
  detailOpen.value = true
}
async function handleRetryDelivery(delivery: DeliveryData) {
  try {
    const res = await webhooksAPI.retryDelivery(currentWebhookId.value, delivery.id)
    if (res.data?.success || res.data?.code === 0) {
      message.success('重试请求已发送')
      await openDeliveries({ id: currentWebhookId.value })
    } else {
      message.error(res.data?.message || '重试失败')
    }
  } catch (e: unknown) {
    message.error((e as Error).message || '重试失败')
  }
}
function getDeliveryStatus(item: DeliveryData) {
  if (item.status === 'success') return 'success'
  if (item.status === 'failed') return 'error'
  return 'warning'
}
function getDeliveryColor(status: string) {
  if (status === 'success') return 'green'
  if (status === 'failed') return 'red'
  return 'orange'
}
function formatTime(time: string) {
  if (!time) return '-'
  return new Date(time).toLocaleString()
}
onMounted(() =&gt; {
  loadWebhooks()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
}
.hd {
  padding: 14px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hd-actions {
  display: flex;
  gap: 8px;
}
.t {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sr {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.s {
  padding: 20px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.s-icon {
  font-size: 2rem;
  color: #8b5cf6;
}
.s-info {
  flex: 1;
}
.s-num {
  font-size: 1.5rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.s-label {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.tb {
  padding: 20px;
  border-radius: 12px;
}
.webhook-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.url-text {
  font-family: monospace;
  font-size: 0.85rem;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
&lt;/style&gt;
&nbsp;