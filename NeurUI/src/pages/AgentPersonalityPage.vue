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

        <!-- 情绪变化时间轴：效价带符号（正=积极），空桶画断点，悬停看触发事件 -->
        <GlassCard :title="t('emotion.timelineTitle')" style="margin-top: 20px">
          <div class="timeline-toolbar">
            <span class="timeline-hint">{{ t('emotion.timelineAxisHint') }}</span>
            <a-radio-group v-model:value="timelineRange" size="small">
              <a-radio-button value="24h">{{ t('emotion.range24h') }}</a-radio-button>
              <a-radio-button value="7d">{{ t('emotion.range7d') }}</a-radio-button>
              <a-radio-button value="30d">{{ t('emotion.range30d') }}</a-radio-button>
              <a-radio-button value="90d">{{ t('emotion.range90d') }}</a-radio-button>
            </a-radio-group>
          </div>
          <a-spin :spinning="loadingTimeline">
            <VChart :option="emotionTimelineOption" autoresize class="timeline-chart" />
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
              <!-- 空态引导：服务端从未持久化 traits（2026-09-16）；旧实现用内置默认值冒充档案 -->
              <div v-if="hasServerTraits === false" class="traits-empty-guide">
                <p class="traits-empty-hint">{{ t('personality.emptyHint') }}</p>
                <GlassButton variant="primary" size="sm" :loading="savingDefaults" @click="writeDefaultTraits">{{ t('personality.emptyAction') }}</GlassButton>
              </div>
              <div v-else>
                <div class="traits-list">
                  <div v-for="trait in traitList" :key="trait.key" class="trait-row">
                    <span class="trait-name">{{ t('personality.' + trait.key) }}</span>
                    <a-slider v-model:value="trait.percent" :min="0" :max="100" :disabled="!editing" style="flex: 1" />
                    <span class="trait-value">{{ trait.percent }}%</span>
                  </div>
                </div>
                <div v-if="verifyFailed" class="traits-verify-tip">{{ verifyFailed }}</div>
              </div>
              <template #footer>
                <div v-if="hasServerTraits === false" class="traits-footer traits-footer-empty"></div>
                <div v-else class="traits-footer">
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
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { request } from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useEnumLabel } from '@/composables/useEnumLabel'
import { getEmotionSummary, getEmotionTimeline } from '@/api/modules/memory'
import type { EmotionTimelineRange, EmotionTimelinePoint } from '@/api/modules/memory'

const { t } = useI18n()
const { enumLabel } = useEnumLabel()
// onAgentChange：切换 agent 后全页按新 agent 重拉（同族页面 Memory/Metacognition 的既有接线契约）
const { agentId } = useAgentPage({
  onAgentChange: () => {
    refreshAll()
  },
})

const activeTab = ref('emotion')
const refreshing = ref(false)

// --- 情绪页签状态 ---
const loadingEmotion = ref(false)
// 情绪变化时间轴：窗口 → 粒度由后端推导（24h 按小时 / 7d、30d 按天 / 90d 按周）
const timelineRange = ref<EmotionTimelineRange>('7d')
const timelinePoints = ref<EmotionTimelinePoint[]>([])
const loadingTimeline = ref(false)

// Emotion stats (from /memory/emotion/summary -> { total_annotated, emotion_distribution, emotion_weight })
const currentEmotion = ref<{ dominant?: string; shared?: number }>({})
const categories = ref<{ name: string; count: number; value: number }[]>([])
const totalAnnotated = ref(0)

// --- 个性页签状态 ---
const loading = ref(false)
const saving = ref(false)
const evolving = ref(false)
const editing = ref(false)
// 保存回读校验：null=未校验/通过，字符串=回读不一致提示（2026-09-16）
const verifyFailed = ref<string | null>(null)
// 服务端是否已持久化 traits（null=未知/loading 中；false→空态引导）
const hasServerTraits = ref<boolean | null>(null)
const savingDefaults = ref(false)

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

const emotionLabel = (emotion?: string) => enumLabel('emotion', emotion)

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

const fetchTimeline = async () => {
  loadingTimeline.value = true
  try {
    const env: any = await getEmotionTimeline(agentId.value, timelineRange.value)
    timelinePoints.value = env?.data?.points ?? []
  } catch {
    message.error(t('common.error'))
  } finally {
    loadingTimeline.value = false
  }
}

// 窗口切换即换粒度重拉（24h 小时 / 7d、30d 天 / 90d 周）
watch(timelineRange, fetchTimeline)

/**
 * 情绪变化时间轴 option。
 * Y 轴固定 [-1,1]（正=积极、负=消极），0 处画分界虚线；
 * 空桶保留 null 且 connectNulls=false → 画成断点，不抹平成"中性 0"；
 * 悬停给该桶的峰值事件：时间 · 情绪项名 · 效价 · 触发它的记忆摘要。
 */
const emotionTimelineOption = computed(() => {
  const points = timelinePoints.value
  return {
    grid: { left: 44, right: 16, top: 20, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      // 浮层挂 body：图表在 GlassPanel 的 overflow:hidden 里，挂在容器内会被裁切
      appendToBody: true,
      extraCssText: 'max-width: 320px; white-space: normal;',
      formatter: (items: any[]) => {
        const point = points[items?.[0]?.dataIndex ?? -1]
        if (!point || point.valence === null) return ''
        return [
          `${point.label} · ${enumLabel('emotion', point.peak_emotion ?? '')}`,
          point.valence.toFixed(2),
          point.excerpt,
        ].filter(Boolean).join('<br/>')
      },
    },
    xAxis: { type: 'category', data: points.map((p) => p.label) },
    yAxis: {
      type: 'value',
      min: -1,
      max: 1,
      axisLabel: { color: '#94a3b8' },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.15)' } },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        connectNulls: false,
        symbolSize: 7,
        data: points.map((p) => p.valence),
        itemStyle: { color: '#22d3ee' },
        lineStyle: { color: '#22d3ee' },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ yAxis: 0, lineStyle: { color: '#94a3b8', type: 'dashed' } }],
        },
      },
    ],
  }
})

// --- 个性页签取数/编辑 ---
const fetchPersonality = async () => {
  loading.value = true
  try {
    const res: any = await request.get('/growth/personality', { params: { agent_id: agentId.value } })
    // envelope.data 是唯一事实源（2026-09-16 契约收口，见 personality-envelope-contract.test.ts）
    const data = res?.data ?? {}
    const traits = data.traits ?? {}
    hasServerTraits.value = typeof traits === 'object' && !Array.isArray(traits) && Object.keys(traits).length > 0
    if (hasServerTraits.value) {
      traitList.value = traitList.value.map(t => {
        const val = (traits as Record<string, number>)[t.key] ?? t.value
        return { ...t, value: val, percent: Math.round(val * 100) }
      })
    }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

/** PUT /personality 并用响应 envelope.data.traits 回读校验。
 *  失败原因判别：missing = 服务端未回读 traits；mismatch = 回读与写入不一致（携带回读值供回刷）。 */
type PersistResult =
  | { ok: true; traits: Record<string, number> }
  | { ok: false; reason: 'missing' }
  | { ok: false; reason: 'mismatch'; traits: Record<string, number> }
const persistTraits = async (traits: Record<string, number>): Promise<PersistResult> => {
  const res: any = await request.put('/growth/personality', { traits }, { params: { agent_id: agentId.value } })
  const readBack = res?.data?.traits
  if (!readBack || typeof readBack !== 'object') return { ok: false, reason: 'missing' }
  const mismatch = Object.entries(traits).some(([k, v]) => Math.abs((Number(readBack[k]) || 0) - v) > 1e-9)
  return mismatch ? { ok: false, reason: 'mismatch', traits: readBack as Record<string, number> } : { ok: true, traits: readBack as Record<string, number> }
}

/** 用服务端 traits 回刷滑杆列表（回读为准） */
const applyServerTraits = (traits: Record<string, number>) => {
  traitList.value = traitList.value.map(t => {
    if (traits[t.key] === undefined) return t
    return { ...t, value: traits[t.key], percent: Math.round(traits[t.key] * 100) }
  })
  hasServerTraits.value = Object.keys(traits).length > 0
}

const savePersonality = async () => {
  saving.value = true
  verifyFailed.value = null
  try {
    const traits: Record<string, number> = {}
    traitList.value.forEach(t => { traits[t.key] = t.percent / 100 })
    const result = await persistTraits(traits)
    if (!result.ok) {
      // 回读缺失或不一致：如实报错，不谎报成功；不一致时服务端值仍为事实源，回刷列表
      if (result.reason === 'mismatch') applyServerTraits(result.traits)
      message.error(t('common.error'))
      verifyFailed.value = result.reason === 'missing'
        ? t('personality.verifyFailed')
        : t('personality.verifyMismatch')
      return
    }
    applyServerTraits(result.traits)
    editing.value = false
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    saving.value = false
  }
}

/** 空态引导：写入六维中性默认值并按回读刷新（回读失败保持空态） */
const writeDefaultTraits = async () => {
  savingDefaults.value = true
  verifyFailed.value = null
  try {
    const defaults: Record<string, number> = {}
    traitList.value.forEach(t => { defaults[t.key] = 0.5 })
    const result = await persistTraits(defaults)
    if (!result.ok) {
      if (result.reason === 'mismatch') applyServerTraits(result.traits)
      message.error(t('common.error'))
      verifyFailed.value = result.reason === 'missing'
        ? t('personality.verifyFailed')
        : t('personality.verifyMismatch')
      return
    }
    applyServerTraits(result.traits)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    savingDefaults.value = false
  }
}

const evolvePersonality = async () => {
  evolving.value = true
  try {
    await request.post('/growth/personality/evolve', {}, { params: { agent_id: agentId.value } })
    message.success(t('common.success'))
    await fetchPersonality()
  } catch {
    message.error(t('common.error'))
  } finally {
    evolving.value = false
  }
}

const refreshAll = async () => {
  refreshing.value = true
  try {
    await Promise.all([fetchEmotion(), fetchTimeline(), fetchPersonality()])
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

/* 情绪变化时间轴：窗口切换与图高 */
.timeline-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; margin-bottom: 12px;
}
.timeline-hint { font-size: 12px; color: var(--nr-text-muted); }
.timeline-chart { height: 260px; width: 100%; }

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

/* 空态引导：服务端未建立档案 */
.traits-empty-guide { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 36px 12px; }
.traits-empty-hint { margin: 0; font-size: 13px; color: var(--nr-text-secondary); }
.traits-verify-tip {
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.25);
}
</style>
