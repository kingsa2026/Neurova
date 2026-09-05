<template>
  <div class="pg">
    <div class="hd glass-effect">
      <h2 class="t"><HookIcon :style="{ color: '#8b5cf6' }" /> Webhook 管理</h2>
      <div class="hd-actions">
        <a-button @click="loadWebhooks" :loading="loading"><ReloadOutlined /> 刷新</a-button>
        <a-button type="primary" @click="openAddWebhook"><PlusOutlined /> 创建 Webhook</a-button>
      </div>
    </div>

    <div class="sr">
      <div class="s glass-effect">
        <HookIcon class="s-icon" />
        <div class="s-info">
          <div class="s-num">{{ webhooks.length }}</div>
          <div class="s-label">Webhook 总数</div>
        </div>
      </div>
      <div class="s glass-effect">
        <CheckCircleOutlined class="s-icon" style="color: #34d399" />
        <div class="s-info">
          <div class="s-num">{{ webhooks.filter(w => w.is_active !== false).length }}</div>
          <div class="s-label">已启用</div>
        </div>
      </div>
      <div class="s glass-effect">
        <ExclamationCircleOutlined class="s-icon" style="color: #f59e0b" />
        <div class="s-info">
          <div class="s-num">{{ failedCount }}</div>
          <div class="s-label">失败投递</div>
        </div>
      </div>
    </div>

    <a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" />
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />

    <div v-if="!loading" class="tb glass-effect">
      <a-table :columns="columns" :data-source="webhooks" row-key="id" size="middle" :pagination="pagination">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <div class="webhook-name">
              <HookIcon style="color: #8b5cf6" />
              <span>{{ record.name }}</span>
            </div>
          </template>
          <template v-else-if="column.key === 'url'">
            <a-tooltip :title="record.url">
              <span class="url-text">{{ record.url }}</span>
            </a-tooltip>
          </template>
          <template v-else-if="column.key === 'events'">
            <a-tag v-for="event in (record.events || [])" :key="event" size="small" color="blue">
              {{ getEventLabel(event) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'is_active'">
            <a-tag :color="record.is_active !== false ? 'green' : 'default'">
              {{ record.is_active !== false ? '启用' : '禁用' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'stats'">
            <a-space>
              <a-badge :count="record.success_count || 0" :number-style="{ backgroundColor: '#34d399' }" />
              <a-badge :count="record.failure_count || 0" :number-style="{ backgroundColor: '#ef4444' }" />
            </a-space>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-button type="link" size="small" @click="openEdit(record)">编辑</a-button>
              <a-button type="link" size="small" @click="handleTest(record)">测试</a-button>
              <a-button type="link" size="small" @click="openDeliveries(record)">投递</a-button>
              <a-popconfirm title="删除此 Webhook?" @confirm="handleDelete(record.id)">
                <a-button type="link" size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>

    <!-- 添加/编辑弹窗 -->
    <a-modal
      v-model:open="formOpen"
      :title="editingWebhook ? '编辑 Webhook' : '创建 Webhook'"
      @ok="handleSave"
      :confirm-loading="saving"
      ok-text="保存"
      cancel-text="取消"
      width="600px"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="输入 Webhook 名称" />
        </a-form-item>
        <a-form-item label="URL" required>
          <a-input v-model:value="form.url" placeholder="https://your-server.com/webhook" />
        </a-form-item>
        <a-form-item label="事件类型" required>
          <a-select v-model:value="form.events" mode="multiple" placeholder="选择要监听的事件" style="width: 100%">
            <a-select-option value="CHAT_MESSAGE_RECEIVED">聊天消息</a-select-option>
            <a-select-option value="AGENT_CREATED">Agent 创建</a-select-option>
            <a-select-option value="AGENT_UPDATED">Agent 更新</a-select-option>
            <a-select-option value="SKILL_INSTALLED">技能安装</a-select-option>
            <a-select-option value="MEMORY_CREATED">记忆创建</a-select-option>
            <a-select-option value="WORKFLOW_STARTED">工作流启动</a-select-option>
            <a-select-option value="WORKFLOW_COMPLETED">工作流完成</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="过滤条件 - Agent IDs">
          <a-select v-model:value="form.filter_agents" mode="tags" placeholder="输入 Agent ID" style="width: 100%" allow-clear />
        </a-form-item>
        <a-form-item label="最大重试次数">
          <a-input-number v-model:value="form.max_retries" :min="0" :max="10" style="width: 100%" />
        </a-form-item>
        <a-form-item label="启用状态">
          <a-switch v-model:checked="form.is_active" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 投递记录弹窗 -->
    <a-modal v-model:open="deliveriesOpen" title="投递记录" :footer="null" width="800px">
      <a-spin v-if="loadingDeliveries" />
      <a-list v-else :data-source="deliveries" size="small" bordered>
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :title="formatTime(item.created_at)"
              :description="item.response_status ? '响应状态: ' + item.response_status : '等待响应'"
            >
              <template #avatar>
                <a-badge :status="getDeliveryStatus(item)" />
              </template>
            </a-list-item-meta>
            <template #actions>
              <a-button type="link" size="small" @click="viewDeliveryDetail(item)">详情</a-button>
              <a-button
                v-if="item.status === 'failed'"
                type="link"
                size="small"
                @click="handleRetryDelivery(item)"
              >
                重试
              </a-button>
            </template>
          </a-list-item>
        </template>
      </a-list>
    </a-modal>

    <!-- 投递详情弹窗 -->
    <a-modal v-model:open="detailOpen" title="投递详情" :footer="null" width="700px">
      <a-descriptions bordered :column="1" v-if="currentDelivery">
        <a-descriptions-item label="投递 ID">{{ currentDelivery.id }}</a-descriptions-item>
        <a-descriptions-item label="创建时间">{{ currentDelivery.created_at }}</a-descriptions-item>
        <a-descriptions-item label="状态">
          <a-tag :color="getDeliveryColor(currentDelivery.status)">{{ currentDelivery.status }}</a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="事件类型">{{ getEventLabel(currentDelivery.event_type) }}</a-descriptions-item>
        <a-descriptions-item label="响应状态">{{ currentDelivery.response_status || '-' }}</a-descriptions-item>
        <a-descriptions-item label="响应体">
          <pre style="white-space: pre-wrap">{{ currentDelivery.response_body || '无' }}</pre>
        </a-descriptions-item>
        <a-descriptions-item label="错误信息">
          <span v-if="currentDelivery.error">{{ currentDelivery.error }}</span>
          <span v-else>-</span>
        </a-descriptions-item>
      </a-descriptions>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
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

const HookIcon = () => h('span', { style: 'font-size: 1.2rem' }, '🔗')

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

const webhooks = ref<WebhookData[]>([])
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
const editingWebhook = ref<WebhookData | null>(null)
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
const deliveries = ref<DeliveryData[]>([])

const detailOpen = ref(false)
const currentDelivery = ref<DeliveryData | null>(null)

const eventLabels: Record<string, string> = {
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
      failedCount.value = webhooks.value.reduce((sum, w) => sum + (w.failure_count || 0), 0)
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

onMounted(() => {
  loadWebhooks()
})
</script>

<style scoped>
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
</style>
