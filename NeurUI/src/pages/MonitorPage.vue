<template>
  <div class="monitor-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('system.monitor') }}</h2>
        <p class="page-global-hint">{{ t('common.globalSettingHint') }}</p>
      </div>
      <div class="header-actions">
        <a-switch v-model:checked="autoRefresh" :checked-children="t('common.refresh')" :un-checked-children="'Off'" @change="toggleAutoRefresh" />
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchAll">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <!-- 非管理员:仅提示 -->
    <template v-if="!isAdmin">
      <div class="admin-gate">{{ t('common.adminOnlyHint') }}</div>
    </template>
    <template v-else>
    <!-- Resource usage cards -->
    <div class="stats-grid">
      <GlassStatCard :label="t('system.cpu')" :value="`${resources.cpu?.usage ?? 0}%`" emoji="🖥️" :trend="resources.cpu?.trend" :spark-data="resources.cpu?.history" />
      <GlassStatCard :label="t('system.mem')" :value="`${resources.memory?.usage ?? 0}%`" emoji="💾" :trend="resources.memory?.trend" :spark-data="resources.memory?.history" />
      <GlassStatCard :label="t('system.disk')" :value="`${resources.disk?.usage ?? 0}%`" emoji="💿" :trend="resources.disk?.trend" :spark-data="resources.disk?.history" />
    </div>

    <!-- Resource progress bars -->
    <GlassCard :title="t('system.resources')" style="margin-top: 20px">
      <div class="resource-bars">
        <div class="resource-item">
          <div class="resource-label"><span>{{ t('system.cpu') }}</span><span>{{ resources.cpu?.usage ?? 0 }}%</span></div>
          <a-progress :percent="resources.cpu?.usage ?? 0" :stroke-color="getProgressColor(resources.cpu?.usage ?? 0)" :show-info="false" />
        </div>
        <div class="resource-item">
          <div class="resource-label"><span>{{ t('system.mem') }}</span><span>{{ resources.memory?.usage ?? 0 }}%</span></div>
          <a-progress :percent="resources.memory?.usage ?? 0" :stroke-color="getProgressColor(resources.memory?.usage ?? 0)" :show-info="false" />
        </div>
        <div class="resource-item">
          <div class="resource-label"><span>{{ t('system.disk') }}</span><span>{{ resources.disk?.usage ?? 0 }}%</span></div>
          <a-progress :percent="resources.disk?.usage ?? 0" :stroke-color="getProgressColor(resources.disk?.usage ?? 0)" :show-info="false" />
        </div>
      </div>
    </GlassCard>

    <!-- Connections and Alerts side by side -->
    <div class="two-col" style="margin-top: 20px">
      <GlassCard :title="t('system.connections')">
        <a-list :data-source="connections" :loading="loading" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <div class="connection-item">
                <a-badge :status="item.status === 'connected' ? 'success' : 'error'" />
                <span class="conn-name">{{ item.name }}</span>
                <span class="conn-detail">{{ item.detail }}</span>
              </div>
            </a-list-item>
          </template>
          <template #empty><a-empty :description="t('common.noData')" /></template>
        </a-list>
      </GlassCard>

      <GlassCard :title="t('system.alerts')">
        <a-list :data-source="alerts" :loading="loading" size="small">
          <template #renderItem="{ item }">
            <a-list-item>
              <div class="alert-item">
                <a-tag :color="item.severity === 'critical' ? 'red' : item.severity === 'warning' ? 'orange' : 'blue'">{{ item.severity }}</a-tag>
                <span class="alert-msg">{{ item.message }}</span>
                <GlassButton v-if="!item.resolved" variant="ghost" size="sm" @click="resolveAlert(item.id)">
                  {{ t('common.confirm') }}
                </GlassButton>
              </div>
            </a-list-item>
          </template>
          <template #empty><a-empty :description="t('common.noData')" /></template>
        </a-list>
      </GlassCard>
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import { useAuthStore } from '@/stores/auth'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()
const authStore = useAuthStore()
/** 系统监控数据全局可见性受控; 仅管理员可访问 */
const isAdmin = computed(() => authStore.user?.role === 'admin')

const loading = ref(false)
const autoRefresh = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | null = null

const resources = ref<Record<string, any>>({ cpu: {}, memory: {}, disk: {} })
const connections = ref<any[]>([])
const alerts = ref<any[]>([])

const getProgressColor = (pct: number) => {
  if (pct >= 90) return '#ef4444'
  if (pct >= 70) return '#f59e0b'
  return '#10b981'
}

const fetchAll = async () => {
  loading.value = true
  try {
    const [resRes, connRes, alertRes]: any[] = await Promise.all([
      request.get('/monitor/resources'),
      request.get('/monitor/connections'),
      request.get('/monitor/alerts'),
    ])
    resources.value = resRes?.data ?? resRes ?? {}
    connections.value = Array.isArray(connRes?.data) ? connRes.data : Array.isArray(connRes) ? connRes : []
    alerts.value = Array.isArray(alertRes?.data) ? alertRes.data : Array.isArray(alertRes) ? alertRes : []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const resolveAlert = async (id: string) => {
  try {
    await request.put(`/monitor/alerts/${id}/resolve`)
    message.success(t('common.success'))
    await fetchAll()
  } catch {
    message.error(t('common.error'))
  }
}

const toggleAutoRefresh = () => {
  if (autoRefresh.value) {
    refreshTimer = setInterval(fetchAll, 10000)
  } else {
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
  }
}

onMounted(fetchAll)
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<style scoped>
.monitor-page { display: flex; flex-direction: column; gap: 20px; }
/* 全局说明与权限提示 */
.page-global-hint { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-secondary, #8a8a92); }
.admin-gate { margin: 24px auto; max-width: 480px; padding: 16px; border: 1px dashed var(--nr-border, rgba(255, 255, 255, 0.12)); border-radius: 10px; text-align: center; font-size: 13px; color: var(--nr-text-secondary, #8a8a92); }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; align-items: center; gap: 12px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.resource-bars { display: flex; flex-direction: column; gap: 16px; }
.resource-item { display: flex; flex-direction: column; gap: 6px; }
.resource-label { display: flex; justify-content: space-between; font-size: 13px; color: var(--nr-text-secondary); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
.connection-item { display: flex; align-items: center; gap: 8px; width: 100%; }
.conn-name { font-weight: 500; color: var(--nr-text-primary); }
.conn-detail { font-size: 12px; color: var(--nr-text-tertiary); margin-left: auto; }
.alert-item { display: flex; align-items: center; gap: 8px; width: 100%; }
.alert-msg { flex: 1; font-size: 13px; color: var(--nr-text-secondary); }
</style>
