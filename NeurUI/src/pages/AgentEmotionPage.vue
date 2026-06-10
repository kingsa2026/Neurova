<template>
  <div class="emotion-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('emotion.title') }}</h2>
      <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchEmotion">{{ t('common.refresh') }}</GlassButton>
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
import { useRoute } from 'vue-router'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()
const route = useRoute()

const agentId = route.params.agentId as string
const loading = ref(false)
const currentEmotion = ref<Record<string, any>>({})
const categories = ref<any[]>([])
const history = ref<any[]>([])

const emotionEmoji = (emotion: string) => {
  const map: Record<string, string> = {
    happy: '😊', sad: '😢', angry: '😠', fearful: '😨',
    surprised: '😲', disgusted: '🤢', neutral: '😐',
    excited: '🤩', anxious: '😰', content: '😌',
    frustrated: '😤', curious: '🤔',
  }
  return map[emotion?.toLowerCase()] || '😐'
}

const timelineColor = (emotion: string) => {
  const map: Record<string, string> = {
    happy: 'green', sad: 'blue', angry: 'red', fearful: 'orange',
    surprised: 'purple', neutral: 'gray', excited: 'green',
  }
  return map[emotion?.toLowerCase()] || 'gray'
}

const formatTime = (ts: string) => ts ? new Date(ts).toLocaleString() : ''

const fetchEmotion = async () => {
  loading.value = true
  try {
    const res: any = await request.get(`/memory/emotion?agent_id=${agentId}`)
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

onMounted(fetchEmotion)
</script>

<style scoped>
.emotion-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
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
</style>
