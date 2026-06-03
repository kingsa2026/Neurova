&lt;template&gt;
  &lt;div &gt;
    &lt;!-- 页面标题 --&gt;
    &lt;div &gt;
      &lt;h2 &gt;
        &lt;AuditOutlined :style="{ color: '#f59e0b' }" /&gt;
        审计日志
      &lt;/h2&gt;
      &lt;a-space&gt;
        &lt;a-button @click="handleExport" :loading="exporting"&gt;
          &lt;template #icon&gt;&lt;DownloadOutlined /&gt;&lt;/template&gt;
          导出
        &lt;/a-button&gt;
        &lt;a-button @click="loadLogs" :loading="loading"&gt;
          &lt;template #icon&gt;&lt;ReloadOutlined /&gt;&lt;/template&gt;
          刷新
        &lt;/a-button&gt;
      &lt;/a-space&gt;
    &lt;/div&gt;
    &lt;!-- 统计卡片 --&gt;
    &lt;div &gt;
      &lt;div &gt;
        &lt;div &gt;&lt;FileTextOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.total || 0 }}&lt;/div&gt;
          &lt;div &gt;总日志数&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;&lt;ExclamationCircleOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.warnings || 0 }}&lt;/div&gt;
          &lt;div &gt;警告事件&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
      &lt;div &gt;
        &lt;div &gt;&lt;CloseCircleOutlined /&gt;&lt;/div&gt;
        &lt;div &gt;
          &lt;div &gt;{{ stats.errors || 0 }}&lt;/div&gt;
          &lt;div &gt;错误事件&lt;/div&gt;
        &lt;/div&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;!-- 筛选条件 --&gt;
    &lt;div &gt;
      &lt;a-form layout="inline" :model="filterForm"&gt;
        &lt;a-form-item label="时间范围"&gt;
          &lt;a-range-picker
            v-model:value="filterForm.dateRange"
            @change="handleFilter"
          /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="事件类型"&gt;
          &lt;a-select
            v-model:value="filterForm.event_type"
            placeholder="选择事件类型"
            allow-clear
            style="width: 150px"
            @change="handleFilter"
          &gt;
            &lt;a-select-option value="AUTH"&gt;认证&lt;/a-select-option&gt;
            &lt;a-select-option value="DATA_ACCESS"&gt;数据访问&lt;/a-select-option&gt;
            &lt;a-select-option value="SECURITY"&gt;安全&lt;/a-select-option&gt;
            &lt;a-select-option value="CONFIG"&gt;系统配置&lt;/a-select-option&gt;
            &lt;a-select-option value="AUTHORIZATION"&gt;授权&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="严重性"&gt;
          &lt;a-select
            v-model:value="filterForm.severity"
            placeholder="选择严重性"
            allow-clear
            style="width: 120px"
            @change="handleFilter"
          &gt;
            &lt;a-select-option value="INFO"&gt;信息&lt;/a-select-option&gt;
            &lt;a-select-option value="WARNING"&gt;警告&lt;/a-select-option&gt;
            &lt;a-select-option value="ERROR"&gt;错误&lt;/a-select-option&gt;
            &lt;a-select-option value="CRITICAL"&gt;严重&lt;/a-select-option&gt;
          &lt;/a-select&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item label="用户"&gt;
          &lt;a-input
            v-model:value="filterForm.actor_id"
            placeholder="输入用户 ID"
            allow-clear
            style="width: 150px"
            @pressEnter="handleFilter"
          /&gt;
        &lt;/a-form-item&gt;
        &lt;a-form-item&gt;
          &lt;a-button type="primary" @click="handleFilter"&gt;
            搜索
          &lt;/a-button&gt;
          &lt;a-button style="margin-left: 8px" @click="resetFilter"&gt;
            重置
          &lt;/a-button&gt;
        &lt;/a-form-item&gt;
      &lt;/a-form&gt;
    &lt;/div&gt;
    &lt;!-- 日志列表 --&gt;
    &lt;div &gt;
      &lt;a-table
        :columns="columns"
        :data-source="logs"
        :loading="loading"
        :pagination="pagination"
        row-key="id"
        size="middle"
        :scroll="{ x: 1000 }"
        @change="handleTableChange"
      &gt;
        &lt;template #bodyCell="{ column, record }"&gt;
          &lt;template v-if="column.key === 'severity'"&gt;
            &lt;a-tag :color="getSeverityColor(record.severity)"&gt;
              {{ getSeverityText(record.severity) }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'event_type'"&gt;
            &lt;a-tag :color="getEventTypeColor(record.event_type)"&gt;
              {{ getEventTypeText(record.event_type) }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'success'"&gt;
            &lt;a-tag :color="record.success ? 'green' : 'red'"&gt;
              {{ record.success ? '成功' : '失败' }}
            &lt;/a-tag&gt;
          &lt;/template&gt;
          &lt;template v-else-if="column.key === 'action'"&gt;
            &lt;a-space&gt;
              &lt;a-button type="link" size="small" @click="showDetail(record)"&gt;
                详情
              &lt;/a-button&gt;
            &lt;/a-space&gt;
          &lt;/template&gt;
        &lt;/template&gt;
      &lt;/a-table&gt;
    &lt;/div&gt;
    &lt;!-- 详情弹窗 --&gt;
    &lt;a-modal
      v-model:open="detailVisible"
      title="日志详情"
      :footer="null"
      width="600px"
    &gt;
      &lt;a-descriptions bordered :column="1" v-if="currentLog"&gt;
        &lt;a-descriptions-item label="日志 ID"&gt;
          {{ currentLog.id }}
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="时间"&gt;
          {{ currentLog.timestamp }}
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="事件类型"&gt;
          &lt;a-tag :color="getEventTypeColor(currentLog.event_type)"&gt;
            {{ getEventTypeText(currentLog.event_type) }}
          &lt;/a-tag&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="严重性"&gt;
          &lt;a-tag :color="getSeverityColor(currentLog.severity)"&gt;
            {{ getSeverityText(currentLog.severity) }}
          &lt;/a-tag&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="用户"&gt;
          {{ currentLog.actor_id || '-' }}
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="资源类型"&gt;
          {{ currentLog.resource_type || '-' }}
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="操作结果"&gt;
          &lt;a-tag :color="currentLog.success ? 'green' : 'red'"&gt;
            {{ currentLog.success ? '成功' : '失败' }}
          &lt;/a-tag&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="描述"&gt;
          {{ currentLog.description || '-' }}
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="详情"&gt;
          &lt;pre style="white-space: pre-wrap; margin: 0"&gt;{{ currentLog.details || '无' }}&lt;/pre&gt;
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="IP地址"&gt;
          {{ currentLog.ip_address || '-' }}
        &lt;/a-descriptions-item&gt;
        &lt;a-descriptions-item label="用户代理"&gt;
          {{ currentLog.user_agent || '-' }}
        &lt;/a-descriptions-item&gt;
      &lt;/a-descriptions&gt;
    &lt;/a-modal&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
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
const currentLog = ref&lt;AuditLog | null&gt;(null)
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
  showTotal: (total: number) =&gt; `共 ${total} 条`,
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
const logs = ref&lt;AuditLog[]&gt;([])
const loadLogs = async () =&gt; {
  try {
    loading.value = true
    const params: Record&lt;string, unknown&gt; = {
      page: pagination.current,
      page_size: pagination.pageSize,
    }
    if (filterForm.dateRange &amp;&amp; filterForm.dateRange.length === 2) {
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
const handleFilter = () =&gt; {
  pagination.current = 1
  loadLogs()
}
const resetFilter = () =&gt; {
  filterForm.dateRange = []
  filterForm.event_type = undefined
  filterForm.severity = undefined
  filterForm.actor_id = undefined
  handleFilter()
}
const handleTableChange: TableProps['onChange'] = (pag) =&gt; {
  pagination.current = pag.current || 1
  pagination.pageSize = pag.pageSize || 20
  loadLogs()
}
const handleExport = async () =&gt; {
  try {
    exporting.value = true
    const params: Record&lt;string, unknown&gt; = { format: 'csv' }
    if (filterForm.dateRange &amp;&amp; filterForm.dateRange.length === 2) {
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
const showDetail = (record: AuditLog) =&gt; {
  currentLog.value = record
  detailVisible.value = true
}
const getSeverityColor = (severity: string) =&gt; {
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
const getSeverityText = (severity: string) =&gt; {
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
const getEventTypeColor = (eventType: string) =&gt; {
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
const getEventTypeText = (eventType: string) =&gt; {
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
onMounted(() =&gt; {
  loadLogs()
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
&lt;/style&gt;
&nbsp;