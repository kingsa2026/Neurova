<template>
  <div class="relations-section" data-testid="studio-relations">
    <h4 class="section-title" data-testid="relation-profile-title">{{ t('ontology.relationProfileTitle') }}</h4>
    <div v-if="relationTerms.length" class="profile-list">
      <div v-for="term in pagedRelationTerms" :key="term.term_id" class="profile-row">
        <span class="term-id mono">{{ term.term_id }}</span>
        <span class="profile-tags">
          <a-tag v-if="term.inverse_of" color="geekblue">
            {{ t('ontology.inverseOf') }}: {{ term.inverse_of }}
          </a-tag>
          <a-tag v-if="term.symmetric" color="cyan">{{ t('ontology.symmetricTag') }}</a-tag>
          <a-tag v-if="term.transitive" color="purple">{{ t('ontology.transitiveTag') }}</a-tag>
          <a-tag v-if="term.cardinality === 1" color="gold" data-testid="functional-tag">
            {{ t('ontology.functionalTag') }}
          </a-tag>
        </span>
      </div>
    </div>
    <a-pagination
      v-if="relationTerms.length"
      v-model:current="profilePage"
      :page-size="20"
      :total="relationTerms.length"
      :show-size-changer="false"
      class="list-pagination"
    />
    <a-empty v-else :description="t('ontology.noRelationTerms')" />

    <h4 class="section-title" data-testid="candidate-queue-title">{{ t('ontology.candidateQueueTitle') }}</h4>
    <div class="queue-toolbar">
      <a-radio-group v-model:value="candidateStatus" size="sm">
        <a-radio-button value="pending">{{ t('ontology.statusPending') }}</a-radio-button>
        <a-radio-button value="approved">{{ t('ontology.statusApproved') }}</a-radio-button>
        <a-radio-button value="rejected">{{ t('ontology.statusRejected') }}</a-radio-button>
      </a-radio-group>
      <span v-if="!isAdmin" class="admin-note">{{ t('ontology.candidateAdminOnly') }}</span>
    </div>
    <div class="candidate-list" data-testid="candidate-list">
      <div v-for="candidate in pagedCandidates" :key="candidate.candidate_id" class="candidate-row">
        <div class="candidate-main">
          <span class="surface">{{ candidate.surface }}</span>
          <span class="mono candidate-id">{{ candidate.candidate_id }}</span>
        </div>
        <div class="candidate-meta">
          <span class="source-text" :title="candidate.source_text">{{ candidate.source_text || '-' }}</span>
          <span class="confidence">{{ t('ontology.candidateConfidence') }}: {{ formatConfidence(candidate.confidence) }}</span>
          <a-tag v-if="candidate.status !== 'pending'" :color="candidate.status === 'approved' ? 'green' : 'default'">
            {{ candidate.status === 'approved' ? t('ontology.statusApproved') : t('ontology.statusRejected') }}
          </a-tag>
          <a-tag v-if="candidate.promoted_term_id" color="blue" class="mono">
            → {{ candidate.promoted_term_id }}
          </a-tag>
        </div>
        <!-- 批准动作旁显示来源文本与置信度（§15.4：候选只人工批准，不自动升格） -->
        <div v-if="isAdmin && candidate.status === 'pending'" class="candidate-actions">
          <GlassButton size="sm" data-testid="candidate-approve" @click="approveCandidate(candidate)">
            {{ t('ontology.candidateApprove') }}
          </GlassButton>
          <GlassButton size="sm" variant="danger" data-testid="candidate-reject" @click="rejectCandidate(candidate)">
            {{ t('ontology.candidateReject') }}
          </GlassButton>
        </div>
      </div>
      <a-empty v-if="!candidates.length && !loading" :description="t('ontology.candidateEmpty')" />
    </div>
    <a-pagination
      v-if="candidates.length"
      v-model:current="candidatePage"
      :page-size="20"
      :total="candidates.length"
      :show-size-changer="false"
      class="list-pagination"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  approveRelationCandidate,
  listRelationCandidates,
  rejectRelationCandidate,
} from '@/api/modules/ontology'
import type { OntologySchemaData, RelationCandidate } from '@/types/ontology'
import { formatConfidence, jsonOrDash } from '@/utils/ontologyFormat'

const props = defineProps<{ schema: OntologySchemaData | null; isAdmin: boolean }>()
const emit = defineEmits<{ (e: 'candidates-changed'): void }>()

const { t } = useI18n()

const loading = ref(false)
const candidateStatus = ref<'pending' | 'approved' | 'rejected'>('pending')
const candidates = ref<RelationCandidate[]>([])

const relationTerms = computed(() => (props.schema?.terms ?? []).filter((term) => term.kind === 'relation'))

const profilePage = ref(1)
const pagedRelationTerms = computed(() => relationTerms.value.slice((profilePage.value - 1) * 20, profilePage.value * 20))
watch(() => relationTerms.value.length, () => { profilePage.value = 1 })
const candidatePage = ref(1)
const pagedCandidates = computed(() => candidates.value.slice((candidatePage.value - 1) * 20, candidatePage.value * 20))
watch(() => candidates.value.length, () => { candidatePage.value = 1 })

async function loadCandidates() {
  loading.value = true
  try {
    const res = await listRelationCandidates(candidateStatus.value, 100)
    candidates.value = res.data?.items ?? []
  } catch {
    message.error(t('ontology.termsLoadFailed'))
  } finally {
    loading.value = false
  }
}

async function approveCandidate(candidate: RelationCandidate) {
  try {
    await approveRelationCandidate(candidate.candidate_id)
    message.success(t('ontology.candidateApprovedDone'))
    await loadCandidates()
    emit('candidates-changed')
  } catch {
    message.error(t('ontology.candidateActionFailed'))
  }
}

async function rejectCandidate(candidate: RelationCandidate) {
  try {
    await rejectRelationCandidate(candidate.candidate_id)
    message.success(t('ontology.candidateRejectedDone'))
    await loadCandidates()
    emit('candidates-changed')
  } catch {
    message.error(t('ontology.candidateActionFailed'))
  }
}

watch(candidateStatus, loadCandidates)
onMounted(loadCandidates)
</script>

<style scoped>
.section-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.profile-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}
.profile-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  border-radius: 8px;
}
.term-id {
  font-size: 12px;
}
.profile-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.queue-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.admin-note {
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.candidate-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  border-radius: 10px;
}
.candidate-main {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.surface {
  font-weight: 600;
}
.candidate-id {
  font-size: 11px;
  color: var(--nr-text-secondary, inherit);
}
.candidate-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}
.source-text {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--nr-text-secondary, inherit);
}
.candidate-actions {
  display: flex;
  gap: 8px;
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
.list-pagination {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
</style>
