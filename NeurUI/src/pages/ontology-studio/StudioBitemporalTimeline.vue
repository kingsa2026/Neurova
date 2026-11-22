<template>
  <div class="bitemporal-timeline" data-testid="studio-bitemporal-timeline">
    <div class="view-head">
      <h4 class="view-title">{{ t('ontology.timelineTitle') }}</h4>
      <GlassButton
        size="sm"
        variant="secondary"
        :loading="loading"
        data-testid="timeline-refresh"
        @click="loadTimeline"
      >
        {{ t('ontology.timelineRefresh') }}
      </GlassButton>
    </div>

    <div class="asof-row">
      <span class="asof-label">{{ t('ontology.asOfLabel') }}</span>
      <input
        v-model="asOfInput"
        type="datetime-local"
        class="asof-input"
        data-testid="timeline-asof-input"
      />
      <GlassButton size="sm" data-testid="timeline-asof-apply" @click="applyAsOf">
        {{ t('common.search') }}
      </GlassButton>
      <GlassButton size="sm" variant="ghost" data-testid="timeline-asof-clear" @click="clearAsOf">
        {{ t('common.clear') }}
      </GlassButton>
    </div>

    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      data-testid="timeline-error"
      :message="t('ontology.timelineLoadFailed')"
    />
    <p v-else-if="loading" class="loading-note" data-testid="timeline-loading">
      {{ t('common.loading') }}
    </p>
    <a-empty
      v-else-if="!rows.length"
      data-testid="timeline-empty"
      :description="t('ontology.timelineEmpty')"
    />
    <template v-else>
      <svg
        class="timeline-svg"
        :viewBox="`0 0 ${WIDTH} ${svgHeight}`"
        data-testid="timeline-svg"
        role="img"
      >
        <line
          :x1="x(nowMs)" :x2="x(nowMs)" :y1="PAD_TOP - 4" :y2="svgHeight - PAD_BOTTOM + 6"
          class="now-line" data-testid="timeline-now-line"
        />
        <text :x="x(nowMs) + 4" :y="PAD_TOP - 8" class="now-label">{{ t('ontology.timelineNow') }}</text>
        <line
          v-if="asOfMs !== null"
          :x1="x(asOfMs)" :x2="x(asOfMs)" :y1="PAD_TOP - 4" :y2="svgHeight - PAD_BOTTOM + 6"
          class="asof-line" data-testid="timeline-asof-line"
        />
        <text v-if="asOfMs !== null" :x="x(asOfMs) + 4" :y="PAD_TOP + 4" class="asof-label-text">
          {{ shortStamp(asOfMs) }}
        </text>

        <g v-for="row in rows" :key="row.factId" class="timeline-row">
          <text :x="8" :y="rowY(row.index) + BAR_H" class="row-label">{{ row.label }}</text>
          <rect
            v-if="row.start !== null"
            :x="x(row.start)"
            :y="rowY(row.index)"
            :width="barWidth(row)"
            :height="BAR_H"
            rx="6"
            class="bar"
            :class="{ 'bar--open': row.openEnd, 'bar--retracted': row.retracted }"
            data-testid="timeline-interval"
            :data-fact-id="row.factId"
          />
          <text v-else :x="TRACK_X + 4" :y="rowY(row.index) + BAR_H" class="no-start">
            {{ t('ontology.timelineNoStart') }}
          </text>
        </g>

        <line
          :x1="TRACK_X" :x2="WIDTH - PAD_RIGHT" :y1="axisY" :y2="axisY"
          class="axis-line" data-testid="timeline-axis"
        />
        <text :x="TRACK_X" :y="axisY + 14" class="tick-label">{{ shortStamp(axisMin) }}</text>
        <text :x="(TRACK_X + WIDTH - PAD_RIGHT) / 2" :y="axisY + 14" class="tick-label">
          {{ shortStamp((axisMin + axisMax) / 2) }}
        </text>
        <text :x="WIDTH - PAD_RIGHT" :y="axisY + 14" class="tick-label">{{ shortStamp(axisMax) }}</text>
      </svg>

      <p class="legend">
        <span class="legend-item"><span class="swatch swatch--closed" />valid_from → valid_until</span>
        <span class="legend-item"><span class="swatch swatch--open" />{{ t('ontology.timelineOpenEnd') }}</span>
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 双时态时间线（U7，只读）：POST /knowledge/access/query 走事实层
 * （knownAt=当前时刻＝当前快照；asOf 由输入联动——后端 factsBitemporal
 * 以 valid_from/valid_until 裁业务时间）。区间条渲染 valid 区间，
 * 未闭合（valid_until 为空）延伸到「当前时刻」指示线；起点缺失的行
 * 显式标注「起点未记录」，不虚构起点。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GlassButton from '@/components/GlassButton.vue'
import { accessQuery } from '@/api/modules/ontology'
import type { FactQueryItem } from '@/types/ontology'

const { t } = useI18n()

const WIDTH = 760
const PAD_RIGHT = 16
const PAD_TOP = 26
const PAD_BOTTOM = 34
const LABEL_W = 200
const TRACK_X = LABEL_W + 8
const TRACK_W = WIDTH - TRACK_X - PAD_RIGHT
const ROW_H = 26
const BAR_H = 12
const DAY_MS = 24 * 60 * 60 * 1000

interface TimelineRow {
  factId: string
  index: number
  label: string
  start: number | null
  end: number | null
  openEnd: boolean
  retracted: boolean
}

const items = ref<FactQueryItem[]>([])
const asOfInput = ref('')
const loading = ref(false)
const loadError = ref(false)

const nowMs = computed(() => Date.now())

const asOfMs = computed(() => {
  const text = asOfInput.value.trim()
  if (!text) return null
  const parsed = Date.parse(text)
  return Number.isFinite(parsed) ? parsed : null
})

function parseTs(value: unknown): number | null {
  const text = String(value ?? '').trim()
  if (!text) return null
  const parsed = Date.parse(text)
  return Number.isFinite(parsed) ? parsed : null
}

function rowY(index: number): number {
  return PAD_TOP + index * ROW_H + (ROW_H - BAR_H) / 2
}

const rows = computed<TimelineRow[]>(() => {
  const out: TimelineRow[] = []
  for (const item of items.value) {
    const meta = (item.metadata ?? {}) as Record<string, unknown>
    const start = parseTs(meta.valid_from)
    const end = parseTs(meta.valid_until)
    const label = `${meta.subject_key ?? ''}·${meta.predicate_term_id ?? ''}·${meta.object_term ?? ''}`
    out.push({
      factId: item.knowledge_id || item.id || '',
      index: out.length,
      label: truncate(label.replace(/^·+|·+$/g, '') || item.title || '', 34),
      start,
      end,
      openEnd: end === null,
      retracted: !!parseTs(meta.retracted_at),
    })
  }
  return out
})

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

const starts = computed(() => rows.value.map((r) => r.start).filter((v): v is number => v !== null))
const ends = computed(() => rows.value.map((r) => r.end).filter((v): v is number => v !== null))

const axisMin = computed(() => {
  const candidates = [...starts.value, nowMs.value, ...(asOfMs.value !== null ? [asOfMs.value] : [])]
  return candidates.length ? Math.min(...candidates) : nowMs.value - DAY_MS
})

const axisMax = computed(() => {
  const candidates = [...ends.value, nowMs.value, ...(asOfMs.value !== null ? [asOfMs.value] : [])]
  return candidates.length ? Math.max(...candidates) : nowMs.value
})

const svgHeight = computed(() => PAD_TOP + rows.value.length * ROW_H + PAD_BOTTOM)
const axisY = computed(() => PAD_TOP + rows.value.length * ROW_H + 6)

function x(time: number): number {
  const span = axisMax.value - axisMin.value
  if (span <= 0) return TRACK_X + TRACK_W / 2
  return TRACK_X + ((time - axisMin.value) / span) * TRACK_W
}

function barWidth(row: TimelineRow): number {
  const end = row.end ?? nowMs.value
  const start = row.start ?? axisMin.value
  return Math.max(3, x(end) - x(start))
}

function shortStamp(time: number): string {
  const d = new Date(time)
  // padStart 原地内联：不另起具名函数（duplicate-function-inventory 守卫盯同名同体）
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd} ${hh}:${mi}`
}

async function loadTimeline() {
  loading.value = true
  loadError.value = false
  try {
    const body: Record<string, unknown> = {
      query: '',
      knownAt: new Date().toISOString(),
      limit: 100,
    }
    const asOf = asOfInput.value.trim()
    if (asOf) body.asOf = asOf
    const res = await accessQuery(body as never)
    const payload = (res as unknown as { data?: unknown }).data ?? res
    items.value = Array.isArray(payload) ? (payload as FactQueryItem[]) : []
  } catch {
    loadError.value = true
    items.value = []
  } finally {
    loading.value = false
  }
}

function applyAsOf() {
  void loadTimeline()
}

function clearAsOf() {
  asOfInput.value = ''
  void loadTimeline()
}

onMounted(loadTimeline)
</script>

<style scoped>
.bitemporal-timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.view-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.view-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}
.asof-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
}
.asof-label {
  color: var(--nr-text-secondary, inherit);
  white-space: nowrap;
}
.asof-input {
  padding: 5px 8px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.3));
  background: transparent;
  color: var(--nr-text-primary, inherit);
  font-size: 12px;
  color-scheme: inherit;
}
.loading-note {
  margin: 0;
  font-size: 12px;
  color: var(--nr-text-secondary, inherit);
}
.timeline-svg {
  width: 100%;
  max-width: 800px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  border-radius: 10px;
}
.bar {
  fill: var(--nr-primary-soft, rgba(99, 102, 241, 0.12));
  stroke: var(--nr-primary, #6366f1);
}
.bar--open {
  stroke: var(--nr-accent, #22d3ee);
  stroke-dasharray: 3 2;
}
.bar--retracted {
  fill: transparent;
  stroke: var(--nr-text-secondary, rgba(128, 128, 128, 0.6));
  stroke-dasharray: 2 3;
}
.row-label {
  font-size: 10px;
  fill: var(--nr-text-secondary, inherit);
}
.no-start {
  font-size: 10px;
  fill: var(--nr-text-secondary, inherit);
  font-style: italic;
}
.now-line {
  stroke: var(--nr-accent, #22d3ee);
  stroke-width: 1.5;
  stroke-dasharray: 4 3;
}
.now-label {
  font-size: 9px;
  fill: var(--nr-accent, #22d3ee);
}
.asof-line {
  stroke: var(--nr-primary, #6366f1);
  stroke-width: 1.5;
}
.asof-label-text {
  font-size: 9px;
  fill: var(--nr-primary, #6366f1);
}
.axis-line {
  stroke: var(--nr-border, rgba(128, 128, 128, 0.3));
}
.tick-label {
  font-size: 9px;
  fill: var(--nr-text-secondary, inherit);
}
.legend {
  margin: 0;
  display: flex;
  gap: 14px;
  font-size: 11px;
  color: var(--nr-text-secondary, inherit);
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.swatch {
  display: inline-block;
  width: 16px;
  height: 10px;
  border-radius: 3px;
}
.swatch--closed {
  background: var(--nr-primary-soft, rgba(99, 102, 241, 0.12));
  border: 1px solid var(--nr-primary, #6366f1);
}
.swatch--open {
  background: transparent;
  border: 1px dashed var(--nr-accent, #22d3ee);
}
</style>
