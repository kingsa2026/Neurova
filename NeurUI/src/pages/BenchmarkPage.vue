<template>
  <div class="benchmark-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.benchmark') }}</h2>
      <GlassButton variant="primary" size="sm" :loading="running" @click="runBenchmark">{{ t('workflow.execute') }}</GlassButton>
    </div>

    <!-- Benchmark suites -->
    <a-spin :spinning="loading">
      <div class="suites-grid">
        <GlassCard v-for="suite in suites" :key="suite.id" variant="default">
          <template #header>
            <div class="suite-header">
              <span class="suite-name">{{ suite.name }}</span>
              <a-tag :color="suite.status === 'completed' ? 'green' : suite.status === 'running' ? 'blue' : 'default'">
                {{ suite.status || t('benchmark.idle') }}
              </a-tag>
            </div>
          </template>
          <div class="suite-body">
            <p class="suite-desc">{{ suite.description || '-' }}</p>
            <div class="suite-meta">
              <span>{{ suite.tests_count || 0 }} {{ t('benchmark.tests') }}</span>
              <span v-if="suite.last_run">{{ t('benchmark.lastRun') }}{{ formatTime(suite.last_run) }}</span>
            </div>
          </div>
          <template #footer>
            <div class="suite-actions">
              <GlassButton variant="ghost" size="sm" @click="selectSuite(suite)">{{ t('common.open') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" :loading="running" @click="runSuite(suite.id)">{{ t('workflow.execute') }}</GlassButton>
            </div>
          </template>
        </GlassCard>
      </div>
      <a-empty v-if="!suites.length && !loading" :description="t('common.noData')" />
    </a-spin>

    <!-- Results comparison table -->
    <GlassCard :title="t('benchmark.resultsComparison')" style="margin-top: 20px">
      <a-table
        :columns="resultColumns"
        :data-source="results"
        :loading="loadingResults"
        row-key="id"
        :pagination="{ pageSize: 20 }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'agent'">
            <span class="agent-name">{{ record.agent_name }}</span>
          </template>
          <template v-if="column.key === 'score'">
            <a-progress :percent="record.score ?? 0" :stroke-color="record.score >= 80 ? '#10b981' : record.score >= 50 ? '#f59e0b' : '#ef4444'" size="small" />
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="record.passed ? 'green' : 'red'">{{ record.passed ? t('benchmark.pass') : t('benchmark.fail') }}</a-tag>
          </template>
        </template>
      </a-table>
    </GlassCard>

    <!-- Per-agent results -->
    <GlassCard :title="t('benchmark.perAgentResults')" style="margin-top: 20px">
      <a-table :columns="agentResultColumns" :data-source="agentResults" row-key="agent_id" :pagination="false" size="small">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'avg_score'">
            <span class="mono">{{ record.avg_score?.toFixed(1) ?? '-' }}</span>
          </template>
        </template>
      </a-table>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const loadingResults = ref(false)
const running = ref(false)
const suites = ref<any[]>([])
const results = ref<any[]>([])
const agentResults = ref<any[]>([])
const selectedSuite = ref<any>(null)

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const resultColumns = computed(() => [
  { title: t('benchmark.agent'), key: 'agent' },
  { title: t('benchmark.test'), dataIndex: 'test_name', key: 'test_name' },
  { title: t('benchmark.score'), key: 'score', width: 180 },
  { title: t('benchmark.duration'), dataIndex: 'duration_ms', key: 'duration' },
  { title: t('common.status'), key: 'status', width: 80 },
])

const agentResultColumns = computed(() => [
  { title: t('benchmark.agent'), dataIndex: 'agent_name', key: 'agent_name' },
  { title: t('benchmark.testsRun'), dataIndex: 'tests_run', key: 'tests_run' },
  { title: t('benchmark.passed'), dataIndex: 'passed', key: 'passed' },
  { title: t('benchmark.failed'), dataIndex: 'failed', key: 'failed' },
  { title: t('benchmark.avgScore'), key: 'avg_score' },
])

const fetchSuites = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/benchmark/suites')
    // 契约：信封 {code, data:{suites}}。此前取 res?.data 得到的是 data
    // 对象 {suites,total}，v-for 遍历对象 → 无名称幽灵卡，套件名丢失。
    suites.value = res?.data?.suites ?? (Array.isArray(res?.data) ? res.data : [])
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchResults = async (suiteId?: string) => {
  loadingResults.value = true
  try {
    const params: any = {}
    if (suiteId) params.suite_id = suiteId
    const res: any = await request.get('/benchmark/results', { params })
    const data = res?.data ?? res ?? {}
    results.value = data.results ?? (Array.isArray(data) ? data : [])
    agentResults.value = data.agent_results ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingResults.value = false
  }
}

const selectSuite = (suite: any) => {
  selectedSuite.value = suite
  fetchResults(suite.id)
}

const runBenchmark = async () => {
  running.value = true
  try {
    await request.post('/benchmark/run', { suite_id: selectedSuite.value?.id })
    message.success(t('common.success'))
    await fetchResults(selectedSuite.value?.id)
  } catch {
    message.error(t('common.error'))
  } finally {
    running.value = false
  }
}

const runSuite = async (suiteId: string) => {
  running.value = true
  try {
    await request.post('/benchmark/run', { suite_id: suiteId })
    message.success(t('common.success'))
    await fetchResults(suiteId)
    await fetchSuites()
  } catch {
    message.error(t('common.error'))
  } finally {
    running.value = false
  }
}

onMounted(() => {
  fetchSuites()
  fetchResults()
})
</script>

<style scoped>
.benchmark-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.suites-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.suite-header { display: flex; justify-content: space-between; align-items: center; }
.suite-name { font-weight: 600; color: var(--nr-text-primary); }
.suite-body { display: flex; flex-direction: column; gap: 6px; }
.suite-desc { font-size: 13px; color: var(--nr-text-secondary); }
.suite-meta { display: flex; gap: 12px; font-size: 11px; color: var(--nr-text-muted); }
.suite-actions { display: flex; gap: 8px; }
.agent-name { font-weight: 500; color: var(--nr-text-primary); }
.mono { font-family: var(--nr-font-mono); font-size: 13px; }
</style>
