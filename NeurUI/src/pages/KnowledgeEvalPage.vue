<template>
  <div class="knowledge-eval-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('knowledgeEval.title') }}</h2>
      <p class="page-subtitle">{{ t('knowledgeEval.subtitle') }}</p>
    </div>

    <a-spin :spinning="loading">
      <GlassPanel class="panel">
        <div class="panel-head">
          <span class="panel-title">{{ t('knowledgeEval.baselineTitle') }}</span>
          <a-tag v-if="baseline && baseline.measure_state !== 'unevidenced'" color="green" data-testid="baseline-state">
            {{ baseline.measure_state }}
          </a-tag>
        </div>
        <template v-if="baseline && baseline.measure_state !== 'unevidenced'">
          <a-descriptions :column="2" size="small" data-testid="baseline-readings">
            <a-descriptions-item :label="t('knowledgeEval.frozenAt')">{{ baseline.frozen_at || '-' }}</a-descriptions-item>
            <a-descriptions-item :label="t('knowledgeEval.caseCount')">{{ baseline.case_count ?? '-' }}</a-descriptions-item>
            <a-descriptions-item :label="t('knowledgeEval.topK')">{{ baseline.top_k ?? '-' }}</a-descriptions-item>
            <a-descriptions-item :label="t('knowledgeEval.recallAtK')">{{ fmtNum(baseline.readings?.recall_at_k) }}</a-descriptions-item>
            <a-descriptions-item :label="t('knowledgeEval.mrr')">{{ fmtNum(baseline.readings?.mrr) }}</a-descriptions-item>
            <a-descriptions-item :label="t('knowledgeEval.unhitRate')">{{ fmtNum(baseline.readings?.unhit_rate) }}</a-descriptions-item>
          </a-descriptions>
        </template>
        <div v-else class="unevidenced" data-testid="baseline-unevidenced">
          <p class="unevidenced-title">{{ t('knowledgeEval.unevidenced') }}</p>
          <p class="unevidenced-hint">{{ baseline?.missing_reason || t('knowledgeEval.unevidencedHint') }}</p>
        </div>
      </GlassPanel>

      <GlassPanel v-if="isAdmin" class="panel">
        <div class="panel-head">
          <span class="panel-title">{{ t('knowledgeEval.snapshotTitle') }}</span>
        </div>
        <a-spin :spinning="snapshotLoading">
          <pre class="json-pre" data-testid="snapshot-pre">{{ snapshotJson }}</pre>
        </a-spin>
      </GlassPanel>

      <GlassPanel v-if="isAdmin" class="panel">
        <div class="panel-head">
          <span class="panel-title">{{ t('knowledgeEval.compareTitle') }}</span>
        </div>
        <div class="compare-form">
          <a-input v-model:value="runA" :placeholder="t('knowledgeEval.runA')" class="compare-input" />
          <a-input v-model:value="runB" :placeholder="t('knowledgeEval.runB')" class="compare-input" />
          <a-input-number v-model:value="minCases" :min="1" class="compare-min" />
          <GlassButton :disabled="!runA || !runB || comparing" data-testid="compare-btn" @click="onCompare">
            {{ t('knowledgeEval.compareBtn') }}
          </GlassButton>
        </div>
        <p v-if="!compareResult" class="compare-empty">{{ t('knowledgeEval.compareEmpty') }}</p>
        <pre v-else class="json-pre" data-testid="compare-result">{{ compareJson }}</pre>
        <p class="admin-only">{{ t('knowledgeEval.adminOnly') }}</p>
      </GlassPanel>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import {
  compareEvaluationRuns,
  getEvaluationBaseline,
  getRetrievalMetricsSnapshot,
  type EvaluationBaseline,
} from '@/api/modules/knowledgeEval'

const { t } = useI18n()
const authStore = useAuthStore()

const loading = ref(false)
const baseline = ref<EvaluationBaseline | null>(null)

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})

const snapshotLoading = ref(false)
const snapshotData = ref<Record<string, unknown> | null>(null)
const snapshotJson = computed(() =>
  snapshotData.value ? JSON.stringify(snapshotData.value, null, 2) : '',
)

const runA = ref('')
const runB = ref('')
const minCases = ref<number>(30)
const comparing = ref(false)
const compareResult = ref<Record<string, unknown> | null>(null)
const compareJson = computed(() =>
  compareResult.value ? JSON.stringify(compareResult.value, null, 2) : '',
)

function fmtNum(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return String(Math.round(value * 1000) / 1000)
}

async function loadBaseline() {
  loading.value = true
  try {
    const res = await getEvaluationBaseline()
    // 信封契约：拦截器已统一解包，res 即 {code,message,data}
    baseline.value = (res.data ?? null) as EvaluationBaseline | null
  } catch {
    message.error(t('knowledgeEval.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function loadSnapshot() {
  if (!isAdmin.value) return
  snapshotLoading.value = true
  try {
    const res = await getRetrievalMetricsSnapshot()
    snapshotData.value = (res.data ?? null) as Record<string, unknown> | null
  } catch {
    message.error(t('knowledgeEval.loadFailed'))
  } finally {
    snapshotLoading.value = false
  }
}

async function onCompare() {
  if (!runA.value || !runB.value) return
  comparing.value = true
  try {
    const res = await compareEvaluationRuns({
      run_a: runA.value,
      run_b: runB.value,
      min_cases: minCases.value || 30,
    })
    compareResult.value = (res.data ?? null) as Record<string, unknown> | null
  } catch {
    message.error(t('knowledgeEval.loadFailed'))
  } finally {
    comparing.value = false
  }
}

onMounted(() => {
  loadBaseline()
  loadSnapshot()
})
</script>

<style scoped>
.knowledge-eval-page {
  padding: var(--nr-spacing-lg, 24px);
  color: var(--nr-text-primary);
}

.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary);
  font-size: 13px;
}

.panel {
  margin-bottom: var(--nr-spacing-lg, 24px);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.panel-title {
  font-weight: 600;
}

.unevidenced-title {
  margin: 0;
  font-weight: 600;
}

.unevidenced-hint {
  margin: 6px 0 0;
  color: var(--nr-text-secondary);
  font-size: 12px;
  white-space: pre-wrap;
}

.json-pre {
  margin: 0;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  color: var(--nr-text-primary);
  background: var(--nr-bg-inset);
  border-radius: 8px;
  padding: 12px;
}

.compare-form {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.compare-input {
  width: 260px;
}

.compare-min {
  width: 120px;
}

.compare-empty {
  margin: 10px 0 0;
  color: var(--nr-text-secondary);
  font-size: 12px;
}

.admin-only {
  margin: 10px 0 0;
  color: var(--nr-text-tertiary);
  font-size: 11px;
}
</style>
