<template>
  <div class="overview-section" data-testid="studio-overview">
    <div class="stat-grid">
      <div class="stat-item">
        <span class="stat-value" data-testid="overview-term-count">{{ termCount }}</span>
        <span class="stat-label">{{ t('ontology.statTerms') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value" data-testid="overview-rule-count">{{ ruleCount }}</span>
        <span class="stat-label">{{ t('ontology.statRules') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value" data-testid="overview-relation-count">{{ relationCount }}</span>
        <span class="stat-label">{{ t('ontology.statRelations') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value" data-testid="overview-deprecated-count">{{ deprecatedCount }}</span>
        <span class="stat-label">{{ t('ontology.statDeprecated') }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-value" data-testid="overview-pending-count">{{ pendingCandidates }}</span>
        <span class="stat-label">{{ t('ontology.pendingCandidates') }}</span>
      </div>
    </div>

    <div class="panel-row">
      <div class="panel-block">
        <h4 class="block-title">{{ t('ontology.overviewCqHealth') }}</h4>
        <p class="block-line" data-testid="overview-cq-rate">
          {{ t('ontology.cqPassRate') }}: {{ cqImplemented }} / {{ CQ_ROWS.length }}
        </p>
        <p class="block-note">{{ t('ontology.cqStaticSource') }}</p>
      </div>
      <div class="panel-block">
        <h4 class="block-title">{{ t('ontology.releaseStatus') }}</h4>
        <p class="block-line">{{ t('ontology.releaseBaselineHint') }}</p>
        <p class="block-note">{{ t('ontology.releaseAdminOnly') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { OntologySchemaData } from '@/types/ontology'
import { CQ_ROWS } from '@/config/ontologyStatic'

const props = defineProps<{
  schema: OntologySchemaData | null
  pendingCandidates: number
  loading: boolean
}>()

const { t } = useI18n()

const termCount = computed(() => props.schema?.terms?.length ?? 0)
const ruleCount = computed(() => props.schema?.rules?.length ?? 0)
const relationCount = computed(
  () => (props.schema?.terms ?? []).filter((term) => term.kind === 'relation').length,
)
const deprecatedCount = computed(
  () => (props.schema?.terms ?? []).filter((term) => term.deprecated).length,
)
const cqImplemented = computed(() => CQ_ROWS.filter((row) => row.status === 'implemented').length)
</script>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
}
.stat-value {
  font-size: 20px;
  font-weight: 600;
}
.stat-label {
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.panel-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
}
.panel-block {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
}
.block-title {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
}
.block-line {
  margin: 0 0 6px;
  font-size: 13px;
}
.block-note {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
</style>
