<template>
  <div class="personality-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('emotion.personality') }}</h2>
      <div class="header-actions">
        <GlassButton variant="secondary" size="sm" :loading="evolving" @click="evolvePersonality">{{ t('growth.evolve') }}</GlassButton>
        <GlassButton variant="ghost" size="sm" :loading="loading" @click="fetchPersonality">{{ t('common.refresh') }}</GlassButton>
      </div>
    </div>

    <a-spin :spinning="loading">
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
              {{ trait.name }}
            </text>
          </svg>
        </div>
      </GlassCard>

      <!-- Traits list with sliders -->
      <GlassCard :title="t('growth.traits')" style="margin-top: 20px">
        <div class="traits-list">
          <div v-for="trait in traitList" :key="trait.key" class="trait-row">
            <span class="trait-name">{{ trait.name }}</span>
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
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const evolving = ref(false)
const editing = ref(false)

const traitList = ref<{ key: string; name: string; value: number; percent: number }[]>([
  { key: 'openness', name: 'Openness', value: 0.7, percent: 70 },
  { key: 'conscientiousness', name: 'Conscientiousness', value: 0.6, percent: 60 },
  { key: 'extraversion', name: 'Extraversion', value: 0.5, percent: 50 },
  { key: 'agreeableness', name: 'Agreeableness', value: 0.8, percent: 80 },
  { key: 'neuroticism', name: 'Neuroticism', value: 0.3, percent: 30 },
  { key: 'creativity', name: 'Creativity', value: 0.65, percent: 65 },
])

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
    await fetchPersonality()
  } catch {
    message.error(t('common.error'))
  } finally {
    evolving.value = false
  }
}

onMounted(fetchPersonality)
</script>

<style scoped>
.personality-page { display: flex; flex-direction: column; gap: 20px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; gap: 8px; }
.radar-area { display: flex; justify-content: center; padding: 16px; }
.radar-svg { width: 300px; height: 300px; }
.traits-list { display: flex; flex-direction: column; gap: 12px; }
.trait-row { display: flex; align-items: center; gap: 16px; }
.trait-name { width: 160px; font-size: 13px; font-weight: 500; color: var(--nr-text-primary); }
.trait-value { width: 40px; font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); text-align: right; }
.traits-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
