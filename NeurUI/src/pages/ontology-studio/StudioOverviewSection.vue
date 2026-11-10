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
        <p v-if="cqRows === null" class="block-note" data-testid="overview-cq-error">
          {{ t('ontology.cqLoadFailed') }}
        </p>
        <p v-else class="block-line" data-testid="overview-cq-rate">
          {{ t('ontology.cqPassRate') }}: {{ cqImplemented }} / {{ cqRows.length }}
        </p>
        <p class="block-note">{{ t('ontology.cqReadoutNote') }}</p>
      </div>
      <div class="panel-block">
        <h4 class="block-title">{{ t('ontology.releaseStatus') }}</h4>
        <p class="block-line">{{ t('ontology.releaseBaselineHint') }}</p>
        <p class="block-note">{{ t('ontology.releaseAdminOnly') }}</p>
      </div>
    </div>

    <!-- G5 领域包：可选领域词汇的导入入口（admin）；导入只补缺幂等 -->
    <div class="panel-row">
      <div class="panel-block" data-testid="overview-domain-packs">
        <h4 class="block-title">{{ t('ontology.domainPackTitle') }}</h4>
        <p v-for="pack in packs" :key="pack.packId" class="block-line">
          {{ pack.packId }}（{{ pack.termCount }}）— {{ pack.basedOn }}
          <a-button
            v-if="isAdmin"
            size="sm"
            :loading="importing === pack.packId"
            data-testid="domain-pack-import"
            @click="importPack(pack.packId)"
          >{{ t('ontology.domainPackImport') }}</a-button>
        </p>
        <p class="block-note">{{ t('ontology.domainPackNote') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import type { CqRow, OntologySchemaData } from '@/types/ontology'
import { importDomainPack, listDomainPacks } from '@/api/modules/ontology'
import { ontologyErrorDetail } from '@/utils/ontologyFormat'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  schema: OntologySchemaData | null
  pendingCandidates: number
  loading: boolean
  /** cq-matrix 读数行；null = 读面失败（显式报错，不冒充「零实现」）。 */
  cqRows: CqRow[] | null
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
const cqImplemented = computed(
  () => (props.cqRows ?? []).filter((row) => row.status === 'implemented').length,
)

// G5 领域包：清单拉取 + admin 导入（只补缺幂等，导入计数如实回显）
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.currentUser?.role === 'admin')
const packs = ref<Array<{ packId: string; namespace: string; basedOn: string; termCount: number }>>([])
const importing = ref('')

async function loadPacks() {
  try {
    const res: any = await listDomainPacks()
    packs.value = res?.data ?? res ?? []
  } catch {
    packs.value = []
  }
}

async function importPack(packId: string) {
  importing.value = packId
  try {
    const res: any = await importDomainPack(packId)
    message.success(t('ontology.domainPackImported', { count: res?.data?.added ?? 0 }))
    void loadPacks()
  } catch (e) {
    const detail = ontologyErrorDetail(e)
    message.error(detail.message || t('common.error'))
  } finally {
    importing.value = ''
  }
}

onMounted(loadPacks)
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
