<template>
  <div class="experience-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('nav.experience') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <div class="header-actions">
        <GlassButton variant="secondary" size="sm" :loading="loading" @click="fetchAll">
          {{ t('common.refresh') }}
        </GlassButton>
        <GlassButton variant="primary" @click="showCreateModal = true">
          {{ t('common.create') }}
        </GlassButton>
      </div>
    </div>

    <!-- Stats overview (from getExperienceStats API) -->
    <a-spin :spinning="loadingStats">
      <div class="stats-grid">
        <GlassCard variant="subtle">
          <div class="stat-item">
            <div class="stat-value">{{ stats.total_experiences || 0 }}</div>
            <div class="stat-label">{{ t('common.total') }}</div>
          </div>
        </GlassCard>
        <GlassCard variant="subtle">
          <div class="stat-item">
            <div class="stat-value">{{ formatPercent(stats.success_rate) }}</div>
            <div class="stat-label">{{ t('experience.successRate') }}</div>
          </div>
        </GlassCard>
        <GlassCard variant="subtle">
          <div class="stat-item">
            <div class="stat-value">{{ formatPercent(stats.avg_proficiency) }}</div>
            <div class="stat-label">{{ t('experience.proficiency') }}</div>
          </div>
        </GlassCard>
        <GlassCard variant="subtle">
          <div class="stat-item">
            <div class="stat-value">{{ stats.top_categories?.length || 0 }}</div>
            <div class="stat-label">{{ t('common.type') + 's' }}</div>
          </div>
        </GlassCard>
      </div>
    </a-spin>

    <!-- Top categories (NEW) -->
    <div v-if="stats.top_categories?.length" class="top-categories">
      <div v-for="cat in stats.top_categories" :key="cat.category" class="category-chip">
        <span class="chip-name">{{ cat.category }}</span>
        <a-tag color="blue">{{ cat.count }}</a-tag>
      </div>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- Skill Ranking Tab -->
      <a-tab-pane key="ranking" :tab="t('skill.stats')">
        <a-spin :spinning="loading">
          <GlassCard>
            <a-table
              :columns="rankingColumns"
              :data-source="ranking"
              :pagination="{
                current: rankingPage,
                pageSize: rankingSize,
                total: rankingTotal,
                showSizeChanger: true,
              }"
              row-key="skill_name"
              size="middle"
              @change="onRankingTableChange"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'skill_name'">
                  <span class="skill-name">{{ record.skill_name || record.task_type }}</span>
                </template>
                <template v-else-if="column.key === 'success_rate'">
                  <div class="rate-cell">
                    <a-progress
                      :percent="Math.round((record.success_rate || 0) * 100)"
                      :stroke-color="record.success_rate >= 0.8 ? '#10b981' : record.success_rate >= 0.5 ? '#6366f1' : '#f59e0b'"
                      size="small"
                      :show-info="false"
                      style="width: 80px"
                    />
                    <span class="rate-text">{{ formatPercent(record.success_rate) }}</span>
                  </div>
                </template>
                <template v-else-if="column.key === 'experience_count'">
                  <a-tag color="blue">{{ record.experience_count }}</a-tag>
                </template>
                <template v-else-if="column.key === 'proficiency'">
                  <a-rate :value="record.proficiency || 0" disabled :count="5" style="font-size: 12px" />
                </template>
                <template v-else-if="column.key === 'outcome'">
                  <a-tag :color="record.outcome === 'success' ? 'green' : record.outcome === 'failure' ? 'red' : 'default'">
                    {{ record.outcome || 'unknown' }}
                  </a-tag>
                </template>
              </template>
            </a-table>
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Experience Records Tab -->
      <a-tab-pane key="records" :tab="t('nav.experience')">
        <a-spin :spinning="loading">
          <GlassCard>
            <div class="toolbar">
              <a-input-search
                v-model:value="searchQuery"
                :placeholder="t('common.search')"
                style="max-width: 320px"
                allow-clear
              />
              <a-select
                v-model:value="taskTypeFilter"
                :placeholder="t('common.type')"
                allow-clear
                style="min-width: 160px"
                @change="fetchExperiences"
              >
                <a-select-option v-for="tt in taskTypes" :key="tt" :value="tt">{{ tt }}</a-select-option>
              </a-select>
            </div>

            <a-table
              :columns="recordColumns"
              :data-source="filteredRecords"
              :pagination="{
                current: recordsPage,
                pageSize: recordsSize,
                total: recordsTotal,
                showSizeChanger: true,
              }"
              row-key="id"
              size="middle"
              @change="onRecordsTableChange"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'task_type'">
                  <a-tag color="purple">{{ record.task_type }}</a-tag>
                </template>
                <template v-else-if="column.key === 'outcome'">
                  <a-tag :color="record.outcome === 'success' ? 'green' : record.outcome === 'failure' ? 'red' : record.outcome === 'partial' ? 'orange' : 'default'">
                    {{ record.outcome || 'unknown' }}
                  </a-tag>
                </template>
                <template v-else-if="column.key === 'lessons'">
                  <span v-if="record.lessons?.length" class="lessons-count">{{ record.lessons.length }}</span>
                  <span v-else>-</span>
                </template>
                <template v-else-if="column.key === 'actions'">
                  <div class="row-actions">
                    <GlassButton size="sm" variant="ghost" @click="findSimilar(record)">
                      {{ t('experience.similarExperiences') || 'Similar' }}
                    </GlassButton>
                    <a-popconfirm
                      :title="t('common.delete') + '?'"
                      @confirm="deleteExperience(record.id)"
                      :ok-text="t('common.yes')"
                      :cancel-text="t('common.no')"
                    >
                      <GlassButton size="sm" variant="danger">
                        {{ t('common.delete') }}
                      </GlassButton>
                    </a-popconfirm>
                  </div>
                </template>
              </template>
            </a-table>
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Recommendations Tab -->
      <a-tab-pane key="recommendations" tab="Recommendations">
        <div class="tab-toolbar">
          <a-input
            v-model:value="recommendationTaskType"
            :placeholder="t('common.type') || 'Task type'"
            style="max-width: 240px; margin-right: 12px"
            allow-clear
            @pressEnter="fetchRecommendations"
          />
          <GlassButton variant="secondary" size="sm" :loading="loadingRecommendations" @click="fetchRecommendations">
            {{ t('common.search') || 'Search' }}
          </GlassButton>
        </div>
        <a-spin :spinning="loadingRecommendations">
          <div v-if="recommendations.length > 0" class="recommendations-grid">
            <GlassCard v-for="rec in recommendations" :key="rec.id" variant="subtle">
              <div class="rec-item">
                <div class="rec-header">
                  <a-tag :color="rec.outcome === 'success' ? 'green' : rec.outcome === 'failure' ? 'red' : 'blue'">
                    {{ rec.outcome || 'info' }}
                  </a-tag>
                  <span class="rec-skill">{{ rec.task_type || rec.skill_name }}</span>
                </div>
                <p class="rec-text">{{ rec.context }}</p>
                <div v-if="rec.lessons?.length" class="rec-lessons">
                  <div class="lessons-label">{{ t('growth.lesson') + 's' || 'Lessons' }}</div>
                  <ul>
                    <li v-for="(lesson, idx) in rec.lessons" :key="idx">{{ lesson }}</li>
                  </ul>
                </div>
                <div v-if="rec.success_rate" class="rec-confidence">
                  {{ t('experience.successRate') }}: {{ formatPercent(rec.success_rate) }}
                </div>
              </div>
            </GlassCard>
          </div>
          <a-empty v-else :description="t('common.noData')" />
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Similar experiences modal -->
    <a-modal
      v-model:open="showSimilarModal"
      :title="t('experience.similarExperiences')"
      :footer="null"
      width="640px"
    >
      <a-spin :spinning="loadingSimilar">
        <div v-if="similarExperiences.length > 0" class="similar-list">
          <div v-for="sim in similarExperiences" :key="sim.id" class="similar-item">
            <div class="similar-header">
              <span class="similar-skill">{{ sim.task_type || sim.skill_name }}</span>
              <a-tag :color="sim.outcome === 'success' ? 'green' : sim.outcome === 'failure' ? 'red' : 'default'">{{ sim.outcome }}</a-tag>
            </div>
            <div class="similar-content">{{ sim.context }}</div>
            <div v-if="sim.lessons?.length" class="similar-lessons">
              <span class="lessons-label">{{ t('growth.lesson') + 's' || 'Lessons' }}:</span>
              <span v-for="(lesson, idx) in sim.lessons" :key="idx" class="lesson-chip">{{ lesson }}</span>
            </div>
            <div v-if="sim.success_rate" class="similar-score">
              {{ t('experience.successRate') }}: {{ formatPercent(sim.success_rate) }}
            </div>
          </div>
        </div>
        <a-empty v-else :description="t('common.noData')" />
      </a-spin>
    </a-modal>

    <!-- Create experience modal (NEW) -->
    <a-modal
      v-model:open="showCreateModal"
      :title="t('common.create') + ' ' + t('nav.experience')"
      :confirm-loading="creating"
      @ok="createExperienceRecord"
      width="560px"
    >
      <a-form layout="vertical" :model="createForm">
        <a-form-item :label="t('common.type')" required>
          <a-input v-model:value="createForm.task_type" :placeholder="t('experience.taskType')" />
        </a-form-item>
        <a-form-item :label="t('common.description')" required>
          <a-textarea v-model:value="createForm.context" :rows="4" />
        </a-form-item>
        <a-form-item :label="t('experience.outcome')">
          <a-select v-model:value="createForm.outcome" style="width: 100%">
            <a-select-option value="success">{{ t('experience.outcomeSuccess') }}</a-select-option>
            <a-select-option value="failure">{{ t('experience.outcomeFailure') }}</a-select-option>
            <a-select-option value="partial">{{ t('experience.outcomePartial') }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="t('growth.lesson') + 's'">
          <a-select v-model:value="createForm.lessons" mode="tags" :placeholder="t('experience.addLessons')" />
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
import * as experienceApi from '@/api/modules/experience'
import type { ExperienceRecord, ExperienceStats } from '@/api/modules/experience'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage({
  onAgentChange: () => {
    fetchAll()
  },
})

const loading = ref(false)
const loadingStats = ref(false)
const loadingRecommendations = ref(false)
const loadingSimilar = ref(false)
const creating = ref(false)
const activeTab = ref('ranking')
const searchQuery = ref('')
const taskTypeFilter = ref<string | undefined>(undefined)

// Stats
const stats = ref<ExperienceStats>({ total_experiences: 0, success_rate: 0, avg_proficiency: 0, top_categories: [] })

// Ranking
const ranking = ref<ExperienceRecord[]>([])
const rankingPage = ref(1)
const rankingSize = ref(15)
const rankingTotal = ref(0)

// Records
const records = ref<ExperienceRecord[]>([])
const recordsPage = ref(1)
const recordsSize = ref(12)
const recordsTotal = ref(0)

// Recommendations
const recommendations = ref<ExperienceRecord[]>([])
const recommendationTaskType = ref('')

// Similar
const similarExperiences = ref<ExperienceRecord[]>([])
const showSimilarModal = ref(false)

// Create form
const showCreateModal = ref(false)
const createForm = ref({
  task_type: '',
  context: '',
  outcome: 'success',
  lessons: [] as string[],
})

// Collect unique task types from records for filter dropdown
const taskTypes = computed(() => {
  const types = new Set<string>()
  records.value.forEach((r) => { if (r.task_type) types.add(r.task_type) })
  ranking.value.forEach((r) => { if (r.task_type) types.add(r.task_type) })
  stats.value.top_categories?.forEach((c) => types.add(c.category))
  return [...types]
})

const formatPercent = (val: number | undefined) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const rankingColumns = computed(() => [
  { title: t('skill.title'), key: 'skill_name', dataIndex: 'task_type' },
  { title: t('experience.successRate'), key: 'success_rate', width: 180 },
  { title: t('experience.experiences'), key: 'experience_count', width: 120 },
  { title: t('experience.proficiency'), key: 'proficiency', width: 160 },
  { title: t('experience.outcome'), key: 'outcome', width: 120 },
])

const recordColumns = computed(() => [
  { title: t('common.type'), key: 'task_type', width: 140 },
  { title: t('common.description'), dataIndex: 'context', key: 'context', ellipsis: true },
  { title: t('experience.outcome'), key: 'outcome', width: 120 },
  { title: t('growth.lesson') + 's', key: 'lessons', width: 90, align: 'center' as const },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
  { title: t('common.actions'), key: 'actions', width: 200 },
])

const filteredRecords = computed(() => {
  if (!searchQuery.value) return records.value
  const q = searchQuery.value.toLowerCase()
  return records.value.filter(
    (r) =>
      (r.task_type || '').toLowerCase().includes(q) ||
      (r.skill_name || '').toLowerCase().includes(q) ||
      (r.context || '').toLowerCase().includes(q),
  )
})

const onRankingTableChange = (pagination: any) => {
  rankingPage.value = pagination.current || 1
  rankingSize.value = pagination.pageSize || 15
  fetchRanking()
}

const onRecordsTableChange = (pagination: any) => {
  recordsPage.value = pagination.current || 1
  recordsSize.value = pagination.pageSize || 12
  fetchExperiences()
}

// --- API calls using experience module ---

const fetchStats = async () => {
  loadingStats.value = true
  try {
    const res = await experienceApi.getExperienceStats(agentId.value)
    const data = res.data
    if (data && typeof data === 'object') {
      stats.value = {
        total_experiences: data.total_experiences ?? 0,
        success_rate: data.success_rate ?? 0,
        avg_proficiency: data.avg_proficiency ?? 0,
        top_categories: data.top_categories ?? [],
      }
    }
  } catch (e: any) {
    console.error('Failed to fetch experience stats:', e?.response?.data?.message || e?.message)
  } finally {
    loadingStats.value = false
  }
}

const fetchRanking = async () => {
  try {
    const res = await experienceApi.getExperienceRanking(agentId.value, {
      page: rankingPage.value,
      size: rankingSize.value,
    })
    const data = res.data
    if (data && typeof data === 'object' && 'items' in data) {
      ranking.value = data.items ?? []
      rankingTotal.value = data.total ?? 0
    } else {
      ranking.value = Array.isArray(data) ? data : []
      rankingTotal.value = ranking.value.length
    }
  } catch (e: any) {
    console.error('Failed to fetch ranking:', e?.response?.data?.message || e?.message)
  }
}

const fetchExperiences = async () => {
  loading.value = true
  try {
    const params: Record<string, any> = {
      page: recordsPage.value,
      size: recordsSize.value,
    }
    if (taskTypeFilter.value) params.task_type = taskTypeFilter.value

    const res = await experienceApi.getExperiences(agentId.value, params)
    const data = res.data
    if (data && typeof data === 'object' && 'items' in data) {
      records.value = data.items ?? []
      recordsTotal.value = data.total ?? 0
    } else {
      records.value = Array.isArray(data) ? data : []
      recordsTotal.value = records.value.length
    }
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const fetchRecommendations = async () => {
  loadingRecommendations.value = true
  try {
    const taskType = recommendationTaskType.value.trim() || 'general'
    const res = await experienceApi.getRecommendations(agentId.value, taskType, 10)
    recommendations.value = Array.isArray(res.data) ? res.data : []
  } catch (e: any) {
    console.error('Failed to fetch recommendations:', e?.response?.data?.message || e?.message)
  } finally {
    loadingRecommendations.value = false
  }
}

const findSimilar = async (record: ExperienceRecord) => {
  showSimilarModal.value = true
  loadingSimilar.value = true
  try {
    const query = record.context || record.task_type || ''
    const res = await experienceApi.searchSimilar(agentId.value, query, 10)
    similarExperiences.value = Array.isArray(res.data) ? res.data : []
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    loadingSimilar.value = false
  }
}

const createExperienceRecord = async () => {
  if (!createForm.value.task_type.trim() || !createForm.value.context.trim()) {
    message.warning(t('validation.required'))
    return
  }
  creating.value = true
  try {
    await experienceApi.createExperience({
      agent_id: agentId.value,
      task_type: createForm.value.task_type,
      context: createForm.value.context,
      outcome: createForm.value.outcome,
      lessons: createForm.value.lessons.length > 0 ? createForm.value.lessons : undefined,
    })
    message.success(t('common.success'))
    showCreateModal.value = false
    createForm.value = { task_type: '', context: '', outcome: 'success', lessons: [] }
    await fetchAll()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  } finally {
    creating.value = false
  }
}

const deleteExperience = async (id: string) => {
  try {
    await experienceApi.deleteExperience(id)
    message.success(t('common.success'))
    await fetchExperiences()
    await fetchStats()
  } catch (e: any) {
    message.error(e?.response?.data?.message || e?.message || t('common.error'))
  }
}

const fetchAll = async () => {
  loading.value = true
  try {
    await Promise.all([fetchStats(), fetchRanking(), fetchExperiences()])
  } finally {
    loading.value = false
  }
  fetchRecommendations()
}

onMounted(() => {
  fetchAll()
})
</script>

<style scoped>
.experience-page {
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

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-item {
  text-align: center;
  padding: 8px 0;
}

.stat-value {
  font-family: var(--nr-font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--nr-text-primary);
  line-height: 1.1;
}

.stat-label {
  font-size: 12px;
  color: var(--nr-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 6px;
}

/* Top categories */
.top-categories {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.category-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.chip-name {
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-transform: capitalize;
}

.tab-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.skill-name {
  font-weight: 600;
  color: var(--nr-text-primary);
}

.rate-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rate-text {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
}

.lessons-count {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
  background: rgba(99, 102, 241, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
}

.row-actions {
  display: flex;
  gap: 8px;
}

/* Recommendations */
.recommendations-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.rec-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rec-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rec-skill {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.rec-text {
  font-size: 13px;
  color: var(--nr-text-secondary);
  line-height: 1.6;
  margin: 0;
}

.rec-lessons {
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
}

.lessons-label {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
}

.rec-lessons ul {
  margin: 0;
  padding-left: 16px;
}

.rec-lessons li {
  font-size: 12px;
  color: var(--nr-text-secondary);
  line-height: 1.4;
}

.rec-confidence {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  font-family: var(--nr-font-mono);
}

/* Similar experiences */
.similar-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.similar-item {
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.similar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.similar-skill {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.similar-content {
  font-size: 13px;
  color: var(--nr-text-secondary);
  line-height: 1.5;
}

.similar-lessons {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.similar-lessons .lessons-label {
  margin-bottom: 0;
  margin-right: 4px;
}

.lesson-chip {
  font-size: 11px;
  color: var(--nr-text-secondary);
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 8px;
  border-radius: 4px;
}

.similar-score {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  font-family: var(--nr-font-mono);
  margin-top: 6px;
}
</style>
