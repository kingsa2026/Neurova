<template>
  <div class="catalog-panel" data-testid="catalog-panel">
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

    <!-- 列明细（含主外键与术语链接 + U10 列画像） -->
    <a-modal
      v-model:open="detailOpen"
      :title="detailTableName"
      width="960px"
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
          class="catalog-columns-table"
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
            <!-- U10 列画像：sample_rows=0/NULL＝未采样，显式占位不冒充 0 值 -->
            <template v-else-if="isProfileKey(column.key)">
              <span v-if="isSampled(record)" class="mono profile-value">{{ profileCellText(column.key, record) }}</span>
              <span v-else class="profile-unsampled" data-testid="catalog-unsampled">
                {{ t('ontology.catalogProfileNotSampled') }}
              </span>
            </template>
          </template>
        </a-table>
        <a-empty v-else :description="t('ontology.catalogEmpty')" />
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/**
 * P1-1 schema 目录面板（自 SourceCatalogDrawer 抽屉内容提取为内联组件，
 * 2026-11-23 目录主视图重构：抽屉退役，本面板常驻页面主体）。
 *
 * - props 与原抽屉对齐（sourceId/isAdmin）；原 close 事件是抽屉开合专用，
 *   内联面板无开合语义，不再保留（避免死事件）。
 * - 换源（sourceId 变更）＝新目录面：重置搜索词与已开列明细，等价于原
 *   抽屉 destroy-on-close 的每次全新打开。
 * - U10 列画像：后端 tableDetail SELECT * 透出 profile_* 六列；
 *   profile_sample_rows 为 0/NULL 时画像列一律显「未采样」。
 */
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  getCatalogTableDetail,
  listCatalogTables,
  refreshSourceCatalog,
} from '@/api/modules/ontology'
import type { CatalogColumn, CatalogTable } from '@/types/ontology'

const props = defineProps<{ sourceId: string; isAdmin: boolean }>()
const { t } = useI18n()

const loading = ref(false)
const refreshing = ref(false)
const needle = ref('')
const tables = ref<CatalogTable[]>([])
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailTableName = ref('')
const detailColumns = ref<CatalogColumn[]>([])

const tableColumns = computed(() => [
  { key: 'table_name', title: t('ontology.catalogTables'), dataIndex: 'table_name' },
  { key: 'column_count', title: t('ontology.catalogColumns'), dataIndex: 'column_count', width: 80 },
  { key: 'term_id', title: t('ontology.catalogTermLinked'), dataIndex: 'term_id' },
  { key: 'detail', title: '', width: 90 },
])

const PROFILE_KEYS = ['profile_distinct', 'profile_null_rate', 'profile_min', 'profile_max', 'profile_samples', 'profile_sample_rows'] as const
type ProfileKey = (typeof PROFILE_KEYS)[number]

const columnColumns = computed(() => [
  { key: 'column_name', title: t('ontology.catalogColumns'), dataIndex: 'column_name' },
  { key: 'data_type', title: t('ontology.catalogColumnType'), dataIndex: 'data_type', width: 110 },
  { key: 'flags', title: '', width: 200 },
  { key: 'term_id', title: t('ontology.catalogTermLinked'), dataIndex: 'term_id' },
  { key: 'profile_distinct', title: t('ontology.catalogProfileDistinct'), dataIndex: 'profile_distinct', width: 90 },
  { key: 'profile_null_rate', title: t('ontology.catalogProfileNullRate'), dataIndex: 'profile_null_rate', width: 90 },
  { key: 'profile_min', title: t('ontology.catalogProfileMin'), dataIndex: 'profile_min', width: 110 },
  { key: 'profile_max', title: t('ontology.catalogProfileMax'), dataIndex: 'profile_max', width: 110 },
  { key: 'profile_samples', title: t('ontology.catalogProfileSamples'), dataIndex: 'profile_samples' },
  { key: 'profile_sample_rows', title: t('ontology.catalogProfileSampleRows'), dataIndex: 'profile_sample_rows', width: 90 },
])

const isProfileKey = (key: string): key is ProfileKey =>
  (PROFILE_KEYS as readonly string[]).includes(key)

/** 未采样判据：后端对无行数据连接的源型落 sample_rows=0/NULL（不造 0 值画像） */
const isSampled = (record: CatalogColumn) => Number(record.profile_sample_rows ?? 0) > 0

const formatNullRate = (rate: number | null | undefined) =>
  rate == null ? '—' : `${(rate * 100).toFixed(2)}%`

/** profile_samples_json → ≤5 个样例的文本；损坏 JSON 按空样例处理不炸面板 */
const sampleValues = (record: CatalogColumn): string[] => {
  try {
    const parsed = JSON.parse(record.profile_samples_json ?? '[]') as unknown
    return Array.isArray(parsed) ? parsed.map((v) => String(v)).slice(0, 5) : []
  } catch {
    return []
  }
}

const profileCellText = (key: ProfileKey, record: CatalogColumn): string => {
  switch (key) {
    case 'profile_distinct': return record.profile_distinct == null ? '—' : String(record.profile_distinct)
    case 'profile_null_rate': return formatNullRate(record.profile_null_rate)
    case 'profile_min': return record.profile_min == null || record.profile_min === '' ? '—' : record.profile_min
    case 'profile_max': return record.profile_max == null || record.profile_max === '' ? '—' : record.profile_max
    case 'profile_samples': return sampleValues(record).join(', ') || '—'
    case 'profile_sample_rows': return record.profile_sample_rows == null ? '—' : String(record.profile_sample_rows)
  }
}

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

watch(() => props.sourceId, () => {
  needle.value = ''
  detailOpen.value = false
  detailColumns.value = []
  void loadTables()
}, { immediate: true })
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
.catalog-columns-table :deep(th) {
  white-space: nowrap;
}
.profile-value {
  font-size: 12px;
}
.profile-unsampled {
  font-size: 11px;
  color: var(--nr-text-muted);
}
</style>
