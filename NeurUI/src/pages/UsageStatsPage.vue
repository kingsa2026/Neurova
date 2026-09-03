<template>
  <div class="nr-usage-stats">
    <!-- Header: title + scope tag + time range -->
    <div class="nr-usage-header">
      <h2 class="nr-usage-title">{{ t('usageStats.title') }}</h2>
      <div class="nr-usage-toolbar">
        <a-tag v-if="scopeLabel" color="blue">{{ scopeLabel }}</a-tag>
        <a-radio-group v-model:value="trendDays" button-style="solid" size="small">
          <a-radio-button :value="7" @click="setTrendDays(7)">{{ t('usageStats.last7Days') }}</a-radio-button>
          <a-radio-button :value="30" @click="setTrendDays(30)">{{ t('usageStats.last30Days') }}</a-radio-button>
        </a-radio-group>
        <GlassButton size="sm" variant="ghost" @click="fetchData">🔄</GlassButton>
      </div>
    </div>

    <a-spin :spinning="loading">
      <!-- KPI cards（持久化口径：累计/单日峰值/最长会话时长/连续天数） -->
      <div class="nr-usage-kpis">
        <GlassStatCard :label="t('usageStats.totalTokens')" :value="formatTokens(summary.total_tokens)" emoji="📊" spark-color="#a78bfa" :spark-data="sparkDaily" />
        <GlassStatCard :label="t('usageStats.peakTokens')" :value="formatTokens(summary.peak_daily_tokens)" emoji="⚡" spark-color="#60a5fa" :spark-data="sparkDaily" />
        <GlassStatCard :label="t('usageStats.longestSession')" :value="formatDuration(summary.longest_session_seconds)" emoji="⏱️" spark-color="#34d399" :spark-data="sparkCalls" />
        <GlassStatCard :label="t('usageStats.currentStreak')" :value="`${summary.current_streak_days} ${t('usageStats.days')}`" emoji="🔥" spark-color="#fbbf24" :spark-data="sparkCalls" />
        <GlassStatCard :label="t('usageStats.longestStreak')" :value="`${summary.longest_streak_days} ${t('usageStats.days')}`" emoji="🏆" spark-color="#f472b6" :spark-data="sparkCalls" />
      </div>

      <!-- Token 活动热力图（每日网格 / 每周 / 累计） -->
      <GlassCard :title="t('usageStats.tokenActivity')" variant="default" :radius="20">
        <div class="nr-usage-subtoolbar">
          <a-radio-group v-model:value="heatView" size="small" button-style="solid">
            <a-radio-button value="daily">{{ t('usageStats.daily') }}</a-radio-button>
            <a-radio-button value="weekly">{{ t('usageStats.weekly') }}</a-radio-button>
            <a-radio-button value="cumulative">{{ t('usageStats.cumulative') }}</a-radio-button>
          </a-radio-group>
        </div>
        <div class="nr-usage-heatmap">
          <VChart v-if="heatmapOption" :option="heatmapOption" autoresize />
          <a-empty v-else :description="t('common.noData')" />
        </div>
      </GlassCard>

      <!-- 每日 Token 趋势（按模型分组折线） -->
      <GlassCard :title="t('usageStats.dailyTokenTrend')" variant="default" :radius="20">
        <div class="nr-usage-trend">
          <VChart v-if="trendOption" :option="trendOption" autoresize />
          <a-empty v-else :description="t('common.noData')" />
        </div>
      </GlassCard>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  getUsageOverview,
  type UsageOverview,
  type UsageOverviewHeatmapDay,
} from '@/api/modules/stats'

const { t } = useI18n()

const HEATMAP_DAYS = 365
const DEFAULT_TREND_DAYS = 7

const loading = ref(false)
const trendDays = ref(DEFAULT_TREND_DAYS)
const heatView = ref<'daily' | 'weekly' | 'cumulative'>('daily')
const overview = ref<UsageOverview>({
  summary: {
    total_tokens: 0,
    total_calls: 0,
    peak_daily_tokens: 0,
    peak_daily_date: null,
    longest_session_seconds: 0,
    current_streak_days: 0,
    longest_streak_days: 0,
    active_days: 0,
  },
  heatmap: [],
  trends: [],
  by_model: [],
})

const summary = computed(() => overview.value.summary)
const scopeLabel = computed(() =>
  overview.value.scope === 'user' ? t('usageStats.myUsage') : t('usageStats.allUsers'),
)

/** 每日 token 序列（KPI spark 用） */
const heatDays = computed<UsageOverviewHeatmapDay[]>(() => overview.value.heatmap ?? [])
const sparkDaily = computed(() => heatDays.value.map((d) => d.tokens))
const sparkCalls = computed(() => heatDays.value.map((d) => d.calls))

function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function formatDuration(seconds: number): string {
  if (seconds >= 86_400) {
    const days = Math.floor(seconds / 86_400)
    const hours = Math.floor((seconds % 86_400) / 3600)
    return `${days} ${t('usageStats.days')} ${hours} ${t('usageStats.hours')}`
  }
  if (seconds >= 3_600) return `${(seconds / 3_600).toFixed(1)} ${t('usageStats.hours')}`
  if (seconds >= 60) return `${(seconds / 60).toFixed(1)} ${t('usageStats.minutes')}`
  return `${seconds} ${t('usageStats.seconds')}`
}

/** GitHub 风格周网格：x=周序（窗口起点对齐周一），y=周一..周日 */
function buildHeatCells(days: UsageOverviewHeatmapDay[]): [number, number, number][] {
  const first = new Date(`${days[0]!.date}T00:00:00`)
  // 起点回退到所在周的周一
  const mondayOffset = (first.getDay() + 6) % 7
  first.setDate(first.getDate() - mondayOffset)
  return days.map((d) => {
    const dt = new Date(`${d.date}T00:00:00`)
    const week = Math.round((dt.getTime() - first.getTime()) / 86_400_000 / 7)
    const dayIdx = (dt.getDay() + 6) % 7 // Mon=0 .. Sun=6
    return [week, dayIdx, d.tokens]
  })
}

const heatmapOption = computed(() => {
  const days = heatDays.value
  if (!days.length) return null

  // 累计视图：每日累计折线（自窗口起点滚存）
  if (heatView.value === 'cumulative') {
    let acc = 0
    const labels = days.map((d) => d.date.slice(5))
    const data = days.map((d) => (acc += d.tokens))
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 60, right: 24, top: 24, bottom: 28 },
      xAxis: { type: 'category', data: labels, axisLabel: { color: '#94a3b8', interval: Math.max(1, Math.floor(labels.length / 10)) } },
      yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } } },
      series: [{ name: t('usageStats.totalTokens'), type: 'line', smooth: true, showSymbol: false, data, lineStyle: { color: '#a78bfa', width: 2 }, itemStyle: { color: '#a78bfa' }, areaStyle: { color: 'rgba(167,139,250,0.12)' } }],
    }
  }

  const maxTok = Math.max(...days.map((d) => d.tokens), 1)
  const cells =
    heatView.value === 'daily'
      ? buildHeatCells(days)
      : buildHeatCells(days).map(([week, , tokens]) => [week, 0, tokens] as [number, number, number])

  // 每周视图只保留行 0；行标签按视图切换
  const yLabels = heatView.value === 'daily' ? ['1', '2', '3', '4', '5', '6', '7'] : ['W']
  return {
    tooltip: {
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        const idx = p.dataIndex
        const day = days[idx] ?? {}
        const value = p.value?.[2] ?? 0
        return `${day.date ?? ''}<br/>${value.toLocaleString()} tokens · ${day.calls ?? 0} calls`
      },
    },
    grid: { left: 40, right: 16, top: 16, bottom: 24 },
    xAxis: { type: 'category', data: Array.from({ length: Math.max(...cells.map((c) => c[0])) + 1 }, (_, i) => i), axisLabel: { color: '#94a3b8', show: false } },
    yAxis: { type: 'category', data: yLabels, axisLabel: { color: '#94a3b8' } },
    visualMap: {
      show: false,
      min: 0,
      max: maxTok,
      dimension: 2,
      inRange: { color: ['#23283a', '#3b2f63', '#6d4aa3', '#9b6dd6', '#c9a3f5'] },
    },
    series: [
      {
        type: 'heatmap',
        data: cells,
        itemStyle: { borderColor: 'transparent', borderWidth: 2 },
        emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 1 } },
      },
    ],
  }
})

const trendOption = computed(() => {
  const pts = overview.value.trends ?? []
  if (!pts.length) return null
  const dates = [...new Set(pts.map((p) => p.date))].sort()
  const labels = dates.map((d) => d.slice(5))
  const models = (overview.value.by_model ?? []).map((m) => m.model)
  const palette = ['#60a5fa', '#34d399', '#a78bfa', '#f87171', '#fbbf24', '#22d3ee', '#f472b6']
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: '#94a3b8' }, icon: 'circle' },
    grid: { left: 64, right: 24, top: 40, bottom: 28 },
    xAxis: { type: 'category', data: labels, boundaryGap: false, axisLabel: { color: '#94a3b8' } },
    yAxis: { type: 'value', axisLabel: { color: '#94a3b8' }, splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } } },
    series: models.map((model, i) => ({
      name: model,
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: dates.map((d) => pts.find((p) => p.date === d && p.model === model)?.tokens ?? 0),
      lineStyle: { color: palette[i % palette.length]!, width: 2 },
      itemStyle: { color: palette[i % palette.length] },
    })),
  }
})

async function fetchData() {
  loading.value = true
  try {
    const res: any = await getUsageOverview({ days: HEATMAP_DAYS, trend_days: trendDays.value })
    overview.value = (res?.data ?? res ?? { summary: overview.value.summary }) as UsageOverview
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

/** 时间范围切换：显式驱动（antd radio 选中态与 v-model 同步，点击即改即拉取） */
function setTrendDays(n: number) {
  if (trendDays.value === n) return
  trendDays.value = n
  void fetchData()
}

onMounted(fetchData)
</script>

<style scoped>
.nr-usage-stats {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 4px;
}

.nr-usage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.nr-usage-title {
  font-family: var(--nr-font-display);
  font-size: 24px;
  font-weight: 700;
  color: var(--nr-text-primary);
  letter-spacing: -0.03em;
  margin: 0;
}

.nr-usage-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.nr-usage-kpis {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

@media (max-width: 1280px) {
  .nr-usage-kpis { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 800px) {
  .nr-usage-kpis { grid-template-columns: repeat(2, 1fr); }
}

.nr-usage-subtoolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.nr-usage-heatmap {
  height: 260px;
}

.nr-usage-trend {
  height: 320px;
}
</style>
