<template>
  <a-drawer
    :open="open"
    :title="`${t('ontology.catalogDrawerTitle')} — ${sourceId}`"
    width="720px"
    :destroy-on-close="true"
    @close="emit('close')"
  >
    <div class="catalog-toolbar">
      <a-input
        v-model:value="needle"
        size="sm"
        class="search-input"
        :placeholder="t('ontology.catalogTables')"
        data-testid="catalog-search"
        @press-enter="loadTables"
      />
      <GlassButton
        v-if="isAdmin"
        size="sm"
        variant="secondary"
        :loading="refreshing"
        data-testid="catalog-refresh"
        @click="refreshCatalog"
      >{{ t('ontology.catalogRefreshBtn') }}</GlassButton>
    </div>

    <a-spin :spinning="loading">
      <a-table
        v-if="tables.length"
        :columns="tableColumns"
        :data-source="tables"
        row-key="catalog_table_id"
        size="small"
        :pagination="tables.length > 20 ? { pageSize: 20 } : false"
        data-testid="catalog-tables"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'table_name'">
            <span class="mono table-name">{{ record.table_name }}</span>
          </template>
          <template v-else-if="column.key === 'term_id'">
            <a-tag v-if="record.term_id" color="blue" class="mono">{{ record.term_id }}</a-tag>
            <span v-else class="mono">—</span>
          </template>
          <template v-else-if="column.key === 'detail'">
            <GlassButton variant="ghost" size="sm" data-testid="catalog-detail-btn" @click="openDetail(record)">
              {{ t('ontology.catalogColumns') }}
            </GlassButton>
          </template>
        </template>
      </a-table>
      <a-empty v-else-if="!loading" :description="t('ontology.catalogEmpty')" />
    </a-spin>

    <!-- 列明细（含主外键与术语链接） -->
    <a-modal
      v-model:open="detailOpen"
      :title="detailTableName"
      width="680px"
      :footer="null"
    >
      <a-spin :spinning="detailLoading">
        <a-table
          v-if="detailColumns.length"
          :columns="columnColumns"
          :data-source="detailColumns"
          row-key="catalog_column_id"
          size="small"
          :pagination="false"
          data-testid="catalog-columns"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'column_name'">
              <span class="mono">{{ record.column_name }}</span>
            </template>
            <template v-else-if="column.key === 'flags'">
              <a-tag v-if="record.is_primary_key" color="gold" data-testid="catalog-pk-tag">
                {{ t('ontology.catalogPk') }}
              </a-tag>
              <a-tag v-if="record.is_foreign_key" color="geekblue" data-testid="catalog-fk-tag">
                {{ t('ontology.catalogFk') }} → {{ record.foreign_key_target }}
              </a-tag>
              <span v-if="!record.is_primary_key && !record.is_foreign_key" class="mono">—</span>
            </template>
            <template v-else-if="column.key === 'term_id'">
              <a-tag v-if="record.term_id" color="blue" class="mono">{{ record.term_id }}</a-tag>
              <span v-else class="mono">—</span>
            </template>
          </template>
        </a-table>
        <a-empty v-else :description="t('ontology.catalogEmpty')" />
      </a-spin>
    </a-modal>
  </a-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  getCatalogTableDetail,
  listCatalogTables,
  refreshSourceCatalog,
} from '@/api/modules/ontology'
import type { CatalogColumn, CatalogTable } from '@/types/ontology'

const props = defineProps<{ open: boolean; sourceId: string; isAdmin: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const { t } = useI18n()

const loading = ref(false)
const refreshing = ref(false)
const needle = ref('')
const tables = ref<CatalogTable[]>([])
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailTableName = ref('')
const detailColumns = ref<CatalogColumn[]>([])

const tableColumns = [
  { key: 'table_name', title: t('ontology.catalogTables'), dataIndex: 'table_name' },
  { key: 'column_count', title: t('ontology.catalogColumns'), dataIndex: 'column_count', width: 80 },
  { key: 'term_id', title: t('ontology.catalogTermLinked'), dataIndex: 'term_id' },
  { key: 'detail', title: '', width: 90 },
]
const columnColumns = [
  { key: 'column_name', title: t('ontology.catalogColumns'), dataIndex: 'column_name' },
  { key: 'data_type', title: 'type', dataIndex: 'data_type', width: 110 },
  { key: 'flags', title: '', width: 220 },
  { key: 'term_id', title: t('ontology.catalogTermLinked'), dataIndex: 'term_id' },
]

async function loadTables() {
  if (!props.sourceId) return
  loading.value = true
  try {
    const res = await listCatalogTables(props.sourceId, needle.value)
    tables.value = res.data?.items ?? []
  } catch {
    message.error(t('ontology.catalogLoadFailed'))
  } finally {
    loading.value = false
  }
}

async function openDetail(record: CatalogTable) {
  detailOpen.value = true
  detailLoading.value = true
  detailTableName.value = record.table_name
  try {
    const res = await getCatalogTableDetail(record.catalog_table_id)
    detailColumns.value = res.data?.columns ?? []
  } catch {
    message.error(t('ontology.catalogLoadFailed'))
  } finally {
    detailLoading.value = false
  }
}

async function refreshCatalog() {
  refreshing.value = true
  try {
    await refreshSourceCatalog(props.sourceId)
    message.success(t('ontology.catalogRefreshDone'))
    await loadTables()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || t('ontology.catalogLoadFailed'))
  } finally {
    refreshing.value = false
  }
}

watch(() => props.open, (open) => {
  if (open) void loadTables()
})
</script>

<style scoped>
.catalog-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.search-input {
  max-width: 260px;
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
.table-name {
  font-size: 12px;
}
</style>
