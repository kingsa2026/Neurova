<template>
  <div class="reasoning-section" data-testid="studio-reasoning">
    <a-alert
      type="info"
      show-icon
      data-testid="reasoning-note"
      :message="t('ontology.reasoningNote')"
    />
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
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { OntologySchemaData } from '@/types/ontology'

const props = defineProps<{ schema: OntologySchemaData | null }>()
const { t } = useI18n()

const rules = computed(() => props.schema?.rules ?? [])
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
</style>
