<template>
  <div class="reasoning-section" data-testid="studio-reasoning">
    <a-alert
      type="info"
      show-icon
      data-testid="reasoning-note"
      :message="t('ontology.reasoningNote')"
    />
    <h4 class="section-title">{{ t('ontology.sparqlTitle') }}</h4>
    <div class="sparql-panel" data-testid="sparql-panel">
      <textarea v-model="sparqlQuery" class="sparql-input mono"
                :placeholder="t('ontology.sparqlPlaceholder')"
                data-testid="sparql-input" />
      <GlassButton size="sm" data-testid="sparql-run" @click="runSparql">
        {{ t('ontology.sparqlRun') }}
      </GlassButton>
      <div v-if="sparqlError" class="inline-error" data-testid="sparql-error">{{ sparqlError }}</div>
      <div v-if="sparqlResult" class="mono" data-testid="sparql-result">
        {{ t('ontology.sparqlRows', { count: sparqlResult.row_count }) }}
      </div>
    </div>
    <h4 class="section-title">{{ t('ontology.abduceTitle') }}</h4>
    <div class="sparql-panel" data-testid="abduce-panel">
      <a-input v-model:value="abduceForm.subject" class="mono"
               :placeholder="t('ontology.abduceSubject')" data-testid="abduce-subject" />
      <a-input v-model:value="abduceForm.predicate" class="mono"
               :placeholder="t('ontology.abducePredicate')" data-testid="abduce-predicate" />
      <a-input v-model:value="abduceForm.object" class="mono"
               :placeholder="t('ontology.abduceObject')" data-testid="abduce-object" />
      <GlassButton size="sm" data-testid="abduce-run" @click="runAbduce">
        {{ t('ontology.abduceRun') }}
      </GlassButton>
      <div v-if="abduceResult" class="mono" data-testid="abduce-result">
        {{ t('ontology.abduceSatisfied') }}: {{ abduceResult.satisfied }}
        · {{ t('ontology.abduceMissing') }}: {{ (abduceResult.missing ?? []).length }}
      </div>
    </div>
    <!-- U12：目标证明（POST /ontology/prove，反向链，严格只读） -->
    <h4 class="section-title">{{ t('ontology.proveTitle') }}</h4>
    <div class="sparql-panel" data-testid="prove-panel">
      <a-input v-model:value="proveForm.subject" class="mono"
               :placeholder="t('ontology.proveSubjectPh')" data-testid="prove-subject" />
      <a-input v-model:value="proveForm.predicate" class="mono"
               :placeholder="t('ontology.provePredicatePh')" data-testid="prove-predicate" />
      <a-input v-model:value="proveForm.object" class="mono"
               :placeholder="t('ontology.proveObjectPh')" data-testid="prove-object" />
      <GlassButton size="sm" :loading="proveLoading" data-testid="prove-run" @click="runProve">
        {{ t('ontology.proveRunBtn') }}
      </GlassButton>
      <div v-if="proveError" class="inline-error" data-testid="prove-error">{{ proveError }}</div>
      <div v-if="proveResult" class="prove-result" data-testid="prove-result">
        <p class="verdict">
          <a-tag :color="proveResult.proved ? 'green' : 'red'">
            {{ proveResult.proved ? t('ontology.proveProved') : t('ontology.proveNotProved') }}
          </a-tag>
          <span class="mono">{{ fmtTriple(proveResult.goal) }}</span>
        </p>
        <template v-if="proveRows.length">
          <h5 class="result-subtitle">{{ t('ontology.proveStepsTitle') }}</h5>
          <div class="proof-tree mono" data-testid="prove-steps">
            <div v-for="(row, index) in proveRows" :key="index" class="proof-row"
                 :style="{ paddingLeft: row.depth * 16 + 'px' }">
              <a-tag :color="row.step.kind === 'rule' ? 'blue' : 'default'">{{ row.step.kind }}</a-tag>
              <span class="mono">{{ row.step.ref }}</span>
              <span v-if="bindingText(row.step)"> binding={{ bindingText(row.step) }}</span>
            </div>
          </div>
        </template>
        <template v-if="proveResult.missing.length">
          <h5 class="result-subtitle">{{ t('ontology.proveMissingTitle') }}</h5>
          <ul class="missing-list" data-testid="prove-missing">
            <li v-for="(entry, index) in proveResult.missing" :key="index" class="mono">
              {{ fmtTriple(entry.goal) }} ({{ entry.reason }})
            </li>
          </ul>
        </template>
      </div>
    </div>
    <!-- U13：推导解释（GET /ontology/explain/{fact_id}，未知 fact_id 显式 404） -->
    <h4 class="section-title">{{ t('ontology.explainTitle') }}</h4>
    <div class="sparql-panel" data-testid="explain-panel">
      <a-input v-model:value="explainFactId" class="mono"
               :placeholder="t('ontology.explainFactPh')" data-testid="explain-fact-id" />
      <GlassButton size="sm" :loading="explainLoading" data-testid="explain-run" @click="runExplain">
        {{ t('ontology.explainRunBtn') }}
      </GlassButton>
      <div v-if="explainError" class="inline-error" data-testid="explain-error">{{ explainError }}</div>
      <div v-if="explainResult" class="prove-result" data-testid="explain-result">
        <p class="verdict">
          <span class="result-subtitle">{{ t('ontology.explainConclusionTitle') }}</span>
          <span class="mono">{{ fmtTriple(explainResult.conclusion) }}</span>
        </p>
        <template v-if="explainRows.length">
          <h5 class="result-subtitle">{{ t('ontology.proveStepsTitle') }}</h5>
          <div class="proof-tree mono" data-testid="explain-steps">
            <div v-for="(row, index) in explainRows" :key="index" class="proof-row"
                 :style="{ paddingLeft: row.depth * 16 + 'px' }">
              <a-tag :color="row.step.kind === 'rule' ? 'blue' : 'default'">{{ row.step.kind }}</a-tag>
              <span class="mono">{{ row.step.ref }}</span>
              <span v-if="row.step.triple"> {{ fmtTriple(row.step.triple) }}</span>
            </div>
          </div>
        </template>
        <template v-if="explainResult.text">
          <h5 class="result-subtitle">{{ t('ontology.explainTextTitle') }}</h5>
          <p class="explain-text" data-testid="explain-text">{{ explainResult.text }}</p>
        </template>
      </div>
    </div>
        <h4 class="section-title">{{ t('ontology.strategyTitle') }}</h4>
    <div class="strategy-panel" data-testid="strategy-panel">
      <span class="mono">{{ t('ontology.strategyCurrent') }}: <strong>{{ evalStrategy }}</strong></span>
      <!-- 求值策略是引擎缺省只读展示（rule_engine.setEvaluationStrategy 无 HTTP
           端点，本地翻转纯假交互——3.6-13 退役）；后端出策略端点后接真切换 -->
    </div>
<h4 class="section-title">{{ t('ontology.rulesCountTitle') }}</h4>
    <table class="rules-table" data-testid="rules-table">
      <thead>
        <tr>
          <th>{{ t('ontology.termId') }}</th>
          <th>{{ t('ontology.ruleHead') }}</th>
          <th>{{ t('ontology.ruleShape') }}</th>
          <th>{{ t('ontology.ruleEnabled') }}</th>
          <th>{{ t('ontology.termVersion') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="rule in rules" :key="rule.rule_id">
          <td class="mono">{{ rule.rule_id }}</td>
          <td class="mono">{{ rule.head_predicate }}</td>
          <td>{{ rule.shape || '-' }}</td>
          <td>{{ rule.enabled ? t('common.yes') : t('common.no') }}</td>
          <td>{{ rule.version }}</td>
        </tr>
        <tr v-if="!rules.length">
          <td colspan="5">
            <a-empty :description="t('ontology.rulesEmpty')" />
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import { useAuthStore } from '@/stores/auth'
import { explainFact, proveGoal, runOntologyAbduce, runOntologySparql } from '@/api/modules/ontology'
import type { ExplainFactResponse, OntologyProofStep, OntologySchemaData, ProveGoalResponse } from '@/types/ontology'

const props = defineProps<{ schema: OntologySchemaData | null }>()
const { t } = useI18n()
const authStore = useAuthStore()

const rules = computed(() => props.schema?.rules ?? [])

const isAdmin = computed(() => {
  const user = authStore.user as { role?: string } | null | undefined
  return user?.role === 'admin'
})
// 引擎缺省（knowledge/ontology/rule_engine.py EVALUATION_STRATEGIES 闭集，
// 缺省 full_replay）——无 HTTP 切换端点，只读展示不造假交互（3.6-13）。
const evalStrategy = ref('full_replay')

// W9：SPARQL 只读查询＋溯因解释树（501 not_supported 显式横幅）
const sparqlQuery = ref('')
const sparqlError = ref('')
const sparqlResult = ref<{ row_count: number; rows: Array<Record<string, unknown>> } | null>(null)
const abduceForm = ref({ subject: '', predicate: '', object: '' })
const abduceResult = ref<{ satisfied: boolean; missing: Array<unknown> } | null>(null)

async function runSparql() {
  sparqlError.value = ''
  sparqlResult.value = null
  try {
    const res = await runOntologySparql(sparqlQuery.value)
    sparqlResult.value = res.data as unknown as typeof sparqlResult.value
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    sparqlError.value = typeof detail === 'string' && detail
      ? detail : t('ontology.sparqlError')
  }
}

async function runAbduce() {
  try {
    const res = await runOntologyAbduce({
      subject_label: abduceForm.value.subject,
      predicate: abduceForm.value.predicate,
      object_term: abduceForm.value.object,
    })
    abduceResult.value = res.data as typeof abduceResult.value
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    abduceResult.value = { satisfied: false, missing: detail ? [detail] : [] }
  }
}

// ── U12/U13：目标证明与推导解释（都只读）────────────────────────────────

interface ProofRow {
  step: OntologyProofStep
  depth: number
}

const proveForm = ref({ subject: '', predicate: '', object: '' })
const proveLoading = ref(false)
const proveError = ref('')
const proveResult = ref<ProveGoalResponse | null>(null)

const explainFactId = ref('')
const explainLoading = ref(false)
const explainError = ref('')
const explainResult = ref<ExplainFactResponse | null>(null)

/** 树 → 缩进行（prove 走 sub，explain 走 steps；两键都缺就是叶子）。 */
function flattenSteps(nodes: OntologyProofStep[] | undefined, depth: number, out: ProofRow[]): void {
  for (const step of nodes ?? []) {
    out.push({ step, depth })
    const children = step.sub ?? step.steps
    if (children?.length) flattenSteps(children, depth + 1, out)
  }
}

const proveRows = computed<ProofRow[]>(() => {
  const rows: ProofRow[] = []
  flattenSteps(proveResult.value?.steps, 0, rows)
  return rows
})

const explainRows = computed<ProofRow[]>(() => {
  const rows: ProofRow[] = []
  flattenSteps(explainResult.value?.steps, 0, rows)
  return rows
})

function fmtTriple(triple: { subject: string; predicate: string; object: string } | null | undefined): string {
  if (!triple) return '-'
  return `${triple.subject} ${triple.predicate} ${triple.object}`
}

function bindingText(step: OntologyProofStep): string {
  const entries = Object.entries(step.binding ?? {})
  if (!entries.length) return ''
  return entries.map(([key, value]) => `${key}=${String(value)}`).join(',')
}

async function runProve() {
  proveLoading.value = true
  proveError.value = ''
  proveResult.value = null
  try {
    const res = await proveGoal({
      subject: proveForm.value.subject,
      predicate: proveForm.value.predicate,
      object: proveForm.value.object,
    })
    proveResult.value = (res.data ?? null) as ProveGoalResponse | null
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    proveError.value = typeof detail === 'string' && detail ? detail : t('ontology.proveError')
  } finally {
    proveLoading.value = false
  }
}

async function runExplain() {
  explainLoading.value = true
  explainError.value = ''
  explainResult.value = null
  try {
    const res = await explainFact(explainFactId.value.trim())
    explainResult.value = (res.data ?? null) as ExplainFactResponse | null
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    explainError.value = typeof detail === 'string' && detail ? detail : t('ontology.explainError')
  } finally {
    explainLoading.value = false
  }
}
</script>

<style scoped>
.section-title {
  margin: 14px 0 6px;
  font-size: 13px;
  font-weight: 600;
}
.rules-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.rules-table th,
.rules-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
.sparql-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.sparql-input {
  min-width: 320px;
  min-height: 40px;
  font-family: var(--nr-font-mono, monospace);
  font-size: 12px;
  padding: 6px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 6px;
}
.inline-error {
  width: 100%;
  color: var(--nr-error, #ef4444);
  font-size: 12px;
}
.prove-result {
  width: 100%;
  margin-top: 4px;
}
.verdict {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
}
.result-subtitle {
  margin: 6px 0 4px;
  font-size: 12px;
  font-weight: 600;
}
.proof-tree {
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
}
.proof-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
}
.missing-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
}
.explain-text {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
