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
                <div class="big-value">{{ formatPercent(motivationData?.level) }}</div>
                <a-progress
                  :percent="Math.round((motivationData?.level || 0) * 100)"
                  :stroke-color="(motivationData?.level || 0) >= 0.7 ? '#10b981' : '#f59e0b'"
                  :show-info="false"
                />
              </div>
              <!-- Motivation factors -->
              <div v-if="motivationData?.factors?.length" class="factors-list">
                <div v-for="factor in motivationData.factors" :key="factor.name" class="factor-row">
                  <div class="factor-info">
                    <span class="factor-name">{{ factor.name }}</span>
                    <span class="factor-impact" :class="{ positive: factor.impact > 0, negative: factor.impact < 0 }">
                      {{ factor.impact > 0 ? '+' : '' }}{{ Math.round(factor.impact * 100) }}%
                    </span>
                  </div>
                  <a-progress
                    :percent="Math.min(Math.abs(factor.impact) * 100, 100)"
                    :stroke-color="factor.impact >= 0 ? '#10b981' : '#ef4444'"
                    size="small"
                    :show-info="false"
                  />
                </div>
              </div>
              <div v-if="motivationData?.updated_at" class="meta-timestamp">
                {{ t('common.updated') }}: {{ formatTime(motivationData.updated_at) }}
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
              <div v-if="personalityProfile?.style || personalityProfile?.tone" class="personality-meta">
                <a-tag v-if="personalityProfile?.style">{{ personalityProfile.style }}</a-tag>
                <a-tag v-if="personalityProfile?.tone" color="purple">{{ personalityProfile.tone }}</a-tag>
              </div>
            </GlassCard>
          </div>

          <!-- Constitution summary -->
          <GlassCard :title="t('growth.constitution')" style="margin-top: 20px">
            <div v-if="constitutionRules.length > 0" class="constitution-preview">
              <p>{{ constitutionRules.slice(0, 3).map((r: any) => r.rule).join('\n') }}</p>
              <a v-if="constitutionRules.length > 3" class="show-more-link" @click="activeTab = 'constitution'">
                +{{ constitutionRules.length - 3 }} {{ t('growth.moreRules') || 'more rules' }}
              </a>
            </div>
            <a-empty v-else :description="t('common.noData')" />
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Questions Tab -->
      <a-tab-pane key="questions" :tab="t('growth.questions')">
        <div class="tab-toolbar">
          <a-select
            v-model:value="questionsFilter"
            :placeholder="t('common.filter') || 'Filter'"
            allow-clear
            style="min-width: 140px; margin-right: 12px"
            @change="fetchQuestions"
          >
            <a-select-option value="all">{{ t('common.all') }}</a-select-option>
            <a-select-option value="unanswered">{{ t('growth.pending') }}</a-select-option>
            <a-select-option value="answered">{{ t('growth.answered') }}</a-select-option>
          </a-select>
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
                <div v-if="q.context" class="question-context">{{ q.context }}</div>
                <div v-if="q.answer" class="question-answer">{{ q.answer }}</div>
                <div class="question-actions">
                  <GlassButton v-if="!q.answered" size="sm" variant="ghost" @click="openAnswerModal(q)">
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
          <a-select
            v-model:value="actionsFilter"
            :placeholder="t('common.filter') || 'Filter'"
            allow-clear
            style="min-width: 140px; margin-right: 12px"
            @change="fetchActions"
          >
            <a-select-option value="all">{{ t('common.all') }}</a-select-option>
            <a-select-option value="pending">{{ t('growth.pending') }}</a-select-option>
            <a-select-option value="completed">{{ t('growth.completed') || 'Completed' }}</a-select-option>
            <a-select-option value="skipped">{{ t('growth.skipped') || 'Skipped' }}</a-select-option>
          </a-select>
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
                  :status="record.status === 'completed' ? 'success' : record.status === 'in_progress' ? 'processing' : record.status === 'skipped' ? 'warning' : 'default'"
                  :text="record.status"
                />
              </template>
              <template v-else-if="column.key === 'type'">
                <a-tag>{{ record.type }}</a-tag>
              </template>
            </template>
          </a-table>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>

      <!-- Constitution Tab -->
      <a-tab-pane key="constitution" :tab="t('growth.constitution')">
        <div class="tab-toolbar">
          <GlassButton variant="primary" size="sm" @click="showAddRuleModal = true">
            {{ t('common.create') }}
          </GlassButton>
        </div>
        <a-spin :spinning="loadingConstitution">
          <GlassCard :title="t('growth.rules')">
            <div v-if="constitutionRules.length > 0" class="rules-list">
              <div v-for="rule in constitutionRules" :key="rule.id" class="rule-item">
                <div class="rule-header">
                  <span class="rule-index">{{ rule.priority ?? (constitutionRules.indexOf(rule) + 1) }}</span>
                  <div class="rule-body">
                    <span class="rule-text">{{ rule.rule }}</span>
                    <div class="rule-meta">
                      <a-badge :status="rule.enabled ? 'success' : 'default'" :text="rule.enabled ? 'Enabled' : 'Disabled'" />
                      <span class="rule-date">{{ formatTime(rule.created_at) }}</span>
                    </div>
                  </div>
                  <div class="rule-actions">
                    <a-tooltip :title="rule.enabled ? (t('common.disable') || 'Disable') : (t('common.enable') || 'Enable')">
                      <a-switch
                        :checked="rule.enabled"
                        size="small"
                        @change="(checked: boolean) => toggleRule(rule, checked)"
                      />
                    </a-tooltip>
                    <a-popconfirm
                      :title="t('common.delete') + '?'"
                      @confirm="removeRule(rule.id)"
                      :ok-text="t('common.yes')"
                      :cancel-text="t('common.no')"
                    >
                      <GlassButton size="sm" variant="danger">
                        {{ t('common.delete') }}
                      </GlassButton>
                    </a-popconfirm>
                  </div>
                </div>
              </div>
            </div>
            <a-empty v-else :description="t('common.noData')" />
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

    <!-- Add constitution rule modal (NEW) -->
    <a-modal v-model:open="showAddRuleModal" :title="t('growth.rules')" @ok="addRule" :confirm-loading="addingRule">
      <a-form layout="vertical">
        <a-form-item :label="t('growth.rules')" required>
          <a-textarea v-model:value="newRuleText" :rows="3" />
        </a-form-item>
        <a-form-item :label="t('growth.priority')">
          <a-input-number v-model:value="newRulePriority" :min="1" :max="100" style="width: 100%" />
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
import * as growthApi from '@/api/modules/growth'
import type { MotivationState, PersonalityProfile, ConstitutionRule, GrowthQuestion, ProactiveAction } from '@/api/modules/growth'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage({
  onAgentChange: () => {
    fetchOverview()
    fetchQuestions()
    fetchActions()
    fetchConstitution()
  },
})

const activeTab = ref('overview')

// Overview state
const loadingOverview = ref(false)
const motivationData = ref<MotivationState | null>(null)
const personalityProfile = ref<PersonalityProfile | null>(null)
const personalityTraits = ref<{ name: string; value: number }[]>([])
const constitutionRules = ref<ConstitutionRule[]>([])

// Questions state
const loadingQuestions = ref(false)
const questions = ref<GrowthQuestion[]>([])
const questionsFilter = ref<string>('all')
const showQuestionModal = ref(false)
const creatingQuestion = ref(false)
const newQuestion = ref('')
const showAnswerModal = ref(false)
const questionToAnswer = ref<GrowthQuestion | null>(null)
const answerText = ref('')
const submittingAnswer = ref(false)

// Actions state
const loadingActions = ref(false)
const actions = ref<ProactiveAction[]>([])
const actionsFilter = ref<string>('all')

// Constitution state
const loadingConstitution = ref(false)
const showAddRuleModal = ref(false)
const addingRule = ref(false)
const newRuleText = ref('')
const newRulePriority = ref(1)
const deletingRule = ref(false)

const formatPercent = (val: number | undefined) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const traitColor = (val: number) => {
  if (val >= 0.7) return '#10b981'
  if (val >= 0.4) return '#6366f1'
  return '#f59e0b'
}

const actionColumns = computed(() => [
  { title: t('common.description'), dataIndex: 'description', key: 'description', ellipsis: true },
  { title: t('common.type'), key: 'type', dataIndex: 'type', width: 120 },
  { title: t('common.status'), key: 'status', width: 140 },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
])

// --- Fetch functions using growth API module ---

const fetchOverview = async () => {
  loadingOverview.value = true
  try {
    const [motivationRes, personalityRes, constitutionRes] = await Promise.all([
      growthApi.getMotivation(agentId.value),
      growthApi.getPersonality(agentId.value),
      growthApi.getConstitution(agentId.value),
    ])

    motivationData.value = motivationRes.data ?? null
    personalityProfile.value = personalityRes.data ?? null

    const personality = personalityRes.data
    if (personality?.traits) {
      personalityTraits.value = Object.entries(personality.traits).map(([name, value]) => ({
        name,
        value: value as number,
      }))
    }

    constitutionRules.value = Array.isArray(constitutionRes.data) ? constitutionRes.data : []
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loadingOverview.value = false
  }
}

const fetchQuestions = async () => {
  loadingQuestions.value = true
  try {
    const params: { page?: number; size?: number; answered?: boolean } = { size: 50 }
    if (questionsFilter.value === 'answered') params.answered = true
    if (questionsFilter.value === 'unanswered') params.answered = false
    const res = await growthApi.getQuestions(agentId.value, params)
    const data = res.data
    if (data && typeof data === 'object' && 'items' in data) {
      questions.value = data.items ?? []
    } else {
      questions.value = Array.isArray(data) ? data : []
    }
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
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
    // The API module does not expose a createQuestion function directly,
    // so we use answerQuestion pattern. But since the growth API module
    // has no createQuestion, we'll use the existing approach via getQuestions
    // The growth module has getQuestions and answerQuestion. For creation,
    // we still need a POST. Let's use a direct call for this edge case.
    const api = (await import('@/api')).default
    await api.post('/growth/questions', { agent_id: agentId.value, question: newQuestion.value })
    message.success(t('common.success'))
    showQuestionModal.value = false
    newQuestion.value = ''
    await fetchQuestions()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    creatingQuestion.value = false
  }
}

const openAnswerModal = (q: GrowthQuestion) => {
  questionToAnswer.value = q
  answerText.value = ''
  showAnswerModal.value = true
}

const submitAnswer = async () => {
  if (!answerText.value.trim() || !questionToAnswer.value) {
    message.warning(t('validation.required'))
    return
  }
  submittingAnswer.value = true
  try {
    await growthApi.answerQuestion(questionToAnswer.value.id, answerText.value)
    message.success(t('common.success'))
    showAnswerModal.value = false
    await fetchQuestions()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    submittingAnswer.value = false
  }
}

const fetchActions = async () => {
  loadingActions.value = true
  try {
    const params: { status?: string } = {}
    if (actionsFilter.value && actionsFilter.value !== 'all') {
      params.status = actionsFilter.value
    }
    const res = await growthApi.getProactiveActions(agentId.value, params)
    const data = res.data
    actions.value = Array.isArray(data) ? data : []
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loadingActions.value = false
  }
}

const fetchConstitution = async () => {
  loadingConstitution.value = true
  try {
    const res = await growthApi.getConstitution(agentId.value)
    constitutionRules.value = Array.isArray(res.data) ? res.data : []
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loadingConstitution.value = false
  }
}

const addRule = async () => {
  if (!newRuleText.value.trim()) {
    message.warning(t('validation.required'))
    return
  }
  addingRule.value = true
  try {
    await growthApi.addConstitutionRule(agentId.value, newRuleText.value, newRulePriority.value)
    message.success(t('common.success'))
    showAddRuleModal.value = false
    newRuleText.value = ''
    newRulePriority.value = 1
    await fetchConstitution()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    addingRule.value = false
  }
}

const toggleRule = async (rule: ConstitutionRule, enabled: boolean) => {
  try {
    await growthApi.updateConstitutionRule(rule.id, { enabled })
    message.success(t('common.success'))
    await fetchConstitution()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  }
}

const removeRule = async (ruleId: string) => {
  deletingRule.value = true
  try {
    await growthApi.deleteConstitutionRule(ruleId)
    message.success(t('common.success'))
    await fetchConstitution()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    deletingRule.value = false
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

.factors-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.factor-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.factor-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.factor-name {
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-transform: capitalize;
}

.factor-impact {
  font-size: 11px;
  font-family: var(--nr-font-mono);
}

.factor-impact.positive {
  color: var(--nr-success);
}

.factor-impact.negative {
  color: var(--nr-error);
}

.meta-timestamp {
  font-size: 11px;
  color: var(--nr-text-muted);
  margin-top: 12px;
  font-family: var(--nr-font-mono);
}

.personality-meta {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
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

.show-more-link {
  display: inline-block;
  margin-top: 8px;
  font-size: 13px;
  color: var(--nr-primary-light);
  cursor: pointer;
}

.tab-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  margin-bottom: 16px;
}

/* Questions */
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

.question-context {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  font-style: italic;
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

/* Constitution rules */
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

.rule-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rule-text {
  font-size: 14px;
  color: var(--nr-text-primary);
  line-height: 1.5;
}

.rule-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.rule-date {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}

.rule-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
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
