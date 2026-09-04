<template>
  <div class="benchmark-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.benchmark') }}</h2>
      <div class="suite-toolbar">
        <a-select
          :value="effectiveAgentId"
          :options="agentOptions"
          class="agent-select"
          :aria-label="t('benchmark.agent')"
          @update:value="onAgentChange"
        />
        <GlassButton variant="primary" size="sm" :loading="running" :disabled="!selectedSuite" @click="runBenchmark">{{ t('workflow.execute') }}</GlassButton>
      </div>
    </div>

    <!-- Benchmark suites -->
    <a-spin :spinning="loading">
      <div class="suites-grid">
        <GlassCard v-for="suite in suites" :key="suite.id" variant="default">
          <template #header>
            <div class="suite-header">
              <span class="suite-name">{{ suiteLabel(suite) }}</span>
              <a-tag :color="suite.status === 'completed' ? 'green' : suite.status === 'running' ? 'blue' : 'default'">
                {{ suite.status || t('benchmark.idle') }}
              </a-tag>
            </div>
          </template>
          <div class="suite-body">
            <p class="suite-desc">{{ suiteDesc(suite) }}</p>
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
        row-key="run_id"
        :pagination="{ pageSize: 20 }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'agent'">
            <span class="agent-name">{{ record.agent_name || agentName(record.agent_id) }}</span>
          </template>
          <template v-if="column.key === 'suite_name'">
            <span>{{ suiteLabel(record) }}</span>
          </template>
          <template v-if="column.key === 'score'">
            <a-progress :percent="record.score ?? 0" :stroke-color="record.score >= 80 ? '#10b981' : record.score >= 50 ? '#f59e0b' : '#ef4444'" size="small" />
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'completed' ? 'green' : 'blue'">{{ record.status === 'completed' ? t('benchmark.pass') : (record.status || '-') }}</a-tag>
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
import { useAgentStore } from '@/stores/agents'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t, te } = useI18n()
const agentStore = useAgentStore()

// 套件名/描述多语言:后端 _SUITES 是语言中立的英文数据,展示层按 suite_id
// 映射 i18n(11 语言);未登记的 id 回落后端原值。
const suiteLabel = (suite: any) => {
  const id = suite?.id ?? suite?.suite_id ?? ''
  const key = `benchmark.suites.${id}.name`
  return te(key) ? t(key) : (suite?.name ?? id)
}
const suiteDesc = (suite: any) => {
  const key = `benchmark.suites.${suite?.id}.description`
  return te(key) ? t(key) : (suite?.description || '-')
}

const loading = ref(false)
const loadingResults = ref(false)
const running = ref(false)
const suites = ref<any[]>([])
const results = ref<any[]>([])
const selectedSuite = ref<any>(null)
const selectedAgentId = ref<string | null>(null)

// 后端按 agent 记录运行（Agent 层隔离）。未手动选择时回落当前智能体，
// 再回落首个智能体，最终兜底 'default' —— 与其余 agent 页面的默认口径一致。
const agentOptions = computed(() => agentStore.agentOptions ?? [])
const effectiveAgentId = computed(() =>
  selectedAgentId.value ?? agentStore.currentAgentId ?? agentStore.agents[0]?.id ?? 'default',
)

const onAgentChange = (value: string) => {
  selectedAgentId.value = value || null
}

const agentName = (agentId?: string) =>
  agentId ? (agentStore.agents.find((a) => a.id === agentId)?.name ?? agentId) : ''

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const resultColumns = computed(() => [
  { title: t('benchmark.agent'), key: 'agent' },
  { title: t('benchmark.test'), dataIndex: 'suite_name', key: 'suite_name' },
  { title: t('benchmark.score'), key: 'score', width: 180 },
  { title: t('benchmark.duration'), dataIndex: 'avg_latency_ms', key: 'duration' },
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
    // 契约：/results 是 /runs 的别名，result 列表在 data.items（data.results 不存在）。
    const data = res?.data ?? res ?? {}
    results.value = data.items ?? (Array.isArray(data) ? data : [])
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingResults.value = false
  }
}

// 每智能体聚合：运行记录是套件级（tasks_total/tasks_correct/score），
// 按 agent_id 汇总为测试次数/通过/失败/平均分，agent 名从 store 反查。
const agentResults = computed<any[]>(() => {
  const acc = new Map<string, { tests_run: number; passed: number; failed: number; total: number }>()
  for (const run of results.value) {
    const id = run?.agent_id || 'default'
    const cur = acc.get(id) ?? { tests_run: 0, passed: 0, failed: 0, total: 0 }
    cur.tests_run += 1
    cur.passed += run.tasks_correct ?? 0
    cur.failed += (run.tasks_total ?? 0) - (run.tasks_correct ?? 0)
    cur.total += run.score ?? 0
    acc.set(id, cur)
  }
  return [...acc.entries()].map(([id, s]) => ({
    agent_id: id,
    agent_name: agentName(id),
    tests_run: s.tests_run,
    passed: s.passed,
    failed: s.failed,
    avg_score: s.tests_run ? Math.round((s.total / s.tests_run) * 100) / 100 : 0,
  }))
})

const selectSuite = (suite: any) => {
  selectedSuite.value = suite
  fetchResults(suite.id)
}

const runBenchmark = async () => {
  // 未选套件时头部按钮已禁用；此处兜底防止程序化调用发空 payload（422）。
  if (!selectedSuite.value) return
  running.value = true
  try {
    await request.post('/benchmark/run', {
      suite_id: selectedSuite.value.id,
      agent_id: effectiveAgentId.value,
    })
    message.success(t('common.success'))
    await fetchResults(selectedSuite.value.id)
  } catch {
    message.error(t('common.error'))
  } finally {
    running.value = false
  }
}

const runSuite = async (suiteId: string) => {
  running.value = true
  try {
    await request.post('/benchmark/run', {
      suite_id: suiteId,
      agent_id: effectiveAgentId.value,
    })
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
.suite-toolbar { display: flex; gap: 8px; align-items: center; }
.agent-select { min-width: 160px; }
.agent-name { font-weight: 500; color: var(--nr-text-primary); }
.mono { font-family: var(--nr-font-mono); font-size: 13px; }
</style>
