<template>
  <div class="release-section" data-testid="studio-release">
    <p v-if="!isAdmin" class="admin-note" data-testid="release-admin-note">
      {{ t('ontology.releaseAdminOnly') }}
    </p>

    <h4 class="section-title">{{ t('ontology.runTitle') }}</h4>
    <div class="run-form">
      <label class="field">
        <span>{{ t('ontology.runTermUpserts') }}</span>
        <a-textarea v-model:value="termUpsertsText" :rows="3" data-testid="run-term-upserts" />
      </label>
      <label class="field">
        <span>{{ t('ontology.runRuleRegistrations') }}</span>
        <a-textarea v-model:value="ruleRegistrationsText" :rows="3" data-testid="run-rule-registrations" />
      </label>
      <label class="field">
        <span>{{ t('ontology.runFactCandidates') }}</span>
        <a-textarea v-model:value="factCandidatesText" :rows="3" data-testid="run-fact-candidates" />
      </label>
      <label class="field">
        <span>{{ t('ontology.runReason') }}</span>
        <a-input v-model:value="reason" size="sm" data-testid="run-reason" />
      </label>
      <div class="form-actions">
        <GlassButton
          size="sm"
          :loading="running"
          :disabled="!isAdmin"
          data-testid="run-pipeline-btn"
          @click="runPipeline"
        >
          {{ t('ontology.runBtn') }}
        </GlassButton>
      </div>
      <pre v-if="runResult" class="result-pre" data-testid="run-result">{{ runResultText }}</pre>
    </div>

    <h4 class="section-title">{{ t('ontology.diffTitle') }}</h4>
    <div class="diff-form">
      <div class="diff-inputs">
        <label class="field">
          <span>{{ t('ontology.diffFrom') }}</span>
          <a-input v-model:value="diffFrom" size="sm" data-testid="diff-from" />
        </label>
        <label class="field">
          <span>{{ t('ontology.diffTo') }}</span>
          <a-input v-model:value="diffTo" size="sm" data-testid="diff-to" />
        </label>
        <GlassButton size="sm" variant="secondary" :loading="diffLoading" data-testid="diff-btn" @click="runDiff">
          {{ t('ontology.diffBtn') }}
        </GlassButton>
      </div>
      <p v-if="!diffResult" class="diff-empty" data-testid="diff-empty">{{ t('ontology.diffEmpty') }}</p>
      <div v-else class="diff-result" data-testid="diff-result">
        <div class="diff-col">
          <span class="diff-col-title">{{ t('ontology.diffAdded') }}</span>
          <pre class="result-pre">{{ sectionText(diffResult.added) }}</pre>
        </div>
        <div class="diff-col">
          <span class="diff-col-title">{{ t('ontology.diffRemoved') }}</span>
          <pre class="result-pre">{{ sectionText(diffResult.removed) }}</pre>
        </div>
        <div class="diff-col">
          <span class="diff-col-title">{{ t('ontology.diffChanged') }}</span>
          <pre class="result-pre">{{ sectionText(diffResult.changed) }}</pre>
        </div>
      </div>
    </div>

    <h4 class="section-title">{{ t('ontology.rollbackTitle') }}</h4>
    <div class="rollback-form">
      <label class="field">
        <span>toBaselineId</span>
        <a-input v-model:value="rollbackBaseline" size="sm" data-testid="rollback-baseline" />
      </label>
      <label class="field">
        <span>reason</span>
        <a-input v-model:value="rollbackReason" size="sm" data-testid="rollback-reason" />
      </label>
      <div class="form-actions">
        <GlassButton
          size="sm"
          variant="secondary"
          :loading="rollbackLoading"
          :disabled="!isAdmin"
          data-testid="rollback-btn"
          @click="rollback"
        >
          {{ t('ontology.rollbackBtn') }}
        </GlassButton>
      </div>
      <pre v-if="rollbackResult" class="result-pre" data-testid="rollback-result">{{ rollbackResult }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  getOntologyPipelineDiff,
  rollbackOntologyPipeline,
  runOntologyPipeline,
  type PipelineRunPayload,
} from '@/api/modules/ontology'
import type { PipelineDiffResponse } from '@/types/ontology'

const props = defineProps<{ isAdmin: boolean }>()
const { t } = useI18n()

const termUpsertsText = ref('[]')
const ruleRegistrationsText = ref('[]')
const factCandidatesText = ref('[]')
const reason = ref('')
const running = ref(false)
const runResult = ref<Record<string, unknown> | null>(null)

const diffFrom = ref('')
const diffTo = ref('')
const diffLoading = ref(false)
const diffResult = ref<PipelineDiffResponse | null>(null)

const rollbackBaseline = ref('')
const rollbackReason = ref('')
const rollbackLoading = ref(false)
const rollbackResult = ref('')

const runResultText = computed(() =>
  runResult.value ? JSON.stringify(runResult.value, null, 2) : '',
)

function parseArray(text: string, label: string): Array<Record<string, unknown>> {
  const trimmed = text.trim() || '[]'
  const parsed = JSON.parse(trimmed) as unknown
  if (!Array.isArray(parsed)) {
    throw new Error(label)
  }
  return parsed as Array<Record<string, unknown>>
}

async function runPipeline() {
  let payload: PipelineRunPayload
  try {
    payload = {
      termUpserts: parseArray(termUpsertsText.value, 'termUpserts'),
      ruleRegistrations: parseArray(ruleRegistrationsText.value, 'ruleRegistrations'),
      factCandidates: parseArray(factCandidatesText.value, 'factCandidates'),
      reason: reason.value.trim(),
    }
  } catch {
    message.warning(t('ontology.invalidJson'))
    return
  }
  running.value = true
  try {
    const res = await runOntologyPipeline(payload)
    runResult.value = (res.data ?? null) as unknown as Record<string, unknown> | null
    message.success(t('ontology.runSuccess'))
  } catch {
    // 400 带逐条 rejection；403 带管理员门——由拦截器/后端 detail 传达，这里显式失败不吞
    message.error(t('ontology.runFailed'))
  } finally {
    running.value = false
  }
}

async function runDiff() {
  if (!diffFrom.value.trim()) {
    message.warning(t('ontology.diffEmpty'))
    return
  }
  diffLoading.value = true
  try {
    const res = await getOntologyPipelineDiff({
      fromBaseline: diffFrom.value.trim(),
      toBaseline: diffTo.value.trim() || undefined,
    })
    diffResult.value = res.data ?? null
  } catch {
    message.error(t('common.error'))
  } finally {
    diffLoading.value = false
  }
}

function sectionText(section: unknown): string {
  return JSON.stringify(section ?? {}, null, 2)
}

async function rollback() {
  if (!rollbackBaseline.value.trim()) {
    message.warning(t('ontology.diffEmpty'))
    return
  }
  rollbackLoading.value = true
  try {
    const res = await rollbackOntologyPipeline({
      toBaselineId: rollbackBaseline.value.trim(),
      reason: rollbackReason.value.trim(),
    })
    rollbackResult.value = JSON.stringify(res.data ?? {}, null, 2)
    message.success(t('common.confirm'))
  } catch {
    message.error(t('common.error'))
  } finally {
    rollbackLoading.value = false
  }
}
</script>

<style scoped>
.admin-note {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.section-title {
  margin: 16px 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.run-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.form-actions {
  display: flex;
  gap: 8px;
}
.result-pre {
  margin: 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--nr-fill-tertiary, rgba(128, 128, 128, 0.08));
  font-size: 12px;
  font-family: var(--nr-font-mono, monospace);
  overflow: auto;
  max-height: 220px;
  white-space: pre-wrap;
}
.diff-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.diff-inputs {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.diff-inputs .field {
  min-width: 200px;
}
.diff-empty {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.diff-result {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px;
}
.diff-col-title {
  display: block;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 4px;
}
</style>
