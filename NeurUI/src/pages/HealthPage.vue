<template>
  <div class="health-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.health') }}</h2>
      <div class="header-actions">
        <a-tag :color="overallColor" class="overall-badge">
          {{ overallStatus }}
        </a-tag>
        <GlassButton variant="primary" size="sm" :loading="reportLoading" @click="fetchReport">{{ t('health.report') }}</GlassButton>
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchHealth">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <!-- Overall status banner -->
    <GlassPanel :variant="overallStatus === 'healthy' ? 'subtle' : 'prominent'" :glow="overallStatus !== 'healthy'">
      <div class="status-banner">
        <span class="status-icon">{{ overallIcon }}</span>
        <div class="status-text">
          <strong>{{ overallText }}</strong>
          <span>{{
            t('health.checksSummary', {
              checks: checks.length,
              healthy: checks.filter((c) => c.status === 'healthy').length,
              issues: checks.filter((c) => c.status !== 'healthy').length,
            })
          }}</span>
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
              <a-tag :color="checkColor(check.status)">
                {{ check.status }}
              </a-tag>
            </div>
          </template>
          <div class="check-body">
            <p v-if="check.message" class="check-message">{{ check.message }}</p>
            <p class="check-type">{{ t('common.type') }}{{ check.check_type }}</p>
            <p class="check-response">{{ t('health.response') }}{{ check.duration }}ms</p>
          </div>
          <template #footer>
            <div class="check-actions">
              <GlassButton variant="ghost" size="sm" :loading="runningCheck === check.name" @click="runSingleCheck(check.name)">
                {{ t('common.refresh') }}
              </GlassButton>
              <!-- 恢复端点后端显式 501（未实现）：按钮置灰，不以假成功误导（P1-23） -->
              <a-tooltip :title="t('common.comingSoon')">
                <GlassButton v-if="check.status !== 'healthy'" variant="danger" size="sm" disabled>
                  {{ t('health.recover') }}
                </GlassButton>
              </a-tooltip>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-empty v-if="!checks.length && !loading" :description="t('common.noData')" />
    </a-spin>

    <!-- Full health report modal -->
    <a-modal v-model:open="showReport" :title="t('health.reportTitle')" :footer="null" width="640px">
      <pre class="report-content">{{ reportText }}</pre>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import * as healthApi from '@/api/modules/health'
import type { HealthCheck, HealthState } from '@/api/modules/health'

const { t } = useI18n()

const loading = ref(false)
const reportLoading = ref(false)
const runningCheck = ref<string | null>(null)
const checks = ref<HealthCheck[]>([])
// 初始 unknown（不是 healthy）：检查器未返回任何读数时亮绿灯就是掩盖故障
// （P1-23 的「恒 healthy 假绿」正是从这里 + [].every() 恒真共同合成的）。
const overallStatus = ref<HealthState>('unknown')
const showReport = ref(false)
const reportText = ref('')

const overallColor = computed(() =>
  overallStatus.value === 'healthy' ? 'green' : overallStatus.value === 'degraded' ? 'orange' : overallStatus.value === 'unhealthy' ? 'red' : 'default',
)
const overallIcon = computed(() =>
  overallStatus.value === 'healthy' ? '✅' : overallStatus.value === 'degraded' ? '⚠️' : overallStatus.value === 'unhealthy' ? '❌' : '❓',
)
const overallText = computed(() =>
  overallStatus.value === 'healthy'
    ? t('health.allOperational')
    : overallStatus.value === 'degraded'
      ? t('health.someDegraded')
      : overallStatus.value === 'unhealthy'
        ? t('health.systemIssues')
        : t('common.noData'),
)

const checkColor = (status: string) =>
  status === 'healthy' ? 'green' : status === 'degraded' ? 'orange' : status === 'unhealthy' ? 'red' : 'default'

const fetchHealth = async () => {
  loading.value = true
  try {
    // 拦截器已解包：拿到的是裸 CheckResultResponse[]（health.ts 类型单源）。
    // 此前读 res?.data 恒 undefined → checks=[] → [].every() 恒真 → 恒 'healthy' 假绿。
    const rows = await healthApi.getHealthChecks()
    checks.value = healthApi.normalizeHealthChecks(rows)
    overallStatus.value = healthApi.aggregateOverallStatus(checks.value)
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchReport = async () => {
  reportLoading.value = true
  try {
    const report = await healthApi.getHealthReport()
    reportText.value = JSON.stringify(report, null, 2)
    checks.value = healthApi.normalizeHealthChecks(report?.checks)
    overallStatus.value = healthApi.aggregateOverallStatus(checks.value)
    showReport.value = true
  } catch {
    message.error(t('common.error'))
  } finally {
    reportLoading.value = false
  }
}

// 手动执行单个检查：POST /health/checks/{name}/run（此前误打 /recover，后端恒 501）
const runSingleCheck = async (name: string) => {
  runningCheck.value = name
  try {
    await healthApi.runCheck(name)
    message.success(t('common.success'))
    await fetchHealth()
  } catch {
    message.error(t('common.error'))
  } finally {
    runningCheck.value = null
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
.check-type { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.check-response { font-size: 11px; color: var(--nr-text-tertiary); font-family: var(--nr-font-mono); }
.check-actions { display: flex; gap: 8px; }
.report-content { background: rgba(0,0,0,0.3); padding: 16px; border-radius: 8px; font-size: 12px; color: var(--nr-text-secondary); font-family: var(--nr-font-mono); max-height: 500px; overflow: auto; white-space: pre-wrap; margin: 0; }
</style>
