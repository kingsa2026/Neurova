<template>
  <div class="emotion-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('emotion.title') }}</h2>
        <p class="page-subtitle">{{ currentAgent?.name || '' }}</p>
      </div>
      <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchAll">{{ t('common.refresh') }}</GlassButton>
    </div>

    <!-- Current emotion state -->
    <GlassPanel variant="prominent" :glow="true">
      <div class="current-state">
        <div class="emotion-icon">{{ emotionEmoji(currentEmotion.dominant) }}</div>
        <div class="emotion-info">
          <h3 class="emotion-label">{{ t('emotion.analysis') }}</h3>
          <p class="emotion-dominant">{{ currentEmotion.dominant || t('emotion.neutral') }}</p>
          <p class="emotion-intensity">{{ t('emotion.intensity') }} {{ Math.round((currentEmotion.intensity ?? 0) * 100) }}%</p>
        </div>
      </div>
    </GlassPanel>

    <!-- Emotion categories -->
    <a-spin :spinning="loading">
      <div class="categories-grid" style="margin-top: 20px">
        <GlassStatCard
          v-for="cat in categories"
          :key="cat.name"
          :label="cat.name"
          :value="`${Math.round((cat.value ?? 0) * 100)}%`"
          :emoji="emotionEmoji(cat.name)"
        />
      </div>
    </a-spin>

    <!-- Motivation State (NEW - from growth API) -->
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

    <!-- Personality Traits (NEW - from growth API) -->
    <GlassCard :title="t('growth.personality')" style="margin-top: 20px">
      <a-spin :spinning="loadingPersonality">
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
        <a-empty v-else-if="!loadingPersonality" :description="t('common.noData')" />
      </a-spin>
    </GlassCard>

    <!-- Emotion history timeline -->
    <GlassCard :title="t('memory.timeline')" style="margin-top: 20px">
      <a-spin :spinning="loading">
        <a-timeline>
          <a-timeline-item v-for="entry in history" :key="entry.id" :color="timelineColor(entry.emotion)">
            <div class="timeline-entry">
              <div class="timeline-header">
                <span class="timeline-emotion">{{ emotionEmoji(entry.emotion) }} {{ entry.emotion }}</span>
                <span class="timeline-time">{{ formatTime(entry.timestamp) }}</span>
              </div>
              <p v-if="entry.context" class="timeline-context">{{ entry.context }}</p>
              <a-progress :percent="Math.round((entry.intensity ?? 0) * 100)" size="small" :stroke-color="timelineColor(entry.emotion)" />
            </div>
          </a-timeline-item>
        </a-timeline>
        <a-empty v-if="!history.length && !loading" :description="t('common.noData')" />
      </a-spin>
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import * as growthApi from '@/api/modules/growth'
import type { MotivationState, PersonalityProfile } from '@/api/modules/growth'
import { request } from '@/api'

const { t } = useI18n()
const { agentId, currentAgent } = useAgentPage()

const loading = ref(false)
const loadingMotivation = ref(false)
const loadingPersonality = ref(false)

// Emotion state (from memory/emotion endpoint)
const currentEmotion = ref<Record<string, any>>({})
const categories = ref<any[]>([])
const history = ref<any[]>([])

// Motivation state (from growth API)
const motivationData = ref<MotivationState | null>(null)

// Personality state (from growth API)
const personalityProfile = ref<PersonalityProfile | null>(null)
const personalityTraits = ref<{ name: string; value: number }[]>([])

const emotionEmoji = (emotion: string) => {
  const map: Record<string, string> = {
    happy: '\u{1F60A}', sad: '\u{1F622}', angry: '\u{1F620}', fearful: '\u{1F628}',
    surprised: '\u{1F632}', disgusted: '\u{1F922}', neutral: '\u{1F610}',
    excited: '\u{1F929}', anxious: '\u{1F630}', content: '\u{1F60C}',
    frustrated: '\u{1F624}', curious: '\u{1F914}',
  }
  return map[emotion?.toLowerCase()] || '\u{1F610}'
}

const timelineColor = (emotion: string) => {
  const map: Record<string, string> = {
    happy: 'green', sad: 'blue', angry: 'red', fearful: 'orange',
    surprised: 'purple', neutral: 'gray', excited: 'green',
  }
  return map[emotion?.toLowerCase()] || 'gray'
}

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const formatPercent = (val: number | undefined) =>
  val !== undefined && val !== null ? `${Math.round(val * 100)}%` : '-'

const traitColor = (val: number) => {
  if (val >= 0.7) return '#10b981'
  if (val >= 0.4) return '#6366f1'
  return '#f59e0b'
}

const fetchEmotion = async () => {
  loading.value = true
  try {
    const res: any = await request.get(`/memory/emotion?agent_id=${agentId.value}`)
    const data = res?.data ?? res ?? {}
    currentEmotion.value = data.current ?? data.state ?? {}
    categories.value = data.categories ?? data.emotions ?? Object.entries(currentEmotion.value.scores ?? {}).map(([name, value]) => ({ name, value }))
    history.value = data.history ?? data.timeline ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
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

const fetchPersonality = async () => {
  loadingPersonality.value = true
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
    loadingPersonality.value = false
  }
}

const fetchAll = async () => {
  await Promise.all([fetchEmotion(), fetchMotivation(), fetchPersonality()])
}

onMounted(fetchAll)
</script>

<style scoped>
.emotion-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.page-subtitle { margin: 4px 0 0; color: var(--nr-text-secondary); font-size: 13px; }
.current-state { display: flex; align-items: center; gap: 20px; }
.emotion-icon { font-size: 48px; }
.emotion-info { display: flex; flex-direction: column; gap: 4px; }
.emotion-label { font-size: 12px; color: var(--nr-text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; margin: 0; }
.emotion-dominant { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); margin: 0; text-transform: capitalize; }
.emotion-intensity { font-size: 13px; color: var(--nr-text-secondary); margin: 0; }
.categories-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.timeline-entry { display: flex; flex-direction: column; gap: 4px; }
.timeline-header { display: flex; justify-content: space-between; align-items: center; }
.timeline-emotion { font-weight: 500; color: var(--nr-text-primary); text-transform: capitalize; }
.timeline-time { font-size: 11px; color: var(--nr-text-muted); font-family: var(--nr-font-mono); }
.timeline-context { font-size: 12px; color: var(--nr-text-tertiary); margin: 0; }

/* Motivation section */
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
.factor-value.positive { color: #10b981; }
.factor-value.negative { color: #ef4444; }

/* Personality traits chart */
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
</style>
