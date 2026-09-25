<template>
  <!-- 可复用玻璃表格：统一 a-table 观感（玻璃主题），小数据量自动隐藏分页，透传全部插槽（bodyCell 等）。 -->
  <div class="glass-table">
    <a-table
      :columns="columns"
      :data-source="dataSource"
      :row-key="rowKey"
      :loading="loading"
      :pagination="resolvedPagination"
      size="small"
      v-bind="$attrs"
    >
      <template v-for="(_, name) in $slots" #[name]="slotProps">
        <slot :name="name" v-bind="slotProps || {}" />
      </template>
    </a-table>
  </div>
</template>

<script setup lang="ts">
import { computed, useSlots } from 'vue'

const props = withDefaults(
  defineProps<{
    columns: Record<string, any>[]
    dataSource: any[]
    rowKey?: string
    loading?: boolean
    pageSize?: number
  }>(),
  { rowKey: 'id', loading: false, pageSize: 10 },
)

// 数据量 ≤ pageSize 时隐藏分页器（避免单行也带分页噪音）。
const resolvedPagination = computed(() =>
  props.dataSource.length > props.pageSize ? { pageSize: props.pageSize } : false,
)

// 触发类型检查感知 $slots 使用（模板已透传全部具名插槽）
useSlots()
</script>

<style scoped>
.glass-table :deep(.ant-table) {
  background: transparent;
  color: var(--nr-text-primary);
}
.glass-table :deep(.ant-table-thead > tr > th) {
  background: rgba(255, 255, 255, 0.04);
  color: var(--nr-text-secondary);
  border-bottom: 1px solid var(--nr-glass-border, rgba(255, 255, 255, 0.08));
  font-weight: 600;
}
.glass-table :deep(.ant-table-tbody > tr > td) {
  border-bottom: 1px solid var(--nr-glass-border, rgba(255, 255, 255, 0.06));
  color: var(--nr-text-primary);
}
.glass-table :deep(.ant-table-tbody > tr:hover > td) {
  background: rgba(99, 102, 241, 0.06);
}
.glass-table :deep(.ant-table-placeholder .ant-table-cell) {
  background: transparent;
  color: var(--nr-text-tertiary);
}
.glass-table :deep(.ant-pagination) {
  color: var(--nr-text-secondary);
}
</style>
