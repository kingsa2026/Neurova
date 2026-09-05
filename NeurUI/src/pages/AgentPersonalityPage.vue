<template>
  <div class="personality-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('nav.persona') }}</h2>
      <GlassButton variant="ghost" size="sm" :loading="refreshing" @click="refreshAll">{{ t('common.refresh') }}</GlassButton>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <!-- 情绪页签（原情绪页内容迁入） -->
      <a-tab-pane key="emotion" :tab="t('nav.emotion')">
        <!-- Current emotion state -->
        <GlassPanel variant="prominent" :glow="true">
          <div class="current-state">
            <div class="emotion-icon">{{ emotionEmoji(currentEmotion.dominant || '') }}</div>
            <div class="emotion-info">
              <h3 class="emotion-label">{{ t('emotion.analysis') }}</h3>
              <p class="emotion-dominant">{{ emotionLabel(currentEmotion.dominant) || t('emotion.neutral') }}</p>
              <p class="emotion-intensity">
                {{ t('emotion.share') }}{{ Math.round((currentEmotion.shared ?? 0) * 100) }}% · {{ totalAnnotated }} {{ t('emotion.entries') }}
              </p>
            </div>
          </div>
        </GlassPanel>

        <!-- Emotion categories -->
        <a-spin :spinning="loadingEmotion">
          <div class="categories-grid" style="margin-top: 20px">
            <GlassStatCard
              v-for="cat in categories"
              :key="cat.name"
              :label="emotionLabel(cat.name)"
              :value="`${Math.round((cat.value ?? 0) * 100)}%`"
              :emoji="emotionEmoji(cat.name)"
            />
          </div>
          <a-empty v-if="!categories.length && !loadingEmotion" :description="t('common.noData')" style="margin-top: 20px" />
        </a-spin>

        <!-- Motivation State (from growth API) -->
        <GlassCard :title="t('growth.motivation')" style="margin-top: 20px">
          <a-spin :spinning="loadingMotivation">
            <div v-if="motivationData" class="motivation-section">
              <div class="motivation-overview">
                <div class="motivation-level">
                  <div class="big-value">{{ formatPercent(motivationData.level) }}</div>
                  <a-progress
                    :percent="Math.round((motivationData.level || 0) * 100)"
                    :stroke-color="motivationData.level >= 0.7 ? '#10b981' : motivationData.level >= 0.4 ? '#f59e0b' : '#ef4444'"
                    :show-info="false"
                  />
                </div>
              </div>
              <div v-if="motivationData.factors?.length" class="factors-grid">
                <div v-for="factor in motivationData.factors" :key="factor.name" class="factor-card">
                  <div class="factor-header">
                    <span class="factor-name">{{ factor.name }}</span>
                    <span class="factor-value" :class="{ positive: factor.impact > 0, negative: factor.impact < 0 }">
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
              <div v-if="motivationData.updated_at" class="meta-timestamp">
                {{ t('common.updated') }}: {{ formatTime(motivationData.updated_at) }}
              </div>
            </div>
            <a-empty v-else-if="!loadingMotivation" :description="t('common.noData')" />
          </a-spin>
        </GlassCard>

        <!-- Personality Traits (from growth API) -->
        <GlassCard :title="t('growth.personality')" style="margin-top: 20px">
          <a-spin :spinning="loadingProfile">
            <div v-if="personalityTraits.length > 0" class="personality-section">
              <!-- Visual bar chart -->
              <div class="traits-chart">
                <div v-for="trait in personalityTraits" :key="trait.name" class="trait-bar-row">
                  <div class="trait-bar-label">{{ trait.name }}</div>
                  <div class="trait-bar-track">
                    <div
                      class="trait-bar-fill"
                      :style="{ width: `${Math.round((trait.value || 0) * 100)}%`, backgroundColor: traitColor(trait.value) }"
                    ></div>
                  </div>
                  <div class="trait-bar-value">{{ formatPercent(trait.value) }}</div>
                </div>
              </div>
              <div v-if="personalityProfile?.style || personalityProfile?.tone" class="personality-meta">
                <a-tag v-if="personalityProfile?.style">{{ t('growth.personality') }}: {{ personalityProfile.style }}</a-tag>
                <a-tag v-if="personalityProfile?.tone" color="purple">{{ t('emotion.title') }}: {{ personalityProfile.tone }}</a-tag>
                <span v-if="personalityProfile?.updated_at" class="meta-timestamp">
                  {{ t('common.updated') }}: {{ formatTime(personalityProfile.updated_at) }}
                </span>
              </div>
            </div>
            <a-empty v-else-if="!loadingProfile" :description="t('common.noData')" />
          </a-spin>
        </GlassCard>
      </a-tab-pane>

      <!-- 个性页签（原个性页内容） -->
      <a-tab-pane key="personality" :tab="t('nav.personality')">
        <div class="tab-toolbar">
          <GlassButton variant="secondary" size="sm" :loading="evolving" @click="evolvePersonality">{{ t('growth.evolve') }}</GlassButton>
        </div>

        <a-spin :spinning="loading">
          <div class="personality-grid">
            <!-- Radar chart area -->
            <GlassCard :title="t('growth.personality')">
              <div class="radar-area">
                <svg viewBox="0 0 300 300" class="radar-svg">
                  <g v-for="(level, i) in [0.2, 0.4, 0.6, 0.8, 1.0]" :key="i">
                    <polygon :points="polygonPoints(level)" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="0.5" />
                  </g>
                  <line v-for="(trait, i) in traitList" :key="'axis-' + i"
                    x1="150" y1="150"
                    :x2="150 + 120 * Math.cos((2 * Math.PI * i) / traitList.length - Math.PI / 2)"
                    :y2="150 + 120 * Math.sin((2 * Math.PI * i) / traitList.length - Math.PI / 2)"
                    stroke="rgba(255,255,255,0.06)" stroke-width="0.5" />
                  <polygon :points="dataPolygonPoints" fill="rgba(99,102,241,0.2)" stroke="#6366f1" stroke-width="1.5" />
                  <circle v-for="(trait, i) in traitList" :key="'dot-' + i"
                    :cx="150 + 120 * (trait.value ?? 0.5) * Math.cos((2 * Math.PI * i) / traitList.length - Math.PI / 2)"
                    :cy="150 + 120 * (trait.value ?? 0.5) * Math.sin((2 * Math.PI * i) / traitList.length - Math.PI / 2)"
                    r="3" fill="#6366f1" />
                  <text v-for="(trait, i) in traitList" :key="'label-' + i"
                    :x="150 + 140 * Math.cos((2 * Math.PI * i) / traitList.length - Math.PI / 2)"
                    :y="150 + 140 * Math.sin((2 * Math.PI * i) / traitList.length - Math.PI / 2)"
                    text-anchor="middle" dominant-baseline="middle" fill="var(--nr-text-secondary)" font-size="10">
                    {{ t('personality.' + trait.key) }}
                  </text>
                </svg>
              </div>
            </GlassCard>

            <!-- Traits list with sliders -->
            <GlassCard :title="t('growth.traits')">
              <div class="traits-list">
                <div v-for="trait in traitList" :key="trait.key" class="trait-row">
                  <span class="trait-name">{{ t('personality.' + trait.key) }}</span>
                  <a-slider v-model:value="trait.percent" :min="0" :max="100" :disabled="!editing" style="flex: 1" />
                  <span class="trait-value">{{ trait.percent }}%</span>
                </div>
              </div>
              <template #footer>
                <div class="traits-footer">
                  <GlassButton v-if="!editing" variant="secondary" size="sm" @click="editing = true">{{ t('common.edit') }}</GlassButton>
                  <template v-else>
                    <GlassButton variant="ghost" size="sm" @click="editing = false">{{ t('common.cancel') }}</GlassButton>
                    <GlassButton variant="primary" size="sm" :loading="saving" @click="savePersonality">{{ t('common.save') }}</GlassButton>
                  </template>
                </div>
              </template>
            </GlassCard>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import { useAgentPage } from '@/composables/useAgentPage'
import * as growthApi from '@/api/modules/growth'
import type { MotivationState, PersonalityProfile } from '@/api/modules/growth'
import { getEmotionSummary } from '@/api/modules/memory'

const { t } = useI18n()
const { agentId } = useAgentPage()

const activeTab = ref('emotion')
const refreshing = ref(false)

// --- 情绪页签状态 ---
const loadingEmotion = ref(false)
const loadingMotivation = ref(false)
const loadingProfile = ref(false)

// Emotion stats (from /memory/emotion/summary -> { total_annotated, emotion_distribution, emotion_weight })
const currentEmotion = ref<{ dominant?: string; shared?: number }>({})
const categories = ref<{ name: string; count: number; value: number }[]>([])
const totalAnnotated = ref(0)

// Motivation state (from growth API)
const motivationData = ref<MotivationState | null>(null)

// Personality overview (from growth API)
const personalityProfile = ref<PersonalityProfile | null>(null)
const personalityTraits = ref<{ name: string; value: number }[]>([])

// --- 个性页签状态 ---
const loading = ref(false)
const saving = ref(false)
const evolving = ref(false)
const editing = ref(false)

const traitList = ref<{ key: string; value: number; percent: number }[]>([
  { key: 'openness', value: 0.7, percent: 70 },
  { key: 'conscientiousness', value: 0.6, percent: 60 },
  { key: 'extraversion', value: 0.5, percent: 50 },
  { key: 'agreeableness', value: 0.8, percent: 80 },
  { key: 'neuroticism', value: 0.3, percent: 30 },
  { key: 'creativity', value: 0.65, percent: 65 },
])

// 类型映射对齐后端 EmotionType 枚举（17 类：8 核心 + 9 扩展）
const emotionEmoji = (emotion?: string) => {
  const map: Record<string, string> = {
    joy: '\u{1F60A}', sadness: '\u{1F622}', anger: '\u{1F620}', fear: '\u{1F628}',
    surprise: '\u{1F632}', disgust: '\u{1F922}', trust: '\u{1F91D}', anticipation: '\u{1F929}',
    neutral: '\u{1F610}',
    confusion: '\u{1F635}', frustration: '\u{1F624}', love: '\u{1F970}', gratitude: '\u{1F979}',
    nostalgia: '\u{1F97A}', anxiety: '\u{1F630}', pride: '\u{1F60E}', shame: '\u{1F633}',
    empathy: '\u{1F917}',
  }
  return map[emotion?.toLowerCase() ?? ''] || '\u{1F610}'
}

const emotionLabel = (emotion?: string) => {
  if (!emotion) return ''
  const key = `emotion.${emotion.toLowerCase()}`
  return t(key) !== key ? t(key) : emotion
}

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const formatPercent = (val: number | undefined) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const traitColor = (val: number) => {
  if (val >= 0.7) return '#10b981'
  if (val >= 0.4) return '#6366f1'
  return '#f59e0b'
}

const polygonPoints = (level: number) => {
  const n = traitList.value.length
  return Array.from({ length: n }, (_, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2
    return `${150 + 120 * level * Math.cos(angle)},${150 + 120 * level * Math.sin(angle)}`
  }).join(' ')
}

const dataPolygonPoints = computed(() => {
  const n = traitList.value.length
  return Array.from({ length: n }, (_, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2
    const v = traitList.value[i].value ?? 0.5
    return `${150 + 120 * v * Math.cos(angle)},${150 + 120 * v * Math.sin(angle)}`
  }).join(' ')
})

// --- 情绪页签取数 ---
const fetchEmotion = async () => {
  loadingEmotion.value = true
  try {
    const env: any = await getEmotionSummary(agentId.value)
    const data = (env?.data ?? {}) as {
      total_annotated?: number
      emotion_distribution?: Record<string, number>
      emotion_weight?: number
    }
    totalAnnotated.value = data.total_annotated ?? 0
    const distribution = Object.entries(data.emotion_distribution ?? {}).sort((a, b) => b[1] - a[1])
    categories.value = distribution.map(([name, count]) => ({
      name,
      count,
      value: totalAnnotated.value > 0 ? count / totalAnnotated.value : 0,
    }))
    currentEmotion.value = distribution.length
      ? { dominant: distribution[0][0], shared: distribution[0][1] / (totalAnnotated.value || 1) }
      : {}
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingEmotion.value = false
  }
}

const fetchMotivation = async () => {
  loadingMotivation.value = true
  try {
    const res = await growthApi.getMotivation(agentId.value)
    motivationData.value = res.data ?? null
  } catch (e: any) {
    console.error('Failed to fetch motivation:', e?.response?.data?.message || e?.message)
  } finally {
    loadingMotivation.value = false
  }
}

const fetchEmotionProfile = async () => {
  loadingProfile.value = true
  try {
    const res = await growthApi.getPersonality(agentId.value)
    personalityProfile.value = res.data ?? null
    const traits = res.data?.traits
    if (traits && typeof traits === 'object') {
      personalityTraits.value = Object.entries(traits)
        .map(([name, value]) => ({ name, value: value as number }))
        .sort((a, b) => b.value - a.value)
    }
  } catch (e: any) {
    console.error('Failed to fetch personality:', e?.response?.data?.message || e?.message)
  } finally {
    loadingProfile.value = false
  }
}

// --- 个性页签取数/编辑 ---
const fetchPersonality = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/growth/personality')
    const data = res?.data ?? res ?? {}
    const traits = data.traits ?? data.profile ?? {}
    if (typeof traits === 'object' && !Array.isArray(traits)) {
      traitList.value = traitList.value.map(t => {
        const val = traits[t.key] ?? t.value
        return { ...t, value: val, percent: Math.round(val * 100) }
      })
    }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const savePersonality = async () => {
  saving.value = true
  try {
    const traits: Record<string, number> = {}
    traitList.value.forEach(t => { traits[t.key] = t.percent / 100 })
    await request.put('/growth/personality', { traits })
    message.success(t('common.success'))
    editing.value = false
    traitList.value = traitList.value.map(t => ({ ...t, value: t.percent / 100 }))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

const evolvePersonality = async () => {
  evolving.value = true
  try {
    await request.post('/growth/personality/evolve')
    message.success(t('common.success'))
    await Promise.all([fetchPersonality(), fetchEmotionProfile()])
  } catch {
    message.error(t('common.error'))
  } finally {
    evolving.value = false
  }
}

const refreshAll = async () => {
  refreshing.value = true
  try {
    await Promise.all([fetchEmotion(), fetchMotivation(), fetchEmotionProfile(), fetchPersonality()])
  } finally {
    refreshing.value = false
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.personality-page { display: flex; flex-direction: column; gap: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.tab-toolbar { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 16px; }

/* 情绪页签 */
.current-state { display: flex; align-items: center; gap: 20px; }
.emotion-icon { font-size: 48px; }
.emotion-info { display: flex; flex-direction: column; gap: 4px; }
.emotion-label { font-size: 12px; color: var(--nr-text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; margin: 0; }
.emotion-dominant { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); margin: 0; text-transform: capitalize; }
.emotion-intensity { font-size: 13px; color: var(--nr-text-secondary); margin: 0; }
.categories-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }

.motivation-section { display: flex; flex-direction: column; gap: 16px; }
.motivation-overview { display: flex; align-items: center; gap: 20px; }
.motivation-level { flex: 1; }
.motivation-level .big-value {
  font-family: var(--nr-font-display);
  font-size: 32px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin-bottom: 8px;
}
.factors-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.factor-card {
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.factor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.factor-name {
  font-size: 12px;
  color: var(--nr-text-secondary);
  text-transform: capitalize;
}
.factor-value {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  font-weight: 600;
}
.factor-value.positive { color: var(--nr-success); }
.factor-value.negative { color: var(--nr-error); }

.personality-section { display: flex; flex-direction: column; gap: 16px; }
.traits-chart { display: flex; flex-direction: column; gap: 12px; }
.trait-bar-row {
  display: grid;
  grid-template-columns: 120px 1fr 50px;
  align-items: center;
  gap: 12px;
}
.trait-bar-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--nr-text-primary);
  text-transform: capitalize;
  text-align: right;
}
.trait-bar-track {
  height: 8px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px;
  overflow: hidden;
}
.trait-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.4s ease;
}
.trait-bar-value {
  font-size: 12px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
  text-align: right;
}
.personality-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.meta-timestamp {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
}

/* 个性页签：两卡左右分区（窄屏回退单列） */
.personality-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
@media (max-width: 1100px) {
  .personality-grid { grid-template-columns: 1fr; }
}

.radar-area { display: flex; justify-content: center; padding: 16px; }
.radar-svg { width: 300px; height: 300px; }
.traits-list { display: flex; flex-direction: column; gap: 12px; }
.trait-row { display: flex; align-items: center; gap: 16px; }
.trait-name { width: 160px; font-size: 13px; font-weight: 500; color: var(--nr-text-primary); }
.trait-value { width: 40px; font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); text-align: right; }
.traits-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
