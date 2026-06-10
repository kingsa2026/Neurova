<template>
  <div class="growth-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('growth.title') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <GlassButton variant="secondary" :loading="loadingOverview" @click="fetchOverview">
        {{ t('common.refresh') }}
      </GlassButton>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- Overview Tab -->
      <a-tab-pane key="overview" :tab="t('memory.overview')">
        <a-spin :spinning="loadingOverview">
          <!-- Motivation & personality stats -->
          <div class="overview-grid">
            <GlassCard :title="t('growth.motivation')">
              <div class="big-stat">
                <div class="big-value">{{ formatPercent(overview.motivation_level) }}</div>
                <a-progress
                  :percent="Math.round((overview.motivation_level || 0) * 100)"
                  :stroke-color="overview.motivation_level >= 0.7 ? '#10b981' : '#f59e0b'"
                  :show-info="false"
                />
              </div>
            </GlassCard>

            <GlassCard :title="t('growth.personality')">
              <div v-if="personalityTraits.length > 0" class="traits-list">
                <div v-for="trait in personalityTraits" :key="trait.name" class="trait-row">
                  <div class="trait-info">
                    <span class="trait-name">{{ trait.name }}</span>
                    <span class="trait-value">{{ formatPercent(trait.value) }}</span>
                  </div>
                  <a-progress
                    :percent="Math.round((trait.value || 0) * 100)"
                    :stroke-color="traitColor(trait.value)"
                    size="small"
                  />
                </div>
              </div>
              <a-empty v-else :description="t('common.noData')" />
            </GlassCard>
          </div>

          <!-- Constitution summary -->
          <GlassCard :title="t('growth.constitution')" style="margin-top: 20px">
            <div v-if="constitutionSummary" class="constitution-preview">
              <p>{{ constitutionSummary }}</p>
            </div>
            <a-empty v-else :description="t('common.noData')" />
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Questions Tab -->
      <a-tab-pane key="questions" :tab="t('growth.questions')">
        <div class="tab-toolbar">
          <GlassButton variant="primary" size="sm" @click="showQuestionModal = true">
            {{ t('common.create') }}
          </GlassButton>
        </div>
        <a-spin :spinning="loadingQuestions">
          <div v-if="questions.length > 0" class="questions-list">
            <GlassCard v-for="q in questions" :key="q.id" variant="subtle">
              <div class="question-item">
                <div class="question-header">
                  <h4>{{ q.question }}</h4>
                  <a-tag :color="q.answered ? 'green' : 'orange'">
                    {{ q.answered ? t('growth.answered') : t('growth.pending') }}
                  </a-tag>
                </div>
                <div v-if="q.answer" class="question-answer">{{ q.answer }}</div>
                <div class="question-actions">
                  <GlassButton v-if="!q.answered" size="sm" variant="ghost" @click="answerQuestion(q)">
                    {{ t('growth.answer') }}
                  </GlassButton>
                </div>
              </div>
            </GlassCard>
          </div>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>

      <!-- Proactive Actions Tab -->
      <a-tab-pane key="actions" :tab="t('growth.proactive')">
        <div class="tab-toolbar">
          <GlassButton variant="primary" size="sm" @click="showActionModal = true">
            {{ t('common.create') }}
          </GlassButton>
        </div>
        <a-spin :spinning="loadingActions">
          <a-table
            v-if="actions.length > 0"
            :columns="actionColumns"
            :data-source="actions"
            :pagination="false"
            row-key="id"
            size="middle"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <a-badge
                  :status="record.status === 'completed' ? 'success' : record.status === 'in_progress' ? 'processing' : 'default'"
                  :text="record.status"
                />
              </template>
              <template v-else-if="column.key === 'priority'">
                <a-tag :color="record.priority === 'high' ? 'red' : record.priority === 'medium' ? 'orange' : 'blue'">
                  {{ record.priority }}
                </a-tag>
              </template>
            </template>
          </a-table>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>

      <!-- Constitution Tab -->
      <a-tab-pane key="constitution" :tab="t('growth.constitution')">
        <a-spin :spinning="loadingConstitution">
          <GlassCard :title="t('growth.rules')">
            <div v-if="constitutionRules.length > 0" class="rules-list">
              <div v-for="(rule, idx) in constitutionRules" :key="idx" class="rule-item">
                <div class="rule-header">
                  <span class="rule-index">{{ idx + 1 }}</span>
                  <span class="rule-text">{{ rule.rule || rule.content }}</span>
                </div>
                <div v-if="rule.description" class="rule-desc">{{ rule.description }}</div>
              </div>
            </div>
            <a-empty v-else :description="t('common.noData')" />

            <template #footer>
              <div class="constitution-actions">
                <GlassButton variant="secondary" size="sm" @click="showEditConstitution = true">
                  {{ t('common.edit') }}
                </GlassButton>
                <GlassButton variant="primary" size="sm" :loading="evaluating" @click="evaluateConstitution">
                  {{ t('growth.evaluate') }}
                </GlassButton>
              </div>
            </template>
          </GlassCard>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Create question modal -->
    <a-modal v-model:open="showQuestionModal" :title="t('growth.questions')" @ok="createQuestion" :confirm-loading="creatingQuestion">
      <a-form layout="vertical">
        <a-form-item :label="t('growth.questions')">
          <a-textarea v-model:value="newQuestion" :rows="3" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Answer question modal -->
    <a-modal v-model:open="showAnswerModal" :title="t('growth.questions')" @ok="submitAnswer" :confirm-loading="submittingAnswer">
      <p v-if="questionToAnswer" class="modal-question">{{ questionToAnswer.question }}</p>
      <a-form layout="vertical">
        <a-form-item :label="t('growth.answer')">
          <a-textarea v-model:value="answerText" :rows="4" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Create action modal -->
    <a-modal v-model:open="showActionModal" :title="t('growth.proactive')" @ok="createAction" :confirm-loading="creatingAction">
      <a-form layout="vertical" :model="newAction">
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="newAction.description" :rows="3" />
        </a-form-item>
        <a-form-item :label="t('growth.priority')">
          <a-select v-model:value="newAction.priority" style="width: 100%">
            <a-select-option value="low">{{ t('growth.low') }}</a-select-option>
            <a-select-option value="medium">{{ t('growth.medium') }}</a-select-option>
            <a-select-option value="high">{{ t('growth.high') }}</a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- Edit constitution modal -->
    <a-modal v-model:open="showEditConstitution" :title="t('growth.constitution')" @ok="saveConstitution" :confirm-loading="savingConstitution" width="640px">
      <a-form layout="vertical">
        <a-form-item :label="t('growth.rules')">
          <a-textarea v-model:value="constitutionText" :rows="10" :placeholder="t('growth.oneRulePerLine')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { request } from '@/api'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()

const activeTab = ref('overview')

// Overview state
const loadingOverview = ref(false)
const overview = ref<any>({})
const personalityTraits = ref<{ name: string; value: number }[]>([])
const constitutionSummary = ref('')

// Questions state
const loadingQuestions = ref(false)
const questions = ref<any[]>([])
const showQuestionModal = ref(false)
const creatingQuestion = ref(false)
const newQuestion = ref('')
const showAnswerModal = ref(false)
const questionToAnswer = ref<any>(null)
const answerText = ref('')
const submittingAnswer = ref(false)

// Actions state
const loadingActions = ref(false)
const actions = ref<any[]>([])
const showActionModal = ref(false)
const creatingAction = ref(false)
const newAction = ref({ description: '', priority: 'medium' })

// Constitution state
const loadingConstitution = ref(false)
const constitutionRules = ref<any[]>([])
const showEditConstitution = ref(false)
const constitutionText = ref('')
const savingConstitution = ref(false)
const evaluating = ref(false)

const formatPercent = (val: number | undefined) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const traitColor = (val: number) => {
  if (val >= 0.7) return '#10b981'
  if (val >= 0.4) return '#6366f1'
  return '#f59e0b'
}

const actionColumns = computed(() => [
  { title: t('common.description'), dataIndex: 'description', key: 'description', ellipsis: true },
  { title: t('common.status'), key: 'status', width: 140 },
  { title: t('growth.priority'), key: 'priority', width: 100 },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
])

const fetchOverview = async () => {
  loadingOverview.value = true
  try {
    const [growthRes, personalityRes] = await Promise.all([
      request.get('/growth', { params: { agent_id: agentId.value } }),
      request.get('/growth/personality', { params: { agent_id: agentId.value } }),
    ])
    const growth: any = growthRes?.data ?? growthRes
    const personality: any = personalityRes?.data ?? personalityRes

    overview.value = growth?.overview ?? growth ?? {}
    constitutionSummary.value = growth?.constitution_summary ?? growth?.constitution?.summary ?? ''

    if (personality?.traits) {
      personalityTraits.value = Object.entries(personality.traits).map(([name, value]) => ({
        name,
        value: value as number,
      }))
    } else if (Array.isArray(personality)) {
      personalityTraits.value = personality
    }
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loadingOverview.value = false
  }
}

const fetchQuestions = async () => {
  loadingQuestions.value = true
  try {
    const res: any = await request.get('/growth/questions', { params: { agent_id: agentId.value } })
    const data = res?.data ?? res
    questions.value = Array.isArray(data) ? data : data?.items ?? data?.questions ?? []
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loadingQuestions.value = false
  }
}

const createQuestion = async () => {
  if (!newQuestion.value.trim()) {
    message.warning(t('validation.required'))
    return
  }
  creatingQuestion.value = true
  try {
    await request.post('/growth/questions', {
      agent_id: agentId.value,
      question: newQuestion.value,
    })
    message.success(t('common.success'))
    showQuestionModal.value = false
    newQuestion.value = ''
    await fetchQuestions()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    creatingQuestion.value = false
  }
}

const answerQuestion = (q: any) => {
  questionToAnswer.value = q
  answerText.value = ''
  showAnswerModal.value = true
}

const submitAnswer = async () => {
  if (!answerText.value.trim()) {
    message.warning(t('validation.required'))
    return
  }
  submittingAnswer.value = true
  try {
    await request.put(`/growth/questions/${questionToAnswer.value.id}`, {
      answer: answerText.value,
    })
    message.success(t('common.success'))
    showAnswerModal.value = false
    await fetchQuestions()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    submittingAnswer.value = false
  }
}

const fetchActions = async () => {
  loadingActions.value = true
  try {
    const res: any = await request.get('/growth/actions', { params: { agent_id: agentId.value } })
    const data = res?.data ?? res
    actions.value = Array.isArray(data) ? data : data?.items ?? data?.actions ?? []
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loadingActions.value = false
  }
}

const createAction = async () => {
  if (!newAction.value.description.trim()) {
    message.warning(t('validation.required'))
    return
  }
  creatingAction.value = true
  try {
    await request.post('/growth/actions', {
      agent_id: agentId.value,
      ...newAction.value,
    })
    message.success(t('common.success'))
    showActionModal.value = false
    newAction.value = { description: '', priority: 'medium' }
    await fetchActions()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    creatingAction.value = false
  }
}

const fetchConstitution = async () => {
  loadingConstitution.value = true
  try {
    const res: any = await request.get('/growth/constitution', { params: { agent_id: agentId.value } })
    const data = res?.data ?? res
    constitutionRules.value = Array.isArray(data) ? data : data?.rules ?? data?.items ?? []
    constitutionText.value = constitutionRules.value.map((r: any) => r.rule || r.content).join('\n')
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loadingConstitution.value = false
  }
}

const saveConstitution = async () => {
  savingConstitution.value = true
  try {
    const rules = constitutionText.value.split('\n').filter((line) => line.trim())
    await request.put('/growth/constitution', {
      agent_id: agentId.value,
      rules: rules.map((r) => ({ rule: r })),
    })
    message.success(t('common.success'))
    showEditConstitution.value = false
    await fetchConstitution()
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    savingConstitution.value = false
  }
}

const evaluateConstitution = async () => {
  evaluating.value = true
  try {
    await request.post('/growth/constitution/evaluate', { agent_id: agentId.value })
    message.success(t('common.success'))
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    evaluating.value = false
  }
}

onMounted(() => {
  fetchOverview()
  fetchQuestions()
  fetchActions()
  fetchConstitution()
})
</script>

<style scoped>
.growth-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.page-title {
  font-family: var(--nr-font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.page-subtitle {
  margin: 4px 0 0;
  color: var(--nr-text-secondary);
  font-size: 13px;
}

.overview-grid {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 20px;
}

.big-stat {
  text-align: center;
  padding: 12px 0;
}

.big-value {
  font-family: var(--nr-font-display);
  font-size: 36px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin-bottom: 12px;
}

.traits-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.trait-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.trait-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.trait-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
  text-transform: capitalize;
}

.trait-value {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
}

.constitution-preview {
  font-size: 14px;
  color: var(--nr-text-primary);
  line-height: 1.7;
  white-space: pre-wrap;
}

.tab-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}

.questions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.question-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.question-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.question-header h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin: 0;
}

.question-answer {
  font-size: 13px;
  color: var(--nr-text-secondary);
  line-height: 1.6;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
}

.question-actions {
  display: flex;
  justify-content: flex-end;
}

.rules-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rule-item {
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.rule-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.rule-index {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.15);
  color: var(--nr-primary-light);
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.rule-text {
  font-size: 14px;
  color: var(--nr-text-primary);
  line-height: 1.5;
}

.rule-desc {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  margin-top: 6px;
  padding-left: 36px;
}

.constitution-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.modal-question {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin-bottom: 16px;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
}
</style>
