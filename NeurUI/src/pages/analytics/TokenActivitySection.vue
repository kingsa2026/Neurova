<template>
  <div class="nr-usage-stats">
    <!-- 工具行：scope 标签 + 时间范围 + 刷新（页级标题由容器 /analytics 提供） -->
    <div class="nr-usage-toolbar-row">
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
        <GlassStatCard :label="t('usageStats.totalTokens')" :value="formatTokenCount(summary.total_tokens)" emoji="📊" spark-color="#a78bfa" :spark-data="sparkDaily" />
        <GlassStatCard :label="t('usageStats.cacheHitTokens')" :value="formatTokenCount(summary.cache_read_tokens)" emoji="⚡" spark-color="#34d399" :spark-data="sparkDaily" />
        <GlassStatCard :label="t('usageStats.cacheHitRate')" :value="`${((summary.cache_hit_rate || 0) * 100).toFixed(1)}%`" emoji="🎯" spark-color="#22d3ee" :spark-data="sparkDaily" />
        <GlassStatCard :label="t('usageStats.peakTokens')" :value="formatTokenCount(summary.peak_daily_tokens)" emoji="⚡" spark-color="#60a5fa" :spark-data="sparkDaily" />
        <GlassStatCard :label="t('usageStats.longestSession')" :value="formatDuration(summary.longest_session_seconds)" emoji="⏱️" spark-color="#34d399" :spark-data="sparkCalls" />
        <GlassStatCard :label="t('usageStats.currentStreak')" :value="`${summary.current_streak_days} ${t('usageStats.days')}`" emoji="🔥" spark-color="#fbbf24" :spark-data="sparkCalls" />
        <GlassStatCard :label="t('usageStats.longestStreak')" :value="`${summary.longest_streak_days} ${t('usageStats.days')}`" emoji="🏆" spark-color="#f472b6" :spark-data="sparkCalls" />
        <GlassStatCard :label="t('usageStats.aigcImages')" :value="aigcItems('image')" emoji="🖼️" spark-color="#60a5fa" :spark-data="aigcSpark('image')" />
        <GlassStatCard :label="t('usageStats.aigcVideos')" :value="aigcItems('video')" emoji="🎬" spark-color="#a78bfa" :spark-data="aigcSpark('video')" />
        <GlassStatCard :label="t('usageStats.aigcAudios')" :value="aigcItems('audio')" emoji="🔊" spark-color="#34d399" :spark-data="aigcSpark('audio')" />
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

      <!-- P1-13 provider 真账单（默认关，无快照恒隐藏） -->
      <GlassCard v-if="providerSnapshots.length" :title="t('usageStats.providerBilling')" variant="default" :radius="20">
        <div class="nr-provider-grid">
          <div v-for="snap in providerSnapshots" :key="snap.provider_id" class="nr-provider-card">
            <div class="nr-provider-name">{{ snap.provider_id }}</div>
            <div class="nr-provider-balance">
              <template v-if="snap.balance != null">
                {{ snap.currency || '' }} {{ Number(snap.balance).toFixed(2) }}
              </template>
              <template v-else-if="snap.quota_remaining != null">
                {{ Number(snap.quota_remaining).toLocaleString() }}
              </template>
              <template v-else>{{ t('common.noData') }}</template>
            </div>
            <div class="nr-provider-meta">
              <span v-if="snap.plan">{{ snap.plan }}</span>
              <span>{{ snap.ts }}</span>
            </div>
          </div>
        </div>
        <div v-if="providerErrors.length" class="nr-provider-errors">
          <a-tag v-for="err in providerErrors" :key="err.provider_id" color="orange">
            {{ err.provider_id }}: {{ err.error }}
          </a-tag>
        </div>
      </GlassCard>

      <!-- P1-8 按模型延迟分位（无 duration_ms 数据时恒空 → 卡片隐藏） -->
      <GlassCard v-if="latencyStats.length" :title="t('usageStats.latencyByModel')" variant="default" :radius="20">
        <div class="nr-latency-table">
          <div class="nr-latency-row nr-latency-head">
            <span>{{ t('usageStats.latencyCalls') }}</span>
            <span>{{ t('usageStats.latencyP50') }}</span>
            <span>{{ t('usageStats.latencyP95') }}</span>
            <span>{{ t('usageStats.latencyMax') }}</span>
          </div>
          <div v-for="row in latencyStats" :key="row.model" class="nr-latency-row">
            <span class="nr-latency-model">{{ row.model }} · {{ row.calls }}</span>
            <span>{{ formatLatency(row.p50_ms) }}</span>
            <span>{{ formatLatency(row.p95_ms) }}</span>
            <span>{{ formatLatency(row.max_ms) }}</span>
          </div>
        </div>
      </GlassCard>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
// 原 /usage-stats 独立页（UsageStatsPage）整体迁入 /analytics 统一入口的
// 「Token 活动」Tab（六页整合，工单集 §46）。行为零变化：数据口径、副路径
// 静默降级、热力图三视图均保持原实现；仅页级大标题让位给容器。
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { formatTokenCount } from '@/utils/displayText'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import {
  getUsageOverview,
  getProviderUsage,
  type UsageOverview,
  type UsageOverviewHeatmapDay,
  type ProviderUsageSnapshot,
  type ProviderUsageResponse,
} from '@/api/modules/stats'
import { getGenerationUsage, type AigcUsageSummary } from '@/api/modules/generation'

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
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    cache_hit_rate: 0,
  },
  heatmap: [],
  trends: [],
  by_model: [],
})

const summary = computed(() => overview.value.summary)
const scopeLabel = computed(() =>
  overview.value.scope === 'user' ? t('usageStats.myUsage') : t('usageStats.allUsers'),
)

/** P1-13 provider 账单快照（采集器未装配/无启用 provider 时恒空 → 卡片隐藏） */
const providerSnapshots = ref<ProviderUsageSnapshot[]>([])
const providerErrors = ref<ProviderUsageResponse['errors']>([])

/** L4：AIGC 生成用量（图/视频/音频计数；读失败回空账不影响主看板） */
const aigcUsage = ref<AigcUsageSummary>({ daily: [], totals: [], days: 30 })

function aigcItems(kind: string, status = 'success'): number {
  const row = aigcUsage.value.totals.find(r => r.kind === kind && r.status === status)
  return row ? (row.items || row.calls) : 0
}

function aigcSpark(kind: string): number[] {
  return aigcUsage.value.daily
    .filter(r => r.kind === kind && r.status === 'success')
    .map(r => r.items || r.calls)
}

/** P1-8 按模型延迟分位（后端已算，此前前端零消费——契约字段悬空） */
const latencyStats = computed(() => overview.value.latency_stats ?? [])

function formatLatency(ms: number): string {
  if (!ms) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
}

/** 每日 token 序列（KPI spark 用） */
const heatDays = computed<UsageOverviewHeatmapDay[]>(() => overview.value.heatmap ?? [])
const sparkDaily = computed(() => heatDays.value.map((d) => d.tokens))
const sparkCalls = computed(() => heatDays.value.map((d) => d.calls))


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

/** 热力图 x 轴刻度：每周序 → 该周首日（周一）的 MM-DD。 */
function heatWeekLabels(days: UsageOverviewHeatmapDay[], cells: [number, number, number][]): string[] {
  const totalWeeks = Math.max(...cells.map((c) => c[0])) + 1
  const first = new Date(`${days[0]!.date}T00:00:00`)
  first.setDate(first.getDate() - ((first.getDay() + 6) % 7))
  return Array.from({ length: totalWeeks }, (_, i) => {
    const d = new Date(first.getTime())
    d.setDate(d.getDate() + i * 7)
    return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
    // x 轴 = 周序，但**必须有日期刻度**：此前 axisLabel.show=false，
    // 365 天窗口渲染成一条没有任何日期参照的空白长条（截图里的灰带）。
    // 刻度取每周首日的 MM-DD，间隔抽稀到 ≤12 个，避免糊成一片。
    xAxis: { type: 'category', data: heatWeekLabels(days, cells), axisLabel: { color: '#94a3b8', interval: Math.max(0, Math.ceil((Math.max(...cells.map((c) => c[0])) + 1) / 12) - 1), fontSize: 10 } },
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
  // P1-13: provider 账单副路径（失败静默，不影响主看板）
  try {
    const pu: any = await getProviderUsage()
    const payload: ProviderUsageResponse = pu?.data ?? pu ?? { snapshots: [], errors: [] }
    providerSnapshots.value = payload.snapshots ?? []
    providerErrors.value = payload.errors ?? []
  } catch {
    providerSnapshots.value = []
    providerErrors.value = []
  }
  // L4: AIGC 生成用量副路径（失败回空账，不影响主看板）
  try {
    const au: any = await getGenerationUsage(30)
    aigcUsage.value = (au?.data ?? au) as AigcUsageSummary
  } catch {
    aigcUsage.value = { daily: [], totals: [], days: 30 }
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
  padding: 4px 0;
}

.nr-usage-toolbar-row {
  display: flex;
  justify-content: flex-end;
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

.nr-provider-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}

.nr-provider-card {
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 14px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nr-provider-name {
  font-weight: 600;
  color: var(--nr-text-primary);
  font-size: 14px;
}

.nr-provider-balance {
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary);
}

.nr-provider-meta {
  display: flex;
  justify-content: space-between;
  color: var(--nr-text-tertiary, var(--nr-text-tertiary));
  font-size: 12px;
}

.nr-provider-errors {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.nr-latency-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nr-latency-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  color: var(--nr-text-secondary, var(--nr-text-tertiary));
  font-size: 13px;
}

.nr-latency-row:not(.nr-latency-head):nth-child(odd) {
  background: rgba(148, 163, 184, 0.06);
}

.nr-latency-head {
  font-weight: 600;
  color: var(--nr-text-primary, #e2e8f0);
}

.nr-latency-model {
  color: var(--nr-text-primary, #e2e8f0);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
