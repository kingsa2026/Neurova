<template>
  <a-modal
    :open="open"
    :title="t('plan.panelTitle')"
    width="720px"
    :footer="null"
    :mask-closable="false"
    class="nr-plan-panel"
    @cancel="emit('close')"
  >
    <!-- 头部：需求摘要 + 状态 -->
    <div class="nr-plan-head">
      <div class="nr-plan-request" :title="session?.request">{{ session?.request }}</div>
      <a-tag v-if="session" :color="statusColor">{{ statusLabel }}</a-tag>
    </div>

    <!-- 初始需求输入态（未建会话） -->
    <div v-if="!session" class="nr-plan-intro">
      <a-textarea
        v-model:value="requestDraft"
        :placeholder="t('plan.requestPlaceholder')"
        :rows="4"
        @keydown.enter.exact.prevent="startSession"
      />
      <div class="nr-plan-intro-hint">{{ t('plan.introHint') }}</div>
    </div>

    <!-- 加载/错误条 -->
    <a-alert v-if="error" type="error" :message="error" show-icon closable class="nr-plan-alert" @close="error = ''" />
    <div v-if="busy" class="nr-plan-busy">
      <a-spin size="small" />
      <span>{{ t('plan.thinking') }}</span>
    </div>

    <!-- 问答区（asking 态） -->
    <div v-if="session && session.status === 'asking'" class="nr-plan-qa">
      <div v-for="(round, ri) in session.rounds" :key="ri" class="nr-plan-round">
        <div class="nr-plan-round-label">{{ t('plan.roundN', { n: ri + 1 }) }}</div>
        <div v-for="q in currentQuestions(round)" :key="q.id" class="nr-plan-question">
          <div class="nr-plan-q-text">{{ q.question }}</div>
          <a-checkbox-group
            v-if="q.multi"
            :value="answers[q.id]?.selected ?? []"
            class="nr-plan-options"
            @update:value="(v: string[]) => setAnswer(q, v)"
          >
            <a-checkbox v-for="opt in q.options" :key="opt.label" :value="opt.label">
              {{ opt.label }}
              <span v-if="opt.description" class="nr-plan-opt-desc">{{ opt.description }}</span>
            </a-checkbox>
          </a-checkbox-group>
          <a-radio-group
            v-else
            :value="answers[q.id]?.selected ?? []"
            class="nr-plan-options"
            @update:value="(v: string) => setAnswer(q, [v])"
          >
            <a-radio v-for="opt in q.options" :key="opt.label" :value="opt.label">
              {{ opt.label }}
              <span v-if="opt.description" class="nr-plan-opt-desc">{{ opt.description }}</span>
            </a-radio>
          </a-radio-group>
          <a-input
            v-if="q.allow_custom"
            :value="answers[q.id]?.custom || ''"
            :placeholder="t('plan.customPlaceholder')"
            class="nr-plan-custom"
            allow-clear
            @update:value="(v: string) => setCustom(q, v)"
          />
        </div>
      </div>
      <a-textarea
        v-model:value="supplement"
        :placeholder="t('plan.supplementPlaceholder')"
        :rows="2"
        class="nr-plan-supplement"
      />
    </div>

    <!-- 计划预览（awaiting_approval 态）-->
    <div v-if="session?.status === 'awaiting_approval' && planContent !== null" class="nr-plan-preview">
      <div class="nr-plan-doc-title">{{ session.document?.title || t('plan.defaultTitle') }}</div>
      <div class="nr-plan-doc-path">{{ session.document?.rel_path }}</div>
      <div class="nr-plan-markdown" v-html="renderedPlan"></div>
    </div>

    <!-- 终态提示 -->
    <a-result
      v-if="session && (session.status === 'approved' || session.status === 'rejected')"
      :status="session.status === 'approved' ? 'success' : 'info'"
      :title="session.status === 'approved' ? t('plan.approvedTitle') : t('plan.rejectedTitle')"
      :sub-title="session.status === 'approved' ? t('plan.approvedDesc') : t('plan.rejectedDesc')"
    />

    <!-- 底部操作 -->
    <div class="nr-plan-actions">
      <template v-if="!session">
        <a-button @click="emit('close')">{{ t('common.cancel') }}</a-button>
        <a-button type="primary" :loading="busy" :disabled="!requestDraft.trim()" @click="startSession">
          {{ t('plan.startClarify') }}
        </a-button>
      </template>
      <template v-else-if="session.status === 'asking'">
        <a-button @click="emit('close')">{{ t('common.cancel') }}</a-button>
        <a-button type="primary" :loading="busy" :disabled="!hasInput" @click="submitRound">
          {{ t('plan.submitAndContinue') }}
        </a-button>
      </template>
      <template v-else-if="session?.status === 'awaiting_approval'">
        <a-button :disabled="busy" @click="backToQuestions">{{ t('plan.supplementMore') }}</a-button>
        <a-button danger :loading="busy" @click="decide('reject')">{{ t('plan.reject') }}</a-button>
        <a-button type="primary" :loading="busy" @click="decide('approve')">
          {{ t('plan.approveExecute') }}
        </a-button>
      </template>
      <template v-else>
        <a-button type="primary" @click="emit('close')">{{ t('common.close') }}</a-button>
      </template>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * PlanPanel —— 计划模式交互面板（ZCode 计划模式对齐）
 *
 * 职责：
 * 1. 问答轮（不限轮数）：选项点选 + 自由补充 → 提交 → LLM 出下一轮或生成计划；
 * 2. 计划预览：MD 全文渲染（renderMarkdown，与聊天页同渲染管线）；
 * 3. 审批：approve → emit('approved', executePrompt)（ChatPage 走 sendMessage
 *    原链路执行）；reject → 终态；补充 → 回问答轮。
 *
 * 状态全部来自后端 PlanSession（单一真相源），本组件只做展示与提交。
 */
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message as uiMessage } from 'ant-design-vue'
import {
  decidePlan,
  readPlanDocument as readPlanDocumentApi,
  startPlanSession as startPlanSessionApi,
  submitPlanAnswers,
  type PlanAnswer,
  type PlanQuestion,
  type PlanRound,
  type PlanSession,
} from '@/api/modules/plans'
import { renderMarkdown } from '@/utils/markdown'

/** 本地答案槽：契约答案字段 + 渲染控制字段（submittedAt 不上行，仅防重复渲染）。 */
interface LocalPlanAnswer extends PlanAnswer {
  submittedAt?: number
}

const props = defineProps<{
  open: boolean
  agentId: string
  /** 初始需求（/plan 后文本）；面板打开时预填 */
  initialRequest: string
}>()

const emit = defineEmits<{
  close: []
  /** 审批通过：携带含计划全文的执行提示词，由聊天页走 sendMessage 原链路 */
  approved: [executePrompt: string]
}>()

const { t } = useI18n()

const busy = ref(false)
const error = ref('')
const supplement = ref('')
const planContent = ref<string | null>(null)
// 会话单一真相源（后端 PlanSession；null=初始需求输入态）
const session = ref<PlanSession | null>(null)
const requestDraft = ref('')
// 每问题一个答案槽：{ selected: string[], custom: string }
const answers = reactive<Record<string, LocalPlanAnswer>>({})

async function startSession(): Promise<void> {
  const request = requestDraft.value.trim()
  if (!request || !props.agentId || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res: any = await startPlanSessionApi(props.agentId, request)
    const started: PlanSession = res?.data?.session
    session.value = started
    resetRoundState(started.rounds[started.rounds.length - 1])
  } catch (e: any) {
    error.value = e?.response?.data?.message || e?.message || t('plan.startFailed')
  } finally {
    busy.value = false
  }
}

const statusColor = computed(() => {
  switch (session.value?.status) {
    case 'asking':
      return 'processing'
    case 'awaiting_approval':
      return 'warning'
    case 'approved':
      return 'success'
    default:
      return 'default'
  }
})

const statusLabel = computed(() => {
  switch (session.value?.status) {
    case 'awaiting_approval':
      return t('plan.statusAwaitingApproval')
    case 'approved':
      return t('plan.statusApproved')
    case 'rejected':
      return t('plan.statusRejected')
    default:
      return t('plan.statusAsking')
  }
})

const hasInput = computed(() => {
  const answered = Object.values(answers).some(
    (a) => (a.selected && a.selected.length > 0) || (a.custom && a.custom.trim())
  )
  return answered || !!supplement.value.trim()
})

const renderedPlan = computed(() => (planContent.value ? renderMarkdown(planContent.value) : ''))

// ---------------------------------------------------------------------------
// 问答交互
// ---------------------------------------------------------------------------

/** 面板只渲染「最新一轮未回答」的问题（历史轮已答复，折叠为轮次标签）。 */
function currentQuestions(round: PlanRound): PlanQuestion[] {
  const s = session.value
  const isLast = !!s && round === s.rounds[s.rounds.length - 1]
  if (!isLast) return []
  return (round.questions || []).filter((q) => !(answers[q.id]?.submittedAt))
}

function ensureAnswer(q: PlanQuestion): LocalPlanAnswer {
  if (!answers[q.id]) {
    answers[q.id] = { id: q.id, selected: [], custom: '' }
  }
  return answers[q.id]
}

function setAnswer(q: PlanQuestion, selected: string[]): void {
  ensureAnswer(q).selected = selected
}

function setCustom(q: PlanQuestion, custom: string): void {
  ensureAnswer(q).custom = custom
}

function resetRoundState(round: PlanRound | undefined): void {
  for (const q of round?.questions || []) {
    answers[q.id] = { id: q.id, selected: [], custom: '' }
  }
  supplement.value = ''
}

// ---------------------------------------------------------------------------
// 提交
// ---------------------------------------------------------------------------

async function submitRound(): Promise<void> {
  if (!session.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const last = session.value.rounds[session.value.rounds.length - 1]
    // 标记本轮已答问题（防重复渲染），只提交有内容的答案
    for (const q of last?.questions || []) {
      if (answers[q.id]) answers[q.id].submittedAt = Date.now()
    }
    const payload: PlanAnswer[] = Object.values(answers).map(({ submittedAt: _s, ...a }) => a).filter(
      (a) => (a.selected && a.selected.length > 0) || (a.custom && a.custom.trim())
    )
    const res: any = await submitPlanAnswers(session.value.session_id, payload, supplement.value)
    const advanced: PlanSession = res?.data?.session
    session.value = advanced
    if (advanced.status === 'awaiting_approval') {
      await loadPlanContent(advanced)
      uiMessage.success(t('plan.generated'))
    } else {
      resetRoundState(advanced.rounds[advanced.rounds.length - 1])
    }
  } catch (e: any) {
    error.value = e?.response?.data?.message || e?.message || t('plan.submitFailed')
  } finally {
    busy.value = false
  }
}

async function backToQuestions(): Promise<void> {
  // 审批面补充 → 空回答 + supplement 提交，后端回到 asking
  if (!session.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res: any = await submitPlanAnswers(session.value.session_id, [], supplement.value)
    const supplemented: PlanSession = res?.data?.session
    session.value = supplemented
    planContent.value = null
    resetRoundState(supplemented.rounds[supplemented.rounds.length - 1])
  } catch (e: any) {
    error.value = e?.response?.data?.message || e?.message || t('plan.submitFailed')
  } finally {
    busy.value = false
  }
}

async function decide(action: 'approve' | 'reject'): Promise<void> {
  if (!session.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res: any = await decidePlan(session.value.session_id, action)
    session.value = res?.data?.session
    if (action === 'approve' && res?.data?.execute_prompt) {
      uiMessage.success(t('plan.approved'))
      emit('approved', res?.data?.execute_prompt)
    } else {
      uiMessage.info(t('plan.rejected'))
    }
  } catch (e: any) {
    error.value = e?.response?.data?.message || e?.message || t('plan.decideFailed')
  } finally {
    busy.value = false
  }
}

async function loadPlanContent(s: PlanSession): Promise<void> {
  if (!s.document) return
  try {
    const res: any = await readPlanDocumentApi(s.agent_id, s.document.name)
    planContent.value = res?.data?.content
  } catch (e: any) {
    planContent.value = null
    error.value = e?.response?.data?.message || t('plan.previewFailed')
  }
}

// open 变化时重置本地态（关闭即丢弃会话态；重开回到需求输入）
watch(
  () => props.open,
  (open) => {
    error.value = ''
    planContent.value = null
    session.value = null
    for (const k of Object.keys(answers)) delete answers[k]
    supplement.value = ''
    requestDraft.value = open ? props.initialRequest : ''
  },
  { immediate: true }
)
</script>

<style scoped>
.nr-plan-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.nr-plan-request {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--nr-text-primary, rgba(0, 0, 0, 0.85));
}

.nr-plan-alert {
  margin-bottom: 12px;
}

.nr-plan-busy {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--nr-text-secondary, rgba(0, 0, 0, 0.45));
  margin-bottom: 12px;
}

.nr-plan-round {
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid var(--nr-border-primary, rgba(0, 0, 0, 0.1));
  border-radius: 10px;
}

.nr-plan-round-label {
  font-size: 12px;
  color: var(--nr-text-tertiary, rgba(0, 0, 0, 0.4));
  margin-bottom: 8px;
}

.nr-plan-question {
  margin-bottom: 14px;
}

.nr-plan-q-text {
  font-weight: 600;
  margin-bottom: 6px;
}

.nr-plan-options {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}

.nr-plan-opt-desc {
  color: var(--nr-text-tertiary, rgba(0, 0, 0, 0.4));
  font-size: 12px;
  margin-left: 4px;
}

.nr-plan-custom {
  margin-top: 4px;
}

.nr-plan-supplement {
  margin-top: 4px;
}

.nr-plan-preview {
  border: 1px solid var(--nr-border-primary, rgba(0, 0, 0, 0.1));
  border-radius: 10px;
  padding: 16px;
  max-height: 50vh;
  overflow-y: auto;
}

.nr-plan-doc-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 2px;
}

.nr-plan-doc-path {
  font-size: 12px;
  color: var(--nr-text-tertiary, rgba(0, 0, 0, 0.4));
  margin-bottom: 12px;
  font-family: monospace;
}

.nr-plan-markdown {
  line-height: 1.65;
}

.nr-plan-markdown :deep(h1),
.nr-plan-markdown :deep(h2),
.nr-plan-markdown :deep(h3) {
  margin: 12px 0 6px;
  font-weight: 700;
}

.nr-plan-markdown :deep(pre) {
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
}

.nr-plan-markdown :deep(code) {
  font-family: monospace;
  font-size: 13px;
}

.nr-plan-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
