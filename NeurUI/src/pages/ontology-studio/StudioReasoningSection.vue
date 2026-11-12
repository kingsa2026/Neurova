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
import { runOntologyAbduce, runOntologySparql } from '@/api/modules/ontology'
import type { OntologySchemaData } from '@/types/ontology'

const props = defineProps<{ schema: OntologySchemaData | null }>()
const { t } = useI18n()

const rules = computed(() => props.schema?.rules ?? [])

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
</style>
