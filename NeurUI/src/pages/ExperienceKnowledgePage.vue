<template>
  <div class="experience-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('nav.experience') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <GlassButton variant="secondary" :loading="loading" @click="fetchAll">
        {{ t('common.refresh') }}
      </GlassButton>
    </div>

    <!-- Stats overview -->
    <div class="stats-grid">
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ stats.total_experiences || 0 }}</div>
          <div class="stat-label">{{ t('common.total') }}</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ stats.unique_skills || 0 }}</div>
          <div class="stat-label">{{ t('skill.title') }}</div>
        </div>
      </GlassCard>
      <GlassCard variant="subtle">
        <div class="stat-item">
          <div class="stat-value">{{ formatPercent(stats.overall_success_rate) }}</div>
          <div class="stat-label">Success Rate</div>
        </div>
      </GlassCard>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- Skill Ranking Tab -->
      <a-tab-pane key="ranking" :tab="t('skill.stats')">
        <a-spin :spinning="loading">
          <GlassCard>
            <a-table
              :columns="rankingColumns"
              :data-source="ranking"
              :pagination="{ pageSize: 15, showSizeChanger: true }"
              row-key="skill_name"
              size="middle"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'skill_name'">
                  <span class="skill-name">{{ record.skill_name }}</span>
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
            </div>

            <a-table
              :columns="recordColumns"
              :data-source="filteredRecords"
              :pagination="{ pageSize: 12 }"
              row-key="id"
              size="middle"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'outcome'">
                  <a-tag :color="record.outcome === 'success' ? 'green' : record.outcome === 'failure' ? 'red' : 'default'">
                    {{ record.outcome || 'unknown' }}
                  </a-tag>
                </template>
                <template v-else-if="column.key === 'actions'">
                  <GlassButton size="sm" variant="ghost" @click="findSimilar(record)">
                    Find Similar
                  </GlassButton>
                </template>
              </template>
            </a-table>
          </GlassCard>
        </a-spin>
      </a-tab-pane>

      <!-- Recommendations Tab -->
      <a-tab-pane key="recommendations" tab="Recommendations">
        <a-spin :spinning="loadingRecommendations">
          <div v-if="recommendations.length > 0" class="recommendations-grid">
            <GlassCard v-for="rec in recommendations" :key="rec.id" variant="subtle">
              <div class="rec-item">
                <div class="rec-header">
                  <a-tag :color="rec.priority === 'high' ? 'red' : rec.priority === 'medium' ? 'orange' : 'blue'">
                    {{ rec.priority || 'info' }}
                  </a-tag>
                  <span class="rec-skill">{{ rec.skill_name }}</span>
                </div>
                <p class="rec-text">{{ rec.recommendation || rec.content }}</p>
                <div v-if="rec.confidence" class="rec-confidence">
                  Confidence: {{ formatPercent(rec.confidence) }}
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
      title="Similar Experiences"
      :footer="null"
      width="640px"
    >
      <a-spin :spinning="loadingSimilar">
        <div v-if="similarExperiences.length > 0" class="similar-list">
          <div v-for="sim in similarExperiences" :key="sim.id" class="similar-item">
            <div class="similar-header">
              <span class="similar-skill">{{ sim.skill_name }}</span>
              <a-tag :color="sim.outcome === 'success' ? 'green' : 'red'">{{ sim.outcome }}</a-tag>
            </div>
            <div class="similar-content">{{ sim.content || sim.description }}</div>
            <div v-if="sim.similarity" class="similar-score">
              Similarity: {{ formatPercent(sim.similarity) }}
            </div>
          </div>
        </div>
        <a-empty v-else :description="t('common.noData')" />
      </a-spin>
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

const loading = ref(false)
const loadingRecommendations = ref(false)
const loadingSimilar = ref(false)
const activeTab = ref('ranking')
const searchQuery = ref('')

const stats = ref<any>({})
const ranking = ref<any[]>([])
const records = ref<any[]>([])
const recommendations = ref<any[]>([])
const similarExperiences = ref<any[]>([])
const showSimilarModal = ref(false)

const formatPercent = (val: number | undefined) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const rankingColumns = computed(() => [
  { title: t('skill.title'), key: 'skill_name', dataIndex: 'skill_name' },
  { title: 'Success Rate', key: 'success_rate', width: 180 },
  { title: 'Experiences', key: 'experience_count', width: 120 },
  { title: 'Proficiency', key: 'proficiency', width: 160 },
])

const recordColumns = computed(() => [
  { title: t('skill.title'), dataIndex: 'skill_name', key: 'skill_name', width: 160 },
  { title: t('common.description'), dataIndex: 'description', key: 'description', ellipsis: true },
  { title: 'Outcome', key: 'outcome', width: 120 },
  { title: t('common.createdAt'), dataIndex: 'created_at', width: 180 },
  { title: t('common.actions'), key: 'actions', width: 140 },
])

const filteredRecords = computed(() => {
  if (!searchQuery.value) return records.value
  const q = searchQuery.value.toLowerCase()
  return records.value.filter(
    (r) =>
      (r.skill_name || '').toLowerCase().includes(q) ||
      (r.description || '').toLowerCase().includes(q),
  )
})

const fetchStats = async () => {
  try {
    const res: any = await request.get('/experience/stats', {
      params: { agent_id: agentId.value },
    })
    const data = res?.data ?? res
    stats.value = data?.stats ?? data ?? {}
    records.value = data?.records ?? data?.items ?? []
  } catch (e: any) {
    console.error('Failed to fetch experience stats:', e)
  }
}

const fetchRanking = async () => {
  try {
    const res: any = await request.get('/experience/ranking', {
      params: { agent_id: agentId.value },
    })
    const data = res?.data ?? res
    ranking.value = Array.isArray(data) ? data : data?.items ?? data?.ranking ?? []
  } catch (e: any) {
    console.error('Failed to fetch ranking:', e)
  }
}

const fetchRecommendations = async () => {
  loadingRecommendations.value = true
  try {
    const res: any = await request.get('/experience/recommendations', {
      params: { agent_id: agentId.value },
    })
    const data = res?.data ?? res
    recommendations.value = Array.isArray(data) ? data : data?.items ?? data?.recommendations ?? []
  } catch (e: any) {
    console.error('Failed to fetch recommendations:', e)
  } finally {
    loadingRecommendations.value = false
  }
}

const findSimilar = async (record: any) => {
  showSimilarModal.value = true
  loadingSimilar.value = true
  try {
    const res: any = await request.get(`/experience/${record.id}/similar`, {
      params: { agent_id: agentId.value },
    })
    const data = res?.data ?? res
    similarExperiences.value = Array.isArray(data) ? data : data?.items ?? data?.similar ?? []
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loadingSimilar.value = false
  }
}

const fetchAll = async () => {
  loading.value = true
  try {
    await Promise.all([fetchStats(), fetchRanking()])
  } finally {
    loading.value = false
  }
  fetchRecommendations()
}

onMounted(() => {
  fetchAll()
  fetchRecommendations()
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
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

.toolbar {
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

.rec-confidence {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  font-family: var(--nr-font-mono);
}

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

.similar-score {
  font-size: 11px;
  color: var(--nr-text-tertiary);
  font-family: var(--nr-font-mono);
  margin-top: 6px;
}
</style>
