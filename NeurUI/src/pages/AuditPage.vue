<template>
  <div class="audit-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.audit') }}</h2>
      <GlassButton variant="secondary" size="sm" :loading="exporting" @click="exportAudit">{{ t('common.export') }}</GlassButton>
    </div>

    <!-- Filters -->
    <GlassCard>
      <div class="filters-row">
        <a-input v-model:value="filters.user" :placeholder="t('nav.users')" style="width: 150px" allow-clear />
        <a-select v-model:value="filters.action" :placeholder="t('common.actions')" style="width: 150px" allow-clear>
          <a-select-option value="create">Create</a-select-option>
          <a-select-option value="update">Update</a-select-option>
          <a-select-option value="delete">Delete</a-select-option>
          <a-select-option value="login">Login</a-select-option>
          <a-select-option value="logout">Logout</a-select-option>
        </a-select>
        <a-range-picker v-model:value="filters.dateRange" show-time style="width: 360px" />
        <GlassButton variant="primary" size="sm" :loading="loading" @click="fetchAudit">{{ t('common.search') }}</GlassButton>
      </div>
    </GlassCard>

    <!-- Audit statistics -->
    <div class="stats-grid" style="margin-top: 16px">
      <GlassStatCard :label="t('common.total')" :value="stats.total ?? 0" emoji="📋" />
      <GlassStatCard label="Today" :value="stats.today ?? 0" emoji="📅" />
      <GlassStatCard label="Warnings" :value="stats.warnings ?? 0" emoji="⚠️" />
    </div>

    <!-- Audit table -->
    <GlassCard style="margin-top: 16px">
      <a-table
        :columns="columns"
        :data-source="records"
        :loading="loading"
        row-key="id"
        :pagination="{ current: page, pageSize: pageSize, total, showSizeChanger: true, onChange: onPageChange }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'timestamp'">
            <span class="audit-time">{{ formatTime(record.timestamp) }}</span>
          </template>
          <template v-if="column.key === 'action'">
            <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
          </template>
          <template v-if="column.key === 'user'">
            <span class="audit-user">{{ record.user }}</span>
          </template>
          <template v-if="column.key === 'resource'">
            <span class="audit-resource">{{ record.resource }}</span>
          </template>
          <template v-if="column.key === 'details'">
            <a-tooltip v-if="record.details" :title="JSON.stringify(record.details)">
              <span class="audit-details">View</span>
            </a-tooltip>
            <span v-else class="text-muted">-</span>
          </template>
        </template>
      </a-table>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const exporting = ref(false)
const records = ref<any[]>([])
const stats = ref<Record<string, any>>({})
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)

const filters = ref<{ user: string; action: string | undefined; dateRange: any }>({
  user: '',
  action: undefined,
  dateRange: null,
})

const columns = computed(() => [
  { title: t('common.createdAt'), key: 'timestamp', width: 180 },
  { title: t('nav.users'), key: 'user', width: 120 },
  { title: t('common.actions'), key: 'action', width: 100 },
  { title: 'Resource', key: 'resource', width: 140 },
  { title: 'Details', key: 'details', width: 80 },
])

const actionColor = (action: string) => {
  const map: Record<string, string> = { create: 'green', update: 'blue', delete: 'red', login: 'cyan', logout: 'default' }
  return map[action] || 'default'
}

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const fetchAudit = async () => {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (filters.value.user) params.user = filters.value.user
    if (filters.value.action) params.action = filters.value.action
    if (filters.value.dateRange?.length === 2) {
      params.start = filters.value.dateRange[0].toISOString()
      params.end = filters.value.dateRange[1].toISOString()
    }

    const res: any = await request.get('/audit', { params })
    const data = res?.data ?? res ?? {}
    records.value = data.items ?? data.records ?? (Array.isArray(data) ? data : [])
    total.value = data.total ?? records.value.length
    stats.value = data.stats ?? { total: total.value, today: 0, warnings: 0 }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const exportAudit = async () => {
  exporting.value = true
  try {
    const res: any = await request.get('/audit/export', { responseType: 'blob' })
    const blob = new Blob([res], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'audit-export.json'
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    exporting.value = false
  }
}

const onPageChange = (p: number, ps: number) => { page.value = p; pageSize.value = ps; fetchAudit() }

onMounted(fetchAudit)
</script>

<style scoped>
.audit-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.filters-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.audit-time { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }
.audit-user { font-weight: 500; color: var(--nr-text-primary); }
.audit-resource { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-secondary); }
.audit-details { color: var(--nr-primary-light, #6366f1); cursor: pointer; font-size: 12px; }
.text-muted { color: var(--nr-text-muted); }
</style>
