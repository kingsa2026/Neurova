&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;div &gt;{{ title }}&lt;/div&gt;
      &lt;div &gt;
        &lt;a-input
          v-if="searchable"
          v-model:value="searchText"
          placeholder="搜索..."
        &gt;
          &lt;template #prefix&gt;
            &lt;SearchOutlined /&gt;
          &lt;/template&gt;
        &lt;/a-input&gt;
        &lt;slot name="actions" /&gt;
      &lt;/div&gt;
    &lt;/div&gt;
    &lt;a-table
      :columns="columns"
      :data-source="filteredData"
      :loading="loading"
      :pagination="pagination"
      row-key="id"
    &gt;
      &lt;template #bodyCell="{ column, record }"&gt;
        &lt;slot :name="column.dataIndex" :record="record"&gt;
          {{ record[column.dataIndex] }}
        &lt;/slot&gt;
      &lt;/template&gt;
    &lt;/a-table&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, computed } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'
defineProps&lt;{
  title: string
  columns: Record&lt;string, unknown&gt;[]
  data: Record&lt;string, unknown&gt;[]
  loading?: boolean
  searchable?: boolean
  pagination?: { current?: number; pageSize?: number; total?: number }
}&gt;()
const searchText = ref&lt;string&gt;('')
const filteredData = computed(() =&gt; {
  // In a real implementation, this would filter data based on searchText
  return data
})
const emit = defineEmits&lt;{
  (e: 'search', value: string): void
}&gt;()
&lt;/script&gt;
&lt;style scoped&gt;
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
:deep(.custom-table .ant-table-thead &gt; tr &gt; th) {
  background: rgba(255, 255, 255, 0.05) !important;
  color: rgba(255, 255, 255, 0.8) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
:deep(.custom-table .ant-table-tbody &gt; tr &gt; td) {
  background: transparent !important;
  color: rgba(255, 255, 255, 0.8) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
:deep(.custom-table .ant-table-tbody &gt; tr:hover &gt; td) {
  background: rgba(255, 255, 255, 0.05) !important;
}
:deep(.ant-pagination) {
  color: rgba(255, 255, 255, 0.8);
}
:deep(.ant-pagination-item a) {
  color: rgba(255, 255, 255, 0.8);
}
&lt;/style&gt;
&nbsp;