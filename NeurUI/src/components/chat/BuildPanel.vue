<template>
  <a-modal
    :open="open"
    :title="t('build.title')"
    width="640px"
    :footer="null"
    :mask-closable="false"
    @cancel="close"
  >
    <div class="nr-build-panel">
      <a-alert v-if="error" type="error" :message="error" show-icon closable @close="error = ''" />

      <template v-if="!session">
        <p class="nr-build-hint">{{ t('build.intro') }}</p>
        <a-textarea
          v-model:value="requestDraft"
          :rows="4"
          :placeholder="t('build.requestPlaceholder')"
        />
        <div class="nr-build-actions">
          <a-button @click="close">{{ t('common.cancel') }}</a-button>
          <a-button type="primary" :loading="loading" :disabled="!requestDraft.trim()" @click="start">
            {{ t('build.start') }}
          </a-button>
        </div>
      </template>

      <template v-else>
        <div class="nr-build-head">
          <span class="nr-build-request">{{ session.request }}</span>
          <a-tag :color="statusColor">{{ statusText }}</a-tag>
        </div>

        <div class="nr-build-checklist">
          <div
            v-for="(value, key) in session.checklist"
            :key="key"
            class="nr-build-check"
            :class="{ 'is-ok': value }"
          >
            <span class="nr-build-check-dot" />
            <span>{{ t(checkLabels[key] || 'build.checkGoal') }}</span>
          </div>
        </div>

        <div v-if="activeInteraction" class="nr-build-question">
          <div class="nr-build-q-text">{{ activeInteraction.question.question }}</div>
          <div v-if="activeInteraction.question.why" class="nr-build-q-why">
            {{ activeInteraction.question.why }}
          </div>
          <QuestionInput
            :question="activeInteraction.question"
            :answer="interactionAnswer"
            @change="onInteractionChange"
          />
        </div>

        <template v-else-if="session.status === 'clarifying'">
          <div v-for="q in currentQuestions" :key="q.id" class="nr-build-question">
            <div class="nr-build-q-text">{{ q.question }}</div>
            <div v-if="q.why" class="nr-build-q-why">{{ q.why }}</div>
            <QuestionInput :question="q" :answer="answers[q.id]" @change="(v) => onAnswerChange(q.id, v)" />
          </div>
          <a-textarea
            v-model:value="supplement"
            :rows="2"
            :placeholder="t('build.supplementPlaceholder')"
            class="nr-build-supplement"
          />
        </template>

        <div v-if="session.status === 'ready'" class="nr-build-ready">
          <p>{{ t('build.readyHint') }}</p>
          <div v-if="session.build_plan?.summary" class="nr-build-plan">
            {{ session.build_plan.summary }}
          </div>
        </div>

        <div v-if="session.status === 'approved' || session.status === 'building'" class="nr-build-ready">
          <p>{{ t('build.approvedHint') }}</p>
          <code v-if="session.batch_id">{{ session.batch_id }}</code>
        </div>

        <div class="nr-build-actions">
          <a-button @click="close">{{ t('common.close') }}</a-button>
          <template v-if="activeInteraction">
            <a-button type="primary" :loading="loading" @click="submitInteraction">
              {{ t('build.answer') }}
            </a-button>
          </template>
          <template v-else-if="session.status === 'clarifying'">
            <a-button type="primary" :loading="loading" @click="submitAnswers">
              {{ t('build.submit') }}
            </a-button>
          </template>
          <template v-else-if="session.status === 'ready'">
            <a-button type="primary" :loading="loading" @click="approve">
              {{ t('build.approve') }}
            </a-button>
          </template>
        </div>
      </template>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * BuildPanel —— 构建就绪门与过程中交互面板（N0）
 *
 * 显式入口：/build 命令或外部按钮打开；一问一答走 Build API。
 * secret 输入只提交一次，面板从不回显值；值由后端写 SecretStore。
 */
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message as uiMessage } from 'ant-design-vue'
import QuestionInput from './BuildQuestionInput.vue'
import {
  answerBuildInteraction,
  approveBuildSession,
  getBuildSession,
  startBuildSession,
  submitBuildAnswers,
  cancelBuildSession,
  type BuildAnswer,
  type BuildInteraction,
  type BuildQuestion,
  type BuildSession,
} from '@/api/modules/build'

const props = withDefaults(defineProps<{
  open: boolean
  agentId?: string
  initialRequest?: string
  interaction?: BuildInteraction | null
}>(), {
  agentId: 'default',
  initialRequest: '',
  interaction: null,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'approved', payload: { sessionId: string; request: string; batchId: string; prompt: string }): void
  (e: 'resumed', payload: { sessionId: string; request: string; prompt: string }): void
}>()

const { t } = useI18n()
const session = ref<BuildSession | null>(null)
const requestDraft = ref('')
const loading = ref(false)
const error = ref('')
const supplement = ref('')
const answers = reactive<Record<string, BuildAnswer>>({})
const interactionAnswer = ref<BuildAnswer>({ id: '', selected: [], custom: '', secret_value: '' })
const activeInteraction = ref<BuildInteraction | null>(null)

const STATUS_LABELS: Record<string, string> = {
  clarifying: 'build.statusClarifying',
  ready: 'build.statusReady',
  approved: 'build.statusApproved',
  building: 'build.statusBuilding',
  blocked: 'build.statusBlocked',
  failed: 'build.statusFailed',
}
const checkLabels: Record<string, string> = {
  goal: 'build.checkGoal',
  target: 'build.checkTarget',
  nodes: 'build.checkNodes',
  params: 'build.checkParams',
  env: 'build.checkEnv',
  permissions: 'build.checkPermissions',
  budget: 'build.checkBudget',
  safe_version: 'build.checkSafeVersion',
}
const statusText = computed(() => t(STATUS_LABELS[session.value?.status || 'clarifying'] || 'build.statusClarifying'))
const statusColor = computed(() => {
  if (session.value?.status === 'ready' || session.value?.status === 'approved') return 'green'
  if (session.value?.status === 'blocked') return 'orange'
  if (session.value?.status === 'failed') return 'red'
  return 'blue'
})
const currentQuestions = computed<BuildQuestion[]>(() => {
  const rounds = session.value?.rounds || []
  const last = rounds[rounds.length - 1]
  return last?.questions || []
})

function resetAnswers() {
  Object.keys(answers).forEach((key) => delete answers[key])
  supplement.value = ''
  interactionAnswer.value = { id: '', selected: [], custom: '', secret_value: '' }
}

function onAnswerChange(id: string, value: BuildAnswer) {
  answers[id] = value
}

function onInteractionChange(value: BuildAnswer) {
  interactionAnswer.value = value
}

async function loadInteraction() {
  if (!props.interaction) return
  const sessionId = props.interaction.build_session_id || ''
  if (!sessionId) {
    error.value = t('build.loadFailed')
    return
  }
  loading.value = true
  try {
    const res: any = await getBuildSession(sessionId)
    session.value = res?.data?.session ?? res?.session ?? null
    activeInteraction.value = props.interaction
    interactionAnswer.value = {
      id: props.interaction.question.id,
      selected: [],
      custom: '',
      secret_value: '',
    }
  } catch (err: any) {
    error.value = err?.message || t('build.loadFailed')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    error.value = ''
    resetAnswers()
    activeInteraction.value = null
    session.value = null
    requestDraft.value = props.initialRequest || ''
    if (props.interaction) {
      await loadInteraction()
    }
  },
  { immediate: true },
)

async function start() {
  const request = requestDraft.value.trim()
  if (!request || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const res: any = await startBuildSession(props.agentId, request)
    session.value = res?.data?.session ?? res?.session ?? null
    resetAnswers()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || t('build.startFailed')
  } finally {
    loading.value = false
  }
}

function buildAnswers(questions: BuildQuestion[], source: Record<string, BuildAnswer>): BuildAnswer[] {
  const result: BuildAnswer[] = []
  for (const q of questions) {
    const answer = source[q.id]
    if (!answer) continue
    if (q.kind === 'secret') {
      if (!answer.secret_value) continue
      result.push({ id: q.id, selected: [], custom: '', secret_value: answer.secret_value })
      continue
    }
    if (!answer.selected?.length && !answer.custom?.trim()) continue
    result.push({ id: q.id, selected: answer.selected || [], custom: answer.custom || '' })
  }
  return result
}

async function submitAnswers() {
  if (!session.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const res: any = await submitBuildAnswers(
      session.value.session_id,
      buildAnswers(currentQuestions.value, answers),
      supplement.value,
    )
    session.value = res?.data?.session ?? res?.session ?? session.value
    resetAnswers()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || t('build.answerFailed')
  } finally {
    loading.value = false
  }
}

function buildTranscript(target: BuildSession): string {
  const lines: string[] = []
  for (const round of target.rounds || []) {
    for (const q of round.questions || []) {
      const answer = (round.answers || []).find((a) => a.id === q.id)
      if (!answer) continue
      let value = answer.custom || (answer.selected || []).join(', ')
      if (q.kind === 'secret') value = '（已配置）'
      if (value) lines.push(`- ${q.question}: ${value}`)
    }
  }
  return lines.join('\n')
}

function buildPrompt(target: BuildSession, batchId: string): string {
  const plan = target.build_plan?.summary ? `构建计划：${target.build_plan.summary}` : '构建计划：按已确认问答执行'
  const transcript = buildTranscript(target)
  return [
    `构建会话 ${target.session_id} 已批准（批次 ${batchId}）。`,
    `需求：${target.request}`,
    plan,
    transcript ? `已确认问答：\n${transcript}` : '',
    '请按就绪清单和已确认参数开始构建；遇到新疑问用 ask_user 面板，不要自行假设。',
  ].filter(Boolean).join('\n')
}

async function submitInteraction() {
  if (!session.value || !activeInteraction.value || loading.value) return
  const q = activeInteraction.value.question
  const answer = interactionAnswer.value
  if (q.kind === 'secret' ? !answer.secret_value : !answer.selected?.length && !answer.custom?.trim()) {
    uiMessage.warning(t('build.answerRequired'))
    return
  }
  loading.value = true
  error.value = ''
  try {
    const payload: BuildAnswer = q.kind === 'secret'
      ? { id: q.id, selected: [], custom: '', secret_value: answer.secret_value }
      : { id: q.id, selected: answer.selected || [], custom: answer.custom || '' }
    const res: any = await answerBuildInteraction(
      session.value.session_id,
      activeInteraction.value.interaction_id,
      payload,
    )
    const updated = res?.data?.session ?? res?.session ?? session.value
    session.value = updated
    if (updated) emit('resumed', {
      sessionId: updated.session_id,
      request: updated.request,
      prompt: `构建会话 ${updated.session_id} 的交互已回答，请继续构建。回答：${payload.custom || payload.selected.join(', ') || (payload.secret_value ? '（凭据已配置）' : '')}`,
    })
    close()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || t('build.answerFailed')
  } finally {
    loading.value = false
  }
}

async function approve() {
  if (!session.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const res: any = await approveBuildSession(session.value.session_id)
    const updated = res?.data?.session ?? res?.session ?? session.value
    session.value = updated
    if (updated) {
      const prompt = buildPrompt(updated, updated.batch_id)
      emit('approved', {
        sessionId: updated.session_id,
        request: updated.request,
        batchId: updated.batch_id,
        prompt,
      })
    }
    close()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || t('build.approveFailed')
  } finally {
    loading.value = false
  }
}

async function close() {
  if (session.value && session.value.status === 'clarifying' && !activeInteraction.value) {
    try {
      await cancelBuildSession(session.value.session_id)
    } catch {
      // 取消失败不阻塞关闭；会话可由后端过期清理
    }
  }
  emit('close')
}

defineExpose({ cancel: close })
</script>

<style scoped>
.nr-build-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.nr-build-hint {
  color: var(--nr-text-secondary);
  font-size: 13px;
  margin: 0;
}
.nr-build-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.nr-build-request {
  font-size: 14px;
  color: var(--nr-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-build-checklist {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
}
.nr-build-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--nr-text-tertiary);
}
.nr-build-check.is-ok {
  color: var(--nr-text-secondary);
}
.nr-build-check-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--nr-border);
}
.nr-build-check.is-ok .nr-build-check-dot {
  background: var(--nr-primary-light);
}
.nr-build-question {
  border: 1px solid var(--nr-glass-border);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--nr-glass-bg);
}
.nr-build-q-text {
  font-size: 13px;
  color: var(--nr-text-primary);
}
.nr-build-q-why {
  margin-top: 4px;
  font-size: 12px;
  color: var(--nr-text-tertiary);
}
.nr-build-supplement {
  margin-top: 4px;
}
.nr-build-ready {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--nr-primary-soft);
  color: var(--nr-text-secondary);
  font-size: 13px;
}
.nr-build-ready code {
  font-size: 11px;
  color: var(--nr-text-tertiary);
}
.nr-build-plan {
  margin-top: 6px;
  color: var(--nr-text-primary);
}
.nr-build-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
</style>
