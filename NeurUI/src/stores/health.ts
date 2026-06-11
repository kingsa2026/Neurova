import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getHealthStatus, getHealthChecks, getHealthReport } from '@/api/modules/health'
import type { HealthStatus, HealthCheck, HealthReport } from '@/api/modules/health'

/**
 * Global health monitoring store.
 * Used by the health page and layout status indicator.
 */
export const useHealthStore = defineStore('health', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const status = ref<HealthStatus | null>(null)
  const checks = ref<HealthCheck[]>([])
  const report = ref<HealthReport | null>(null)
  const loading = ref(false)
  const lastUpdated = ref<string | null>(null)

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------
  const isHealthy = computed(() => status.value?.status === 'healthy')
  const isDegraded = computed(() => status.value?.status === 'degraded')
  const overallStatus = computed(() => status.value?.status || 'unknown')

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  async function fetchStatus() {
    try {
      const res = await getHealthStatus()
      status.value = res.data
      lastUpdated.value = new Date().toISOString()
    } catch (e) {
      console.error('[HealthStore] fetchStatus failed', e)
    }
  }

  async function fetchChecks() {
    loading.value = true
    try {
      const res = await getHealthChecks()
      checks.value = res.data
    } catch (e) {
      console.error('[HealthStore] fetchChecks failed', e)
    } finally {
      loading.value = false
    }
  }

  async function fetchReport() {
    loading.value = true
    try {
      const res = await getHealthReport()
      report.value = res.data
      checks.value = res.data.checks
      status.value = {
        status: res.data.overall,
        version: res.data.version,
        uptime_seconds: 0,
        timestamp: res.data.timestamp,
      }
      lastUpdated.value = new Date().toISOString()
    } catch (e) {
      console.error('[HealthStore] fetchReport failed', e)
    } finally {
      loading.value = false
    }
  }

  return {
    status,
    checks,
    report,
    loading,
    lastUpdated,
    isHealthy,
    isDegraded,
    overallStatus,
    fetchStatus,
    fetchChecks,
    fetchReport,
  }
})
