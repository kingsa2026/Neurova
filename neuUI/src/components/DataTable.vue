<template>
  <div >
    <div >
      <div >{{ title }}</div>
      <div >
        <a-input
          v-if="searchable"
          v-model:value="searchText"
          placeholder="搜索..."
        >
          <template #prefix>
            <SearchOutlined />
          </template>
        </a-input>
        <slot name="actions" />
      </div>
    </div>
    <a-table
      :columns="columns"
      :data-source="filteredData"
      :loading="loading"
      :pagination="pagination"
      row-key="id"
    >
      <template #bodyCell="{ column, record }">
        <slot :name="column.dataIndex" :record="record">
          {{ record[column.dataIndex] }}
        </slot>
      </template>
    </a-table>
  </div>
</template>
<script setup lang="ts">
import { ref, computed } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'
defineProps<{
  title: string
  columns: Record<string, unknown>[]
  data: Record<string, unknown>[]
  loading?: boolean
  searchable?: boolean
  pagination?: { current?: number; pageSize?: number; total?: number }
}>()
const searchText = ref<string>('')
const filteredData = computed(() => {
  // In a real implementation, this would filter data based on searchText
  return data
})
const emit = defineEmits<{
  (e: 'search', value: string): void
}>()
</script>
<style scoped>
.data-table {
  padding: 24px;
}
.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.table-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #ffffff;
}
.table-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.table-search {
  width: 200px;
}
:deep(.custom-table) {
  background: transparent !important;
}
:deep(.custom-table .ant-table) {
  background: transparent !important;
}
:deep(.custom-table .ant-table-thead > tr > th) {
  background: rgba(255, 255, 255, 0.05) !important;
  color: rgba(255, 255, 255, 0.8) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
:deep(.custom-table .ant-table-tbody > tr > td) {
  background: transparent !important;
  color: rgba(255, 255, 255, 0.8) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
:deep(.custom-table .ant-table-tbody > tr:hover > td) {
  background: rgba(255, 255, 255, 0.05) !important;
}
:deep(.ant-pagination) {
  color: rgba(255, 255, 255, 0.8);
}
:deep(.ant-pagination-item a) {
  color: rgba(255, 255, 255, 0.8);
}
</style>
 