<template>
  <GlassPanel variant="default" :radius="18" padding="20px 24px" :glow="hovering" @mouseenter="hovering = true" @mouseleave="hovering = false">
    <div class="nr-stat-card">
      <div class="nr-stat-header">
        <div class="nr-stat-icon" :style="{ background: iconBg }">
          <component :is="icon" v-if="icon" />
          <span v-else>{{ emoji }}</span>
        </div>
        <span v-if="trend !== undefined" class="nr-stat-trend" :class="trendClass">
          {{ trend > 0 ? '+' : '' }}{{ trend }}%
        </span>
      </div>
      <div class="nr-stat-value">{{ displayValue }}</div>
      <div class="nr-stat-label">{{ label }}</div>
      <div v-if="sparkData" class="nr-stat-spark">
        <svg :viewBox="`0 0 ${sparkW} ${sparkH}`" preserveAspectRatio="none">
          <defs>
            <linearGradient :id="gradId" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" :stop-color="sparkColor" stop-opacity="0.3" />
              <stop offset="100%" :stop-color="sparkColor" stop-opacity="0" />
            </linearGradient>
          </defs>
          <path :d="areaPath" :fill="`url(#${gradId})`" />
          <path :d="linePath" fill="none" :stroke="sparkColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
      </div>
    </div>
  </GlassPanel>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import GlassPanel from './GlassPanel.vue'

const props = withDefaults(defineProps<{
  label: string
  value: string | number
  icon?: object
  emoji?: string
  trend?: number
  sparkData?: number[]
  sparkColor?: string
}>(), {
  sparkColor: '#6366f1',
})

const hovering = ref(false)
const sparkW = 120
const sparkH = 32
const gradId = `spark-${Math.random().toString(36).slice(2, 8)}`

const displayValue = computed(() => typeof props.value === 'number' ? props.value.toLocaleString() : props.value)

const iconBg = computed(() => {
  if (props.trend !== undefined) {
    return props.trend >= 0 ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)'
  }
  return 'rgba(99,102,241,0.12)'
})

const trendClass = computed(() => props.trend !== undefined ? (props.trend >= 0 ? 'trend-up' : 'trend-down') : '')

const linePath = computed(() => {
  if (!props.sparkData?.length) return ''
  const max = Math.max(...props.sparkData)
  const min = Math.min(...props.sparkData)
  const range = max - min || 1
  const step = sparkW / (props.sparkData.length - 1)
  return props.sparkData.map((v, i) => {
    const x = i * step
    const y = sparkH - ((v - min) / range) * (sparkH - 4) - 2
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})

const areaPath = computed(() => {
  if (!linePath.value) return ''
  return `${linePath.value} L${sparkW},${sparkH} L0,${sparkH} Z`
})
</script>

<style scoped>
.nr-stat-card { display: flex; flex-direction: column; gap: 8px; }
.nr-stat-header { display: flex; justify-content: space-between; align-items: center; }
.nr-stat-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; color: var(--nr-primary-light);
}
.nr-stat-trend {
  font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 6px;
  font-family: var(--nr-font-mono);
}
.trend-up { color: #10b981; background: rgba(16,185,129,0.1); }
.trend-down { color: #ef4444; background: rgba(239,68,68,0.1); }
.nr-stat-value {
  font-family: var(--nr-font-display); font-size: 28px; font-weight: 700;
  letter-spacing: -0.03em; color: var(--nr-text-primary); line-height: 1.1;
}
.nr-stat-label { font-size: 12px; color: var(--nr-text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; }
.nr-stat-spark { height: 32px; margin-top: 4px; }
.nr-stat-spark svg { width: 100%; height: 100%; }
</style>
