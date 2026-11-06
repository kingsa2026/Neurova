<template>
  <div class="cq-section" data-testid="studio-cq">
    <p class="cq-note" data-testid="cq-note">{{ t('ontology.cqNote') }}</p>
    <table class="cq-table" data-testid="cq-table">
      <thead>
        <tr>
          <th>{{ t('ontology.cqId') }}</th>
          <th>{{ t('ontology.cqQuestion') }}</th>
          <th>{{ t('ontology.cqActor') }}</th>
          <th>{{ t('ontology.cqPriority') }}</th>
          <th>{{ t('ontology.cqQuery') }}</th>
          <th>{{ t('ontology.cqTest') }}</th>
          <th>{{ t('ontology.cqStatus') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in CQ_ROWS" :key="row.cqId" :data-testid="`cq-row-${row.cqId}`">
          <td class="mono">{{ row.cqId }}</td>
          <td>{{ row.question }}</td>
          <td>{{ row.actor }}</td>
          <td>{{ row.priority }}</td>
          <td class="mono query-cell">{{ row.query }}</td>
          <td class="mono query-cell">{{ row.testId }}</td>
          <td>
            <a-tag :color="row.status === 'implemented' ? 'green' : 'default'" data-testid="cq-status">
              {{ row.status === 'implemented' ? t('ontology.cqStatusImplemented') : t('ontology.cqStatusPlanned') }}
            </a-tag>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { CQ_ROWS } from '@/config/ontologyStatic'

const { t } = useI18n()
</script>

<style scoped>
.cq-note {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.cq-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.cq-table th,
.cq-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  vertical-align: top;
}
.query-cell {
  max-width: 260px;
  word-break: break-all;
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
</style>
