<template>
  <div >
    <!-- 页面标题 -->
    <div >
      <h2 >
        <AuditOutlined :style="{ color: '#f59e0b' }" />
        审计日志
      </h2>
      <a-space>
        <a-button @click="handleExport" :loading="exporting">
          <template #icon><DownloadOutlined /></template>
          导出
        </a-button>
        <a-button @click="loadLogs" :loading="loading">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </a-space>
    </div>
    <!-- 统计卡片 -->
    <div >
      <div >
        <div ><FileTextOutlined /></div>
        <div >
          <div >{{ stats.total || 0 }}</div>
          <div >总日志数</div>
        </div>
      </div>
      <div >
        <div ><ExclamationCircleOutlined /></div>
        <div >
          <div >{{ stats.warnings || 0 }}</div>
          <div >警告事件</div>
        </div>
      </div>
      <div >
        <div ><CloseCircleOutlined /></div>
        <div >
          <div >{{ stats.errors || 0 }}</div>
          <div >错误事件</div>
        </div>
      </div>
    </div>
    <!-- 筛选条件 -->
    <div >
      <a-form layout="inline" :model="filterForm">
        <a-form-item label="时间范围">
          <a-range-picker
            v-model:value="filterForm.dateRange"
            @change="handleFilter"
          />
        </a-form-item>
        <a-form-item label="事件类型">
          <a-select
            v-model:value="filterForm.event_type"
            placeholder="选择事件类型"
            allow-clear
            style="width: 150px"
            @change="handleFilter"
          >
            <a-select-option value="AUTH">认证</a-select-option>
            <a-select-option value="DATA_ACCESS">数据访问</a-select-option>
            <a-select-option value="SECURITY">安全</a-select-option>
            <a-select-option value="CONFIG">系统配置</a-select-option>
            <a-select-option value="AUTHORIZATION">授权</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="严重性">
          <a-select
            v-model:value="filterForm.severity"
            placeholder="选择严重性"
            allow-clear
            style="width: 120px"
            @change="handleFilter"
          >
            <a-select-option value="INFO">信息</a-select-option>
            <a-select-option value="WARNING">警告</a-select-option>
            <a-select-option value="ERROR">错误</a-select-option>
            <a-select-option value="CRITICAL">严重</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="用户">
          <a-input
            v-model:value="filterForm.actor_id"
            placeholder="输入用户 ID"
            allow-clear
            style="width: 150px"
            @pressEnter="handleFilter"
          />
        </a-form-item>
        <a-form-item>
          <a-button type="primary" @click="handleFilter">
            搜索
          </a-button>
          <a-button style="margin-left: 8px" @click="resetFilter">
            重置
          </a-button>
        </a-form-item>
      </a-form>
    </div>
    <!-- 日志列表 -->
    <div >
      <a-table
        :columns="columns"
        :data-source="logs"
        :loading="loading"
        :pagination="pagination"
        row-key="id"
        size="middle"
        :scroll="{ x: 1000 }"
        @change="handleTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'severity'">
            <a-tag :color="getSeverityColor(record.severity)">
              {{ getSeverityText(record.severity) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'event_type'">
            <a-tag :color="getEventTypeColor(record.event_type)">
              {{ getEventTypeText(record.event_type) }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'success'">
            <a-tag :color="record.success ? 'green' : 'red'">
              {{ record.success ? '成功' : '失败' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a-button type="link" size="small" @click="showDetail(record)">
                详情
              </a-button>
            </a-space>
          </template>
        </template>
      </a-table>
    </div>
    <!-- 详情弹窗 -->
    <a-modal
      v-model:open="detailVisible"
      title="日志详情"
      :footer="null"
      width="600px"
    >
      <a-descriptions bordered :column="1" v-if="currentLog">
        <a-descriptions-item label="日志 ID">
          {{ currentLog.id }}
        </a-descriptions-item>
        <a-descriptions-item label="时间">
          {{ currentLog.timestamp }}
        </a-descriptions-item>
        <a-descriptions-item label="事件类型">
          <a-tag :color="getEventTypeColor(currentLog.event_type)">
            {{ getEventTypeText(currentLog.event_type) }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="严重性">
          <a-tag :color="getSeverityColor(currentLog.severity)">
            {{ getSeverityText(currentLog.severity) }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="用户">
          {{ currentLog.actor_id || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="资源类型">
          {{ currentLog.resource_type || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="操作结果">
          <a-tag :color="currentLog.success ? 'green' : 'red'">
            {{ currentLog.success ? '成功' : '失败' }}
          </a-tag>
        </a-descriptions-item>
        <a-descriptions-item label="描述">
          {{ currentLog.description || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="详情">
          <pre style="white-space: pre-wrap; margin: 0">{{ currentLog.details || '无' }}</pre>
        </a-descriptions-item>
        <a-descriptions-item label="IP地址">
          {{ currentLog.ip_address || '-' }}
        </a-descriptions-item>
        <a-descriptions-item label="用户代理">
          {{ currentLog.user_agent || '-' }}
        </a-descriptions-item>
      </a-descriptions>
    </a-modal>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import type { TableProps } from 'ant-design-vue'
import {
  AuditOutlined,
  DownloadOutlined,
  ReloadOutlined,
  FileTextOutlined,
  ExclamationCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons-vue'
import { auditAPI } from '@/api/modules/audit'
import dayjs from 'dayjs'
const loading = ref(false)
const exporting = ref(false)
const detailVisible = ref(false)
interface AuditLog {
  id: string
  timestamp: string
  event_type: string
  severity: string
  actor_id?: string
  resource_type?: string
  success: boolean
  description?: string
  details?: unknown
  ip_address?: string
  user_agent?: string
}
const currentLog = ref<AuditLog | null>(null)
const stats = ref({
  total: 0,
  warnings: 0,
  errors: 0,
})
const filterForm = reactive({
  dateRange: [] as unknown[],
  event_type: undefined as string | undefined,
  severity: undefined as string | undefined,
  actor_id: undefined as string | undefined,
})
const pagination = reactive({
  current: 1,
  pageSize: 20,
  total: 0,
  showSizeChanger: true,
  showQuickJumper: true,
  showTotal: (total: number) => `共 ${total} 条`,
})
const columns = [
  {
    title: '时间',
    dataIndex: 'timestamp',
    key: 'timestamp',
    width: 180,
  },
  {
    title: '事件类型',
    dataIndex: 'event_type',
    key: 'event_type',
    width: 120,
  },
  {
    title: '用户',
    dataIndex: 'actor_id',
    key: 'actor_id',
    width: 120,
  },
  {
    title: '严重性',
    dataIndex: 'severity',
    key: 'severity',
    width: 100,
  },
  {
    title: '结果',
    dataIndex: 'success',
    key: 'success',
    width: 80,
  },
  {
    title: '描述',
    dataIndex: 'description',
    key: 'description',
    ellipsis: true,
  },
  {
    title: '操作',
    key: 'action',
    width: 80,
    fixed: 'right',
  },
]
const logs = ref<AuditLog[]>([])
const loadLogs = async () => {
  try {
    loading.value = true
    const params: Record<string, unknown> = {
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    if (filterForm.dateRange && filterForm.dateRange.length === 2) {
      params.start_time = dayjs(filterForm.dateRange[0]).startOf('day').toISOString()
      params.end_time = dayjs(filterForm.dateRange[1]).endOf('day').toISOString()
    }
    if (filterForm.event_type) {
      params.event_type = filterForm.event_type
    }
    if (filterForm.severity) {
      params.severity = filterForm.severity
    }
    if (filterForm.actor_id) {
      params.actor_id = filterForm.actor_id
    }
    const res = await auditAPI.getLogs(params)
    if (res.data) {
      logs.value = res.data.logs || res.data.items || []
      pagination.total = res.data.total || logs.value.length
      stats.value = {
        total: res.data.stats?.total || logs.value.length,
        warnings: res.data.stats?.warnings || 0,
        errors: res.data.stats?.errors || 0,
      }
    }
  } catch (error) {
    message.error('加载审计日志失败')
    logs.value = []
  } finally {
    loading.value = false
  }
}
const handleFilter = () => {
  pagination.current = 1
  loadLogs()
}
const resetFilter = () => {
  filterForm.dateRange = []
  filterForm.event_type = undefined
  filterForm.severity = undefined
  filterForm.actor_id = undefined
  handleFilter()
}
const handleTableChange: TableProps['onChange'] = (pag) => {
  pagination.current = pag.current || 1
  pagination.pageSize = pag.pageSize || 20
  loadLogs()
}
const handleExport = async () => {
  try {
    exporting.value = true
    const params: Record<string, unknown> = { format: 'csv' }
    if (filterForm.dateRange && filterForm.dateRange.length === 2) {
      params.start_time = dayjs(filterForm.dateRange[0]).startOf('day').toISOString()
      params.end_time = dayjs(filterForm.dateRange[1]).endOf('day').toISOString()
    }
    if (filterForm.event_type) {
      params.event_type = filterForm.event_type
    }
    const res = await auditAPI.exportLogs(params)
    if (res.data?.url) {
      window.open(res.data.url, '_blank')
      message.success('导出成功')
    } else {
      message.success('导出请求已提交')
    }
  } catch (error) {
    message.error('导出失败')
  } finally {
    exporting.value = false
  }
}
const showDetail = (record: AuditLog) => {
  currentLog.value = record
  detailVisible.value = true
}
const getSeverityColor = (severity: string) => {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL':
      return 'red'
    case 'ERROR':
      return 'red'
    case 'WARNING':
      return 'orange'
    case 'INFO':
      return 'blue'
    default:
      return 'default'
  }
}
const getSeverityText = (severity: string) => {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL':
      return '严重'
    case 'ERROR':
      return '错误'
    case 'WARNING':
      return '警告'
    case 'INFO':
      return '信息'
    default:
      return severity || '-'
  }
}
const getEventTypeColor = (eventType: string) => {
  switch (eventType?.toUpperCase()) {
    case 'AUTH':
      return 'blue'
    case 'DATA_ACCESS':
      return 'cyan'
    case 'SECURITY':
      return 'red'
    case 'CONFIG':
      return 'purple'
    case 'AUTHORIZATION':
      return 'orange'
    default:
      return 'default'
  }
}
const getEventTypeText = (eventType: string) => {
  switch (eventType?.toUpperCase()) {
    case 'AUTH':
      return '认证'
    case 'DATA_ACCESS':
      return '数据访问'
    case 'SECURITY':
      return '安全'
    case 'CONFIG':
      return '系统配置'
    case 'AUTHORIZATION':
      return '授权'
    default:
      return eventType || '-'
  }
}
onMounted(() => {
  loadLogs()
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
  padding: 16px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.t {
  font-size: 1.25rem;
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
  color: #f59e0b;
}
.s-info {
  flex: 1;
}
.s-num {
  font-size: 1.75rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.s-label {
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.filter {
  padding: 16px 24px;
  border-radius: 12px;
}
.tb {
  padding: 20px;
  border-radius: 12px;
}
</style>
 