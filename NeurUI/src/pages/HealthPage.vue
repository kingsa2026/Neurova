<template>
  <div class="health-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.health') }}</h2>
      <div class="header-actions">
        <a-tag :color="overallStatus === 'healthy' ? 'green' : overallStatus === 'degraded' ? 'orange' : 'red'" class="overall-badge">
          {{ overallStatus }}
        </a-tag>
        <GlassButton variant="primary" size="sm" :loading="reportLoading" @click="fetchReport">{{ t('system.health') }} Report</GlassButton>
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchHealth">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <!-- Overall status banner -->
    <GlassPanel :variant="overallStatus === 'healthy' ? 'subtle' : 'prominent'" :glow="overallStatus !== 'healthy'">
      <div class="status-banner">
        <span class="status-icon">{{ overallStatus === 'healthy' ? '✅' : overallStatus === 'degraded' ? '⚠️' : '❌' }}</span>
        <div class="status-text">
          <strong>{{ overallStatus === 'healthy' ? 'All Systems Operational' : overallStatus === 'degraded' ? 'Some Systems Degraded' : 'System Issues Detected' }}</strong>
          <span>{{ checks.length }} checks · {{ checks.filter(c => c.status === 'healthy').length }} healthy · {{ checks.filter(c => c.status !== 'healthy').length }} issues</span>
        </div>
      </div>
    </GlassPanel>

    <!-- Health check cards -->
    <a-spin :spinning="loading">
      <div class="checks-grid">
        <GlassCard v-for="check in checks" :key="check.name" variant="default">
          <template #header>
            <div class="check-header">
              <span class="check-name">{{ check.name }}</span>
              <a-tag :color="check.status === 'healthy' ? 'green' : check.status === 'degraded' ? 'orange' : 'red'">
                {{ check.status }}
              </a-tag>
            </div>
          </template>
          <div class="check-body">
            <p v-if="check.message" class="check-message">{{ check.message }}</p>
            <p class="check-time">Last checked: {{ formatTime(check.last_check) }}</p>
            <p v-if="check.response_time" class="check-response">Response: {{ check.response_time }}ms</p>
          </div>
          <template #footer>
            <div class="check-actions">
              <GlassButton variant="ghost" size="sm" :loading="runningCheck === check.name" @click="runCheck(check.name)">
                {{ t('common.refresh') }}
              </GlassButton>
              <GlassButton v-if="check.status !== 'healthy'" variant="danger" size="sm" @click="recover(check.name)">
                Recover
              </GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-empty v-if="!checks.length && !loading" :description="t('common.noData')" />
    </a-spin>

    <!-- Full health report modal -->
    <a-modal v-model:open="showReport" title="Health Report" :footer="null" width="640px">
      <pre class="report-content">{{ reportText }}</pre>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const reportLoading = ref(false)
const runningCheck = ref<string | null>(null)
const checks = ref<any[]>([])
const overallStatus = ref('healthy')
const showReport = ref(false)
const reportText = ref('')

const formatTime = (ts: string) => {
  if (!ts) return 'N/A'
  return new Date(ts).toLocaleString()
}

const fetchHealth = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/health')
    const data = res?.data ?? res ?? {}
    checks.value = data.checks ?? (Array.isArray(data) ? data : [])
    overallStatus.value = data.status ?? data.overall ?? (checks.value.every((c: any) => c.status === 'healthy') ? 'healthy' : 'degraded')
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchReport = async () => {
  reportLoading.value = true
  try {
    const res: any = await request.get('/health/report')
    reportText.value = JSON.stringify(res?.data ?? res, null, 2)
    showReport.value = true
  } catch {
    message.error(t('common.error'))
  } finally {
    reportLoading.value = false
  }
}

const runCheck = async (name: string) => {
  runningCheck.value = name
  try {
    await request.post(`/health/check/${name}`)
    message.success(t('common.success'))
    await fetchHealth()
  } catch {
    message.error(t('common.error'))
  } finally {
    runningCheck.value = null
  }
}

const recover = async (name: string) => {
  try {
    await request.post(`/health/recover/${name}`)
    message.success(t('common.success'))
    await fetchHealth()
  } catch {
    message.error(t('common.error'))
  }
}

onMounted(fetchHealth)
</script>

<style scoped>
.health-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.header-actions { display: flex; align-items: center; gap: 12px; }
.overall-badge { font-weight: 700; font-size: 13px; text-transform: uppercase; }
.status-banner { display: flex; align-items: center; gap: 16px; }
.status-icon { font-size: 28px; }
.status-text { display: flex; flex-direction: column; gap: 2px; }
.status-text strong { color: var(--nr-text-primary); font-size: 15px; }
.status-text span { color: var(--nr-text-tertiary); font-size: 12px; }
.checks-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.check-header { display: flex; justify-content: space-between; align-items: center; }
.check-name { font-weight: 600; color: var(--nr-text-primary); }
.check-body { display: flex; flex-direction: column; gap: 4px; }
.check-message { font-size: 13px; color: var(--nr-text-secondary); }
.check-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.check-response { font-size: 11px; color: var(--nr-text-tertiary); font-family: var(--nr-font-mono); }
.check-actions { display: flex; gap: 8px; }
.report-content { background: rgba(0,0,0,0.3); padding: 16px; border-radius: 8px; font-size: 12px; color: var(--nr-text-secondary); font-family: var(--nr-font-mono); max-height: 500px; overflow: auto; white-space: pre-wrap; margin: 0; }
</style>
