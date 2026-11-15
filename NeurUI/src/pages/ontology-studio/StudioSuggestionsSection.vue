<template>
  <div class="suggestions-section" data-testid="studio-suggestions">
    <h4 class="section-title" data-testid="suggestions-title">{{ t('ontology.suggestionsTitle') }}</h4>

    <!-- 跑一轮：目录 → 术语/关系候选（admin；LLM/探针缺省关，与后端门控一致） -->
    <div v-if="isAdmin" class="run-toolbar" data-testid="suggestions-run-toolbar">
      <a-input
        v-model:value="sourceInput"
        size="sm"
        class="source-input"
        :placeholder="t('ontology.suggestionsSourceId')"
        data-testid="suggestions-source-input"
      />
      <a-checkbox v-model:checked="useLlm" data-testid="suggestions-use-llm">
        {{ t('ontology.suggestionsUseLlm') }}
      </a-checkbox>
      <a-checkbox v-model:checked="probe" data-testid="suggestions-probe">
        {{ t('ontology.suggestionsProbe') }}
      </a-checkbox>
      <GlassButton size="sm" :loading="running" data-testid="suggestions-run" @click="runSuggestions">
        {{ t('ontology.suggestionsRunBtn') }}
      </GlassButton>
      <GlassButton
        size="sm"
        variant="secondary"
        :loading="detecting"
        :disabled="!sourceInput.trim()"
        data-testid="suggestions-detect-families"
        @click="detectFamilies"
      >
        {{ t('ontology.suggestionsFamilyBtn') }}
      </GlassButton>
    </div>
    <p class="hint" data-testid="suggestions-source-hint">{{ t('ontology.suggestionsSourceIdHint') }}</p>

    <!-- 状态/类型过滤 + 审批列表（机器只产候选，批准/拒绝都在这里人工完成） -->
    <div class="queue-toolbar">
      <a-radio-group v-model:value="statusFilter" size="sm">
        <a-radio-button value="pending">{{ t('ontology.statusPending') }}</a-radio-button>
        <a-radio-button value="approved">{{ t('ontology.statusApproved') }}</a-radio-button>
        <a-radio-button value="rejected">{{ t('ontology.statusRejected') }}</a-radio-button>
      </a-radio-group>
      <a-radio-group v-model:value="kindFilter" size="sm">
        <a-radio-button value="">{{ t('common.all') }}</a-radio-button>
        <a-radio-button value="term">{{ t('ontology.suggestionsKindTerm') }}</a-radio-button>
        <a-radio-button value="family">{{ t('ontology.suggestionsKindFamily') }}</a-radio-button>
        <a-radio-button value="sql_pattern">{{ t('ontology.suggestionsKindPattern') }}</a-radio-button>
      </a-radio-group>
    </div>

    <a-spin :spinning="loading">
      <div class="suggestion-list" data-testid="suggestion-list">
        <div v-for="item in suggestions" :key="item.suggestion_id" class="suggestion-row">
          <div class="suggestion-main">
            <a-tag :color="kindColor(item.kind)" data-testid="suggestion-kind">
              {{ kindLabel(item.kind) }}
            </a-tag>
            <span class="suggestion-name">{{ payloadName(item) }}</span>
            <span class="mono suggestion-id">{{ item.suggestion_id }}</span>
          </div>
          <div class="suggestion-meta">
            <span class="target mono" :title="item.target">{{ item.target }}</span>
            <span v-if="item.payload?.description" class="desc" :title="item.payload.description">
              {{ item.payload.description }}
            </span>
            <span v-if="item.kind === 'family'" class="members">
              {{ t('ontology.suggestionsMembers') }}: {{ (item.payload?.members ?? []).join(', ') }}
            </span>
            <span v-if="item.kind === 'sql_pattern' && item.payload?.question" class="desc">
              {{ item.payload.question }}
            </span>
            <span class="confidence">
              {{ t('ontology.candidateConfidence') }}: {{ formatConfidence(item.confidence) }}
            </span>
            <a-tag v-if="item.status !== 'pending'" :color="item.status === 'approved' ? 'green' : 'default'">
              {{ item.status === 'approved' ? t('ontology.statusApproved') : t('ontology.statusRejected') }}
            </a-tag>
          </div>
          <div v-if="isAdmin && item.status === 'pending'" class="suggestion-actions">
            <GlassButton size="sm" data-testid="suggestion-approve" @click="decide(item, 'approve')">
              {{ t('ontology.candidateApprove') }}
            </GlassButton>
            <GlassButton size="sm" variant="danger" data-testid="suggestion-reject" @click="decide(item, 'reject')">
              {{ t('ontology.candidateReject') }}
            </GlassButton>
          </div>
        </div>
        <a-empty v-if="!suggestions.length && !loading" :description="t('ontology.suggestionsEmpty')" />
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  decideSchemaSuggestion,
  detectSchemaFamilies,
  listSchemaSuggestions,
  runSchemaSuggestions,
} from '@/api/modules/ontology'
import type { SchemaSuggestion } from '@/types/ontology'
import { formatConfidence } from '@/utils/ontologyFormat'

const props = defineProps<{ isAdmin: boolean }>()
const { t } = useI18n()

const loading = ref(false)
const running = ref(false)
const detecting = ref(false)
const sourceInput = ref('')
const useLlm = ref(false)
const probe = ref(false)
const statusFilter = ref<'pending' | 'approved' | 'rejected'>('pending')
const kindFilter = ref<'' | 'term' | 'family' | 'sql_pattern'>('')
const suggestions = ref<SchemaSuggestion[]>([])

function kindLabel(kind: string): string {
  if (kind === 'term') return t('ontology.suggestionsKindTerm')
  if (kind === 'family') return t('ontology.suggestionsKindFamily')
  if (kind === 'sql_pattern') return t('ontology.suggestionsKindPattern')
  return kind
}
function kindColor(kind: string): string {
  if (kind === 'term') return 'blue'
  if (kind === 'family') return 'purple'
  if (kind === 'sql_pattern') return 'geekblue'
  return 'default'
}
function payloadName(item: SchemaSuggestion): string {
  if (item.kind === 'term') return item.payload?.name || item.target
  if (item.kind === 'family') return item.payload?.base_name || item.target
  if (item.kind === 'sql_pattern') return item.payload?.question || item.target
  return item.target
}

async function load() {
  loading.value = true
  try {
    const res = await listSchemaSuggestions(statusFilter.value, kindFilter.value)
    suggestions.value = res.data?.items ?? []
  } catch {
    message.error(t('ontology.suggestionsLoadFailed'))
  } finally {
    loading.value = false
  }
}

async function runSuggestions() {
  running.value = true
  try {
    const res: any = await runSchemaSuggestions(sourceInput.value.trim(), useLlm.value, probe.value)
    const sources = res?.data?.sources ?? []
    const terms = sources.reduce((sum: number, s: any) => sum + (s.term_suggestions ?? 0), 0)
    const relations = sources.reduce((sum: number, s: any) => sum + (s.relation_candidates ?? 0), 0)
    message.success(`${t('ontology.suggestionsRunDone')}: ${terms} + ${relations}`)
    await load()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || t('ontology.suggestionsLoadFailed'))
  } finally {
    running.value = false
  }
}

async function detectFamilies() {
  const sourceId = sourceInput.value.trim()
  if (!sourceId) return
  detecting.value = true
  try {
    const res: any = await detectSchemaFamilies(sourceId)
    const families = res?.data?.families ?? []
    message.success(`${t('ontology.suggestionsFamilyDone')}: ${families.length}`)
    await load()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || t('ontology.suggestionsLoadFailed'))
  } finally {
    detecting.value = false
  }
}

async function decide(item: SchemaSuggestion, action: 'approve' | 'reject') {
  try {
    await decideSchemaSuggestion(item.suggestion_id, action)
    message.success(action === 'approve' ? t('ontology.candidateApprovedDone') : t('ontology.candidateRejectedDone'))
    await load()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || t('ontology.candidateActionFailed'))
  }
}

watch([statusFilter, kindFilter], load)
onMounted(load)
</script>

<style scoped>
.section-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.run-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.source-input {
  max-width: 240px;
}
.hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.queue-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.suggestion-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.suggestion-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  border-radius: 10px;
}
.suggestion-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.suggestion-name {
  font-weight: 600;
}
.suggestion-id {
  font-size: 11px;
  color: var(--nr-text-secondary, inherit);
}
.suggestion-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}
.target {
  font-size: 11px;
  color: var(--nr-text-secondary, inherit);
}
.desc {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--nr-text-secondary, inherit);
}
.members {
  color: var(--nr-text-secondary, inherit);
}
.suggestion-actions {
  display: flex;
  gap: 8px;
}
.mono {
  font-family: var(--nr-font-mono, monospace);
}
</style>
