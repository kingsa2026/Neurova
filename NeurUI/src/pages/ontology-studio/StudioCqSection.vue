<template>
  <div class="cq-section" data-testid="studio-cq">
    <p class="cq-note" data-testid="cq-note">{{ t('ontology.cqNote') }}</p>
    <p v-if="cqRows === null" class="cq-error" data-testid="cq-load-error">
      {{ t('ontology.cqLoadFailed') }}
    </p>
    <table v-else class="cq-table" data-testid="cq-table">
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
        <tr v-for="row in cqRows" :key="row.cqId" :data-testid="`cq-row-${row.cqId}`">
          <td class="mono">{{ row.cqId }}</td>
          <td>{{ row.question }}</td>
          <td>{{ row.actor }}</td>
          <td>{{ row.priority }}</td>
          <td class="mono query-cell">{{ row.query }}</td>
          <td class="mono query-cell">{{ row.testId }}</td>
          <td>
            <a-tag :color="statusColor(row.status)" data-testid="cq-status">
              {{ statusLabel(row.status) }}
            </a-tag>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CqRow } from '@/types/ontology'

/** 行只来自服务端 cq-matrix 读数面；null = 读面失败（显式报错，不渲染假表）。 */
defineProps<{ cqRows: CqRow[] | null }>()

const { t } = useI18n()

function statusColor(status: CqRow['status']): string {
  if (status === 'implemented') return 'green'
  if (status === 'partial') return 'orange'
  return 'default'
}

function statusLabel(status: CqRow['status']): string {
  if (status === 'implemented') return t('ontology.cqStatusImplemented')
  if (status === 'partial') return t('ontology.cqStatusPartial')
  return t('ontology.cqStatusPlanned')
}
</script>

<style scoped>
.cq-note {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.cq-error {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--nr-danger, #d4380d);
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
