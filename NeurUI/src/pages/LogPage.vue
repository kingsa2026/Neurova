<template>
  <div class="log-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.logs') }}</h2>
      <div class="header-actions">
        <a-switch v-model:checked="autoRefresh" :checked-children="t('common.refresh')" :un-checked-children="t('common.off')" @change="toggleAutoRefresh" />
        <a-popconfirm :title="t('common.confirm') + '?'" @confirm="clearLogs">
          <GlassButton variant="danger" size="sm" :loading="clearing">{{ t('common.delete') }}</GlassButton>
        </a-popconfirm>
      </div>
    </div>

    <!-- Filters -->
    <GlassCard>
      <div class="filters-row">
        <a-select v-model:value="filters.level" :placeholder="t('common.type')" style="width: 150px" allow-clear>
          <a-select-option value="debug">{{ t('log.debug') }}</a-select-option>
          <a-select-option value="info">{{ t('log.info') }}</a-select-option>
          <a-select-option value="warning">{{ t('log.warning') }}</a-select-option>
          <a-select-option value="error">{{ t('log.error') }}</a-select-option>
        </a-select>
        <a-range-picker v-model:value="filters.dateRange" show-time style="width: 360px" />
        <a-input-search v-model:value="filters.keyword" :placeholder="t('common.search')" style="width: 240px" @search="fetchLogs" />
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchLogs">{{ t('common.search') }}</GlassButton>
      </div>
    </GlassCard>

    <!-- Log table -->
    <GlassCard v-if="logs.length > 0 || loading" style="margin-top: 16px">
      <a-table
        :columns="columns"
        :data-source="logs"
        :loading="loading"
        :locale="{ emptyText: '' }"
        row-key="id"
        :pagination="{ current: page, pageSize: pageSize, total: total, showSizeChanger: true, onChange: onPageChange }"
        :scroll="{ y: 500 }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'timestamp'">
            <span class="log-time">{{ formatTime(record.timestamp) }}</span>
          </template>
          <template v-if="column.key === 'level'">
            <a-tag :color="levelColor(record.level)">{{ record.level }}</a-tag>
          </template>
          <template v-if="column.key === 'message'">
            <span class="log-message">{{ record.message }}</span>
          </template>
          <template v-if="column.key === 'source'">
            <span class="log-source">{{ record.source }}</span>
          </template>
        </template>
      </a-table>
    </GlassCard>
    <GlassCard v-else style="margin-top: 16px">
      <a-empty :description="t('common.noData')" />
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { listLogs, clearLogs as clearLogsApi } from '@/api/modules/system-logs'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const clearing = ref(false)
const autoRefresh = ref(false)
const logs = ref<any[]>([])
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
let refreshTimer: ReturnType<typeof setInterval> | null = null

const filters = ref<{ level: string | undefined; dateRange: any; keyword: string }>({
  level: undefined,
  dateRange: null,
  keyword: '',
})

const columns = computed(() => [
  { title: t('common.createdAt'), key: 'timestamp', width: 180 },
  { title: t('log.level'), key: 'level', width: 100 },
  { title: t('log.message'), key: 'message', ellipsis: true },
  { title: t('log.source'), key: 'source', width: 140 },
])

const levelColor = (level: string) => {
  const map: Record<string, string> = { debug: 'default', info: 'blue', warning: 'orange', error: 'red' }
  return map[level] || 'default'
}

const formatTime = (ts: string) => {
  if (!ts) return ''
  return new Date(ts).toLocaleString()
}

const fetchLogs = async () => {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (filters.value.level) params.level = filters.value.level
    if (filters.value.keyword) params.keyword = filters.value.keyword
    if (filters.value.dateRange?.length === 2) {
      params.start = filters.value.dateRange[0].toISOString()
      params.end = filters.value.dateRange[1].toISOString()
    }
    const res = await listLogs(params)
    const data = res?.data
    logs.value = (data as any)?.items ?? (Array.isArray(data) ? data : [])
    total.value = (data as any)?.total ?? logs.value.length
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const clearLogs = async () => {
  clearing.value = true
  try {
    await clearLogsApi()
    message.success(t('common.success'))
    await fetchLogs()
  } catch {
    message.error(t('common.error'))
  } finally {
    clearing.value = false
  }
}

const onPageChange = (p: number, ps: number) => {
  page.value = p
  pageSize.value = ps
  fetchLogs()
}

const toggleAutoRefresh = () => {
  if (autoRefresh.value) {
    refreshTimer = setInterval(fetchLogs, 5000)
  } else {
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
  }
}

onMounted(fetchLogs)
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<style scoped>
.log-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; align-items: center; gap: 12px; }
.filters-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.log-time { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }
.log-message { font-size: 13px; color: var(--nr-text-secondary); word-break: break-word; }
.log-source { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }
</style>
