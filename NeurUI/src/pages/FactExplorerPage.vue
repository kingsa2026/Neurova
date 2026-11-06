<template>
  <div class="fact-explorer-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('ontology.factTitle') }}</h2>
        <p class="page-subtitle">{{ t('ontology.factSubtitle') }}</p>
      </div>
    </div>

    <!-- 四动词查询条（§15.3）：query/analyze/validate/use -->
    <GlassPanel class="query-panel">
      <a-tabs v-model:active-key="activeVerb">
        <a-tab-pane key="query" :tab="t('ontology.verbQuery')">
          <div class="query-bar">
            <a-input-search
              v-model:value="queryText"
              size="sm"
              allow-clear
              class="query-input"
              data-testid="fact-query-input"
              :placeholder="t('ontology.queryPlaceholder')"
              @search="runQuery"
            />
            <a-select v-model:value="scope" size="sm" class="scope-select" data-testid="fact-scope">
              <a-select-option value="all">all</a-select-option>
              <a-select-option value="public">public</a-select-option>
              <a-select-option value="private">private</a-select-option>
              <a-select-option value="shared">shared</a-select-option>
            </a-select>
            <GlassButton size="sm" :loading="querying" data-testid="fact-query-btn" @click="runQuery">
              {{ t('ontology.searchBtn') }}
            </GlassButton>
          </div>
          <!-- 双时态：asOf 与 knownAt 两个独立控件，绝不合并成一个「时间」下拉（§15.4） -->
          <div class="bitemporal-row" data-testid="bitemporal-row">
            <label class="bt-field">
              <span>{{ t('ontology.asOfLabel') }}</span>
              <a-input v-model:value="asOf" size="sm" type="date" data-testid="fact-asof" />
            </label>
            <label class="bt-field">
              <span>{{ t('ontology.knownAtLabel') }}</span>
              <a-input v-model:value="knownAt" size="sm" type="date" data-testid="fact-knownat" />
            </label>
            <p class="bt-axis">
              {{ asOf ? t('ontology.axisValidTime') : '' }}
              {{ knownAt ? t('ontology.axisRecordedTime') : '' }}
            </p>
          </div>
        </a-tab-pane>

        <a-tab-pane key="analyze" :tab="t('ontology.verbAnalyze')">
          <div class="query-bar">
            <a-input v-model:value="analyzeText" size="sm" class="query-input" data-testid="fact-analyze-input" />
            <GlassButton size="sm" :loading="analyzing" data-testid="fact-analyze-btn" @click="runAnalyze">
              {{ t('ontology.wbRunBtn') }}
            </GlassButton>
          </div>
          <pre v-if="analyzeResult" class="result-pre" data-testid="analyze-result">{{ analyzeResultText }}</pre>
        </a-tab-pane>

        <a-tab-pane key="validate" :tab="t('ontology.verbValidate')">
          <p class="verb-hint">{{ t('ontology.wbValidateHint') }}</p>
          <a-textarea v-model:value="validateText" :rows="4" data-testid="fact-validate-input" />
          <div class="form-actions">
            <GlassButton size="sm" :loading="validating" data-testid="fact-validate-btn" @click="runValidate">
              {{ t('ontology.wbRunBtn') }}
            </GlassButton>
          </div>
          <div v-if="validateSummary" class="validate-summary" data-testid="validate-summary">
            {{ validateSummaryText }}
          </div>
          <div v-for="row in validateRows" :key="row.index" class="validate-row">
            <span class="mono validate-index">[{{ row.index }}]</span>
            <a-tag :color="row.verdict === 'violation' ? 'red' : 'green'">{{ row.verdict }}</a-tag>
            <span v-for="(finding, idx) in row.findings" :key="idx" class="finding">
              <a-tag :color="findingColor(finding.kind)" :data-testid="`finding-${finding.kind}`">
                {{ findingLabel(finding.kind) }}
              </a-tag>
              <span class="finding-msg">{{ finding.message }}</span>
            </span>
          </div>
        </a-tab-pane>

        <a-tab-pane key="use" :tab="t('ontology.verbUse')">
          <p class="verb-hint">{{ t('ontology.wbUseHint') }}</p>
          <div class="query-bar">
            <a-input v-model:value="useFactId" size="sm" class="query-input" data-testid="fact-use-input" placeholder="fact_id" />
            <a-input v-model:value="useOutcome" size="sm" class="outcome-input" data-testid="fact-use-outcome" placeholder="outcome" />
            <GlassButton size="sm" :loading="using" data-testid="fact-use-btn" @click="runUse">
              {{ t('ontology.wbRunBtn') }}
            </GlassButton>
          </div>
          <p class="verb-hint">{{ t('ontology.useAdminOnly') }}</p>
          <pre v-if="useResult" class="result-pre" data-testid="use-result">{{ useResultText }}</pre>
        </a-tab-pane>
      </a-tabs>
    </GlassPanel>

    <!-- 结果表 -->
    <GlassPanel v-if="activeVerb === 'query'">
      <p class="result-count" data-testid="fact-result-count">
        {{ t('ontology.resultCount', { n: results.length }) }}
      </p>
      <table class="facts-table" data-testid="facts-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Title</th>
            <th>Source</th>
            <th>Updated</th>
            <th>{{ t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in results" :key="item.id || item.knowledge_id" @click="openDetail(item)">
            <td class="mono">{{ item.id || item.knowledge_id }}</td>
            <td class="title-cell">{{ item.title }}</td>
            <td>{{ item.source || '-' }}</td>
            <td>{{ formatTime(item.updated_at ?? item.created_at) }}</td>
            <td>
              <a-button type="text" size="sm" @click.stop="openDetail(item)">{{ t('ontology.detailTitle') }}</a-button>
            </td>
          </tr>
          <tr v-if="!results.length && !querying">
            <td colspan="5"><a-empty :description="t('ontology.factsEmpty')" /></td>
          </tr>
        </tbody>
      </table>
    </GlassPanel>

    <!-- 事实详情：qualifiers / confidence / 来源链 / 推导标注 / 解释链 / 血缘 -->
    <a-drawer
      v-model:open="detailOpen"
      :title="t('ontology.detailTitle')"
      width="520"
      class="fact-detail-drawer"
    >
      <div v-if="detail" data-testid="fact-detail">
        <div class="detail-row">
          <span class="k">fact_id</span>
          <span class="v mono">{{ detailId }}</span>
          <a-button type="text" size="sm" data-testid="copy-iri" @click="copyIri">
            {{ t('ontology.copyIri') }}
          </a-button>
        </div>
        <div class="detail-row">
          <span class="k">{{ t('ontology.confidence') }}</span>
          <span class="v" data-testid="fact-confidence">{{ formatConfidence(detailConfidence) }}</span>
        </div>
        <div class="detail-row">
          <span class="k">{{ t('ontology.qualifiers') }}</span>
          <span class="v mono" data-testid="fact-qualifiers">{{ jsonOrDash(detailQualifiers) }}</span>
        </div>
        <div class="detail-row">
          <span class="k">{{ t('ontology.derivationTitle') }}</span>
          <span class="v">
            <a-tag v-if="derivation" :color="derivation.derived ? 'purple' : 'default'" data-testid="derivation-badge">
              {{ derivation.derived ? t('ontology.derivationDerived') : t('ontology.derivationObserved') }}
            </a-tag>
            <span v-else class="derivation-pending">-</span>
          </span>
        </div>
        <!-- 解释链：derived=true 才显示规则与前提；观察事实不伪造解释（§15.4） -->
        <div v-if="derivation && derivation.derived" class="explain-block" data-testid="explain-chain">
          <p class="explain-line">
            <span class="k">{{ t('ontology.derivationRule') }}</span>
            <span class="v mono">{{ derivation.rule_id }} ({{ derivation.rule_version }})</span>
          </p>
          <p class="explain-line">
            <span class="k">{{ t('ontology.derivationPremises') }}</span>
            <span class="v">{{ derivation.premise_count }}</span>
          </p>
          <div v-for="premise in derivation.premises" :key="premise.fact_id" class="premise-row mono">
            {{ premise.fact_id }} ← {{ premise.rule_id }}
          </div>
        </div>
        <div class="detail-row">
          <span class="k">{{ t('ontology.sources') }}</span>
          <span class="v">
            <span v-for="(src, idx) in detail.sources ?? []" :key="idx" class="source-chip">
              {{ src.source || src.source_type || '-' }}
            </span>
            <span v-if="!detail.sources?.length">-</span>
          </span>
        </div>
        <div class="detail-actions">
          <GlassButton size="sm" variant="secondary" data-testid="open-lineage" @click="lineageOpen = true">
            {{ t('ontology.lineageBtn') }}
          </GlassButton>
        </div>
      </div>
    </a-drawer>

    <!-- 血缘抽屉复用（§15.0：KnowledgeLineageDrawer 已是事实详情底座） -->
    <KnowledgeLineageDrawer v-if="detail" v-model:open="lineageOpen" :fact-id="detailId" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import KnowledgeLineageDrawer from '@/components/KnowledgeLineageDrawer.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useAuthStore } from '@/stores/auth'
import {
  accessAnalyze,
  accessQuery,
  accessUse,
  accessValidate,
  getDerivationChain,
} from '@/api/modules/ontology'
import type {
  DerivationChain,
  FactQueryBody,
  FactQueryItem,
  OntologyValidateRow,
  OntologyValidateSummary,
  ValidateTriple,
} from '@/types/ontology'
import { formatConfidence, jsonOrDash } from '@/utils/ontologyFormat'

type VerbKey = 'query' | 'analyze' | 'validate' | 'use'

const { t } = useI18n()
const { agentId } = useAgentPage()
const authStore = useAuthStore()

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})

const activeVerb = ref<VerbKey>('query')

// query
const querying = ref(false)
const queryText = ref('')
const scope = ref('all')
const asOf = ref('')
const knownAt = ref('')
const results = ref<FactQueryItem[]>([])

// analyze
const analyzing = ref(false)
const analyzeText = ref('')
const analyzeResult = ref<Record<string, unknown> | null>(null)
const analyzeResultText = computed(() =>
  analyzeResult.value ? JSON.stringify(analyzeResult.value, null, 2) : '',
)

// validate
const validating = ref(false)
const validateText = ref(JSON.stringify([
  { subjectLabel: '示例主体', predicateTermId: 'is_a', objectTerm: '示例类型' },
], null, 2))
const validateRows = ref<OntologyValidateRow[]>([])
const validateSummary = ref<OntologyValidateSummary | null>(null)
const validateSummaryText = computed(() =>
  validateSummary.value
    ? t('ontology.validateSummary')
        .replace('{t}', String(validateSummary.value.total))
        .replace('{p}', String(validateSummary.value.passed))
        .replace('{v}', String(validateSummary.value.violated))
        .replace('{u}', String(validateSummary.value.unregistered))
    : '',
)

// use
const using = ref(false)
const useFactId = ref('')
const useOutcome = ref('adopted')
const useResult = ref<Record<string, unknown> | null>(null)
const useResultText = computed(() =>
  useResult.value ? JSON.stringify(useResult.value, null, 2) : '',
)

// detail
const detailOpen = ref(false)
const lineageOpen = ref(false)
const detail = ref<FactQueryItem | null>(null)
const derivation = ref<DerivationChain | null>(null)
const detailId = computed(() => detail.value?.id || detail.value?.knowledge_id || '')

const detailConfidence = computed(() => {
  const meta = (detail.value?.metadata ?? {}) as Record<string, unknown>
  return meta.confidence as number | null | undefined
})
const detailQualifiers = computed(() => {
  const meta = (detail.value?.metadata ?? {}) as Record<string, unknown>
  return meta.qualifier ?? meta.qualifiers ?? null
})

function findingColor(kind: string): string {
  if (kind === 'violation') return 'red'
  if (kind === 'warning') return 'gold'
  return 'default'
}

function findingLabel(kind: string): string {
  if (kind === 'violation') return t('ontology.findingViolation')
  if (kind === 'warning') return t('ontology.findingWarning')
  return t('ontology.findingInfo')
}

function formatTime(value: number | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value < 1e12 ? value * 1000 : value).toISOString().slice(0, 19).replace('T', ' ')
  } catch {
    return '-'
  }
}

async function runQuery() {
  const query = queryText.value.trim()
  if (!query) return
  querying.value = true
  try {
    const body: FactQueryBody = { query }
    if (asOf.value) body.asOf = asOf.value
    if (knownAt.value) body.knownAt = knownAt.value
    const res = await accessQuery(body, { agent_id: agentId.value || undefined, scope: scope.value })
    const payload = (res as unknown as { data?: unknown }).data ?? res
    results.value = Array.isArray(payload) ? (payload as FactQueryItem[]) : []
  } catch {
    message.error(t('ontology.queryFailed'))
  } finally {
    querying.value = false
  }
}

async function runAnalyze() {
  if (!analyzeText.value.trim()) return
  analyzing.value = true
  try {
    const res = await accessAnalyze({ query: analyzeText.value.trim() })
    analyzeResult.value = (res as unknown as { data?: Record<string, unknown> }).data
      ?? (res as unknown as Record<string, unknown>)
  } catch {
    message.error(t('ontology.queryFailed'))
  } finally {
    analyzing.value = false
  }
}

function parseTriples(text: string): ValidateTriple[] {
  const parsed = JSON.parse(text) as ValidateTriple[]
  if (!Array.isArray(parsed)) throw new Error('triples must be an array')
  return parsed.map((triple) => ({
    subjectLabel: String(triple.subjectLabel ?? ''),
    subjectKey: triple.subjectKey ? String(triple.subjectKey) : undefined,
    predicateTermId: String(triple.predicateTermId ?? ''),
    objectTerm: String(triple.objectTerm ?? ''),
    qualifier: triple.qualifier,
  }))
}

async function runValidate() {
  let triples: ValidateTriple[]
  try {
    triples = parseTriples(validateText.value)
  } catch {
    message.warning(t('ontology.invalidJson'))
    return
  }
  validating.value = true
  try {
    const res = await accessValidate({ agentId: agentId.value || undefined, triples })
    const payload = res.data ?? null
    validateRows.value = payload?.results ?? []
    validateSummary.value = payload?.summary ?? null
  } catch {
    message.error(t('ontology.queryFailed'))
  } finally {
    validating.value = false
  }
}

async function runUse() {
  const factId = useFactId.value.trim()
  if (!factId) return
  using.value = true
  try {
    const res = await accessUse(factId, { outcome: useOutcome.value.trim() || 'adopted' })
    useResult.value = (res.data ?? null) as Record<string, unknown> | null
    message.success(t('ontology.useSuccess'))
  } catch {
    message.error(t('ontology.useFailed'))
  } finally {
    using.value = false
  }
}

async function openDetail(item: FactQueryItem) {
  detail.value = item
  derivation.value = null
  detailOpen.value = true
  const factId = item.id || item.knowledge_id || ''
  if (!factId) return
  try {
    const res = await getDerivationChain(factId)
    derivation.value = (res.data ?? null) as DerivationChain | null
  } catch {
    // 404 = 事实底座没有这一行（条目型命中）：显式保持「无推导记录」，不伪造观察态
    derivation.value = null
  }
}

async function copyIri() {
  if (!detail.value) return
  const iri = `kbg:${detailId.value}`
  try {
    await navigator.clipboard.writeText(iri)
    message.success(t('ontology.copied'))
  } catch {
    // 剪贴板权限失败时回退选中提示，不静默吞掉
    message.info(iri)
  }
}
</script>

<style scoped>
.fact-explorer-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.page-title {
  margin: 0;
  font-size: 20px;
  color: var(--nr-text-primary, inherit);
}
.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary, inherit);
}
.query-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.query-input {
  flex: 1;
  min-width: 220px;
}
.scope-select {
  width: 110px;
}
.outcome-input {
  width: 140px;
}
.bitemporal-row {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  margin-top: 10px;
  flex-wrap: wrap;
}
.bt-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.bt-axis {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.bt-notice {
  margin-top: 8px;
}
.verb-hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.form-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.result-pre {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--nr-fill-tertiary, rgba(128, 128, 128, 0.08));
  font-size: 12px;
  font-family: var(--nr-font-mono, monospace);
  overflow: auto;
  max-height: 240px;
  white-space: pre-wrap;
}
.validate-summary {
  margin-top: 10px;
  font-size: 12px;
}
.validate-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 8px;
  font-size: 12px;
  flex-wrap: wrap;
}
.validate-index {
  color: var(--nr-text-secondary, inherit);
}
.finding {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}
.finding-msg {
  color: var(--nr-text-secondary, inherit);
}
.result-count {
  margin: 0 0 8px;
  font-size: 13px;
}
.facts-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.facts-table th,
.facts-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
}
.facts-table tbody tr {
  cursor: pointer;
}
.title-cell {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.detail-row .k {
  min-width: 90px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.detail-row .v {
  font-size: 13px;
  word-break: break-all;
}
.explain-block {
  margin: 10px 0;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px dashed var(--nr-border, rgba(128, 128, 128, 0.35));
}
.explain-line {
  display: flex;
  gap: 8px;
  margin: 0 0 6px;
  font-size: 12px;
}
.explain-line .k {
  color: var(--nr-text-secondary, inherit);
}
.premise-row {
  font-size: 12px;
  padding: 2px 0;
}
.source-chip {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 8px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.3));
  font-size: 12px;
}
.detail-actions {
  margin-top: 12px;
  display: flex;
  gap: 8px;
}
.mono {
  font-family: var(--nr-font-mono, monospace);
  font-size: 12px;
}
</style>
