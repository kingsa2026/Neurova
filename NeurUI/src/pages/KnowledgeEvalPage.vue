<template>
  <div class="knowledge-eval-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('knowledgeEval.title') }}</h2>
      <p class="page-subtitle">{{ t('knowledgeEval.subtitle') }}</p>
    </div>

    <a-spin :spinning="loading">
      <!-- UI-3：CQ 通过率卡（读 cq-matrix 读数面：元数据照 specs，status 为服务端探针现值） -->
      <GlassPanel class="panel">
        <div class="panel-head">
          <span class="panel-title" data-testid="eval-cq-card-title">{{ t('ontology.evalCqCardTitle') }}</span>
        </div>
        <p v-if="cqRows === null" class="honest-note honest-note--error" data-testid="eval-cq-error">
          {{ t('ontology.cqLoadFailed') }}
        </p>
        <p v-else class="cq-rate" data-testid="eval-cq-rate">
          {{ t('ontology.evalCqRate') }}（{{ cqImplemented }} / {{ cqRows.length }}）
        </p>
        <p class="honest-note">{{ t('ontology.evalCqP1Note') }}</p>
      </GlassPanel>

      <!-- UI-3：质量卡（B13 L9 现算：GET /ontology/quality，只覆盖可计算子集） -->
      <GlassPanel class="panel">
        <div class="panel-head">
          <span class="panel-title" data-testid="eval-quality-title">{{ t('ontology.evalQualityTitle') }}</span>
          <a-tag color="default" data-testid="eval-quality-count">
            {{ quality?.term_count ?? 0 }}
          </a-tag>
        </div>
        <p class="honest-note" data-testid="eval-quality-note">{{ t('ontology.evalQualityNote') }}</p>
        <div class="quality-metrics" data-testid="eval-quality-metrics">
          <div class="metric">
            <span class="k">{{ t('ontology.evalQualityConsistency') }}</span>
            <span class="v mono">{{ fmtNum(quality?.metrics?.consistency) }}</span>
          </div>
          <div class="metric">
            <span class="k">{{ t('ontology.evalQualityConciseness') }}</span>
            <span class="v mono">{{ fmtNum(quality?.metrics?.conciseness) }}</span>
          </div>
        </div>
        <p v-if="qualityLoading" class="honest-note" data-testid="eval-quality-loading">…</p>
        <p v-else-if="qualityError" class="honest-note honest-note--error" data-testid="eval-quality-error">
          {{ t('knowledgeEval.loadFailed') }}
        </p>
        <p v-else-if="!quality?.findings?.length" class="honest-note" data-testid="eval-quality-empty">
          {{ t('ontology.evalQualityEmpty') }}
        </p>
        <template v-else>
          <h4 class="findings-title">{{ t('ontology.evalQualityFindings') }}</h4>
          <table class="matrix-table" data-testid="eval-quality-table">
            <thead>
              <tr>
                <th>kind</th>
                <th>severity</th>
                <th>target</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(finding, index) in quality?.findings ?? []" :key="`${finding.kind}-${finding.target}-${index}`"
                  :data-testid="`quality-row-${finding.kind}-${index}`">
                <td class="mono">{{ finding.kind }}</td>
                <td>
                  <a-tag :color="severityColor(finding.severity)">{{ finding.severity }}</a-tag>
                </td>
                <td class="mono">{{ finding.target }}</td>
              </tr>
            </tbody>
          </table>
        </template>
      </GlassPanel>

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

      <!-- §15.1「观测与开关」：D 组九项现值读数（管理员只读面，不提供任何写入开关）。
           行数与项名一律来自服务端名册——前端抄表那一份漏过 D-03。 -->
      <GlassPanel v-if="isAdmin" class="panel">
        <div class="panel-head">
          <span class="panel-title" data-testid="eval-matrix-title">{{ t('ontology.evalMatrixTitle') }}</span>
          <GlassButton variant="secondary" size="sm" :loading="matrixLoading" data-testid="matrix-refresh" @click="loadDefaultOffMatrix">
            {{ t('common.refresh') }}
          </GlassButton>
        </div>
        <p class="honest-note" data-testid="eval-matrix-note">{{ t('ontology.evalMatrixNote') }}</p>
        <p v-if="matrixError" class="honest-note honest-note--error" data-testid="matrix-error">
          {{ t('ontology.matrixLoadFailed') }}
        </p>
        <table v-else class="matrix-table" data-testid="eval-matrix-table">
          <thead>
            <tr>
              <th>{{ t('ontology.matrixId') }}</th>
              <th>{{ t('ontology.matrixEnv') }}</th>
              <th>{{ t('ontology.matrixDefault') }}</th>
              <th>{{ t('ontology.matrixCurrent') }}</th>
              <th>{{ t('ontology.matrixState') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in matrixRows" :key="row.flagId" :data-testid="`matrix-row-${row.flagId}`">
              <td class="matrix-id">{{ row.flagId }}</td>
              <td class="matrix-env mono">{{ row.envKey }}</td>
              <td class="mono">{{ row.declaredDefault }}</td>
              <td class="mono">{{ row.mode }}</td>
              <td>
                <a-tag :color="row.isDefault ? 'default' : 'warning'" :data-testid="`matrix-state-${row.flagId}`">
                  {{ row.isDefault ? t('ontology.matrixStateDefault') : t('ontology.matrixStateDeviation') }}
                </a-tag>
              </td>
            </tr>
          </tbody>
        </table>
      </GlassPanel>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
import { getOntologyQuality, listCqMatrix, listDefaultOffFlags } from '@/api/modules/ontology'
import { severityColor } from '@/utils/ontologyFormat'
import type { CqRow, DefaultOffReading, OntologyQualityReport } from '@/types/ontology'

const { t } = useI18n()
const authStore = useAuthStore()

const loading = ref(false)
const baseline = ref<EvaluationBaseline | null>(null)

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})

/** CQ 通过率卡读数：行来自 cq-matrix 读数面（探针现值）；null = 读面失败显式报错。 */
const cqRows = ref<CqRow[] | null>(null)
const cqImplemented = computed(
  () => (cqRows.value ?? []).filter((row) => row.status === 'implemented').length,
)

async function loadCqMatrix() {
  try {
    const res = await listCqMatrix()
    cqRows.value = res.data?.items ?? []
  } catch {
    // 读不到就显式报错——保留空表/旧行数会冒充读数
    cqRows.value = null
  }
}

const quality = ref<OntologyQualityReport | null>(null)
const qualityLoading = ref(false)
const qualityError = ref(false)

async function loadQuality() {
  qualityLoading.value = true
  qualityError.value = false
  try {
    const res = await getOntologyQuality()
    quality.value = (res.data ?? null) as OntologyQualityReport | null
  } catch {
    // 读面失败显式报错，不拿空报告冒充「零缺陷」
    qualityError.value = true
  } finally {
    qualityLoading.value = false
  }
}

const matrixRows = ref<DefaultOffReading[]>([])
const matrixLoading = ref(false)
const matrixError = ref(false)

/** 默认关读数面：项名与行数都来自服务端名册，前端不补一行也不删一行。 */
async function loadDefaultOffMatrix() {
  matrixLoading.value = true
  matrixError.value = false
  try {
    const res = await listDefaultOffFlags()
    matrixRows.value = res.data?.items ?? []
  } catch {
    // 读不到就显式报错——保留上一次行数或空表会冒充「九项全是默认态」
    matrixError.value = true
  } finally {
    matrixLoading.value = false
  }
}

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
  loadQuality()
  loadCqMatrix()
})

// 读数面是管理员面（后端 403 治理门）——非管理员不发这一枪，避免一条注定被拒的请求
watch(isAdmin, (allowed) => { if (allowed) void loadDefaultOffMatrix() }, { immediate: true })
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

.cq-rate {
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: 600;
}

.honest-note {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary);
}

.matrix-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.matrix-table th,
.matrix-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
}

.matrix-id {
  font-family: var(--nr-font-mono, monospace);
}

.matrix-env {
  word-break: break-all;
  font-family: var(--nr-font-mono, monospace);
}

.quality-metrics {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 8px 0 0;
}
.metric {
  display: flex;
  gap: 6px;
  font-size: 12px;
}
.metric .k {
  color: var(--nr-text-secondary);
}
.metric .v {
  font-family: var(--nr-font-mono, monospace);
}
.findings-title {
  margin: 12px 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
}
.honest-note--error {
  color: var(--nr-error);
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
