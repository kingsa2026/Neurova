<template>
  <div
    v-if="visible"
    class="nr-ctx-usage"
    :class="{ 'nr-ctx-usage--warn': level === 'warn', 'nr-ctx-usage--danger': level === 'danger' }"
    @mouseenter="openPanel"
    @mouseleave="scheduleClose"
  >
    <svg class="nr-ctx-ring" viewBox="0 0 36 36" width="22" height="22">
      <circle class="nr-ctx-ring-bg" cx="18" cy="18" r="15.9" fill="none" stroke-width="3" />
      <circle
        class="nr-ctx-ring-fg"
        cx="18" cy="18" r="15.9" fill="none"
        stroke-width="3"
        stroke-linecap="round"
        :stroke-dasharray="`${dash} ${100 - dash}`"
        stroke-dashoffset="25"
      />
    </svg>
    <span class="nr-ctx-usage-text">{{ shortTotal }}</span>

    <!-- 悬停明细面板（三需求③）：上下文容量 + 分类占比 + 命中率 -->
    <transition name="nr-ctx-pop">
      <div v-if="panelOpen && composition" class="nr-ctx-panel" @mouseenter="cancelClose" @mouseleave="scheduleClose">
        <div class="nr-ctx-panel-title">{{ t('chat.ctxPanelTitle') }}</div>
        <div class="nr-ctx-panel-headline">
          <span class="nr-ctx-panel-big">{{ fmtCompact(usedTokens) }}</span>
          <span class="nr-ctx-panel-sep">/</span>
          <span class="nr-ctx-panel-total">{{ fmtCompact(contextWindow) }}</span>
          <span class="nr-ctx-panel-pct">({{ usedPct }}%)</span>
        </div>
        <div class="nr-ctx-panel-bar">
          <span
            v-for="seg in barSegments"
            :key="seg.key"
            class="nr-ctx-panel-bar-seg"
            :style="{ width: seg.pct + '%', background: seg.color }"
          />
        </div>
        <div class="nr-ctx-panel-rows">
          <div v-for="row in panelRows" :key="row.key" class="nr-ctx-panel-row">
            <span class="nr-ctx-panel-dot" :style="{ background: row.color }" />
            <span class="nr-ctx-panel-label">{{ row.label }}</span>
            <span class="nr-ctx-panel-value">{{ row.pct }}%</span>
          </div>
        </div>
        <div v-if="cacheHitRate !== null" class="nr-ctx-panel-footer">
          {{ t('chat.ctxCacheHitRate') }} <b>{{ (cacheHitRate * 100).toFixed(1) }}%</b>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
/**
 * Token/上下文用量环形仪表 + 悬停明细面板（QwenPaw ContextUsageIndicator 对齐）。
 *
 * 双语义（环）：
 * - 有 context-window（当前模型限额已知）：环 = context 占比，双色告警
 *   （75% 变橙 / 90% 变红）；
 * - 无 context-window：环 = completion/prompt 比（产出密度），仅展示 token 总量。
 *
 * 可见性（2026-09-07 根因修复）：
 * - 原 `v-if="usage"`：usage 是纯内存态（SSE usage 事件累计），刷新即空 →
 *   环图消失。现当 usage 为空时拉取后端 composition 实测快照
 *   （GET /v1/context/composition，最近一轮真实 prompt 组成）兜底渲染；
 *   两者都无（全新会话/后端未跑过一轮）才不渲染。
 *
 * 悬停面板：上下文容量 used/window(%)、分段占比条（消息/系统工具/MCP 工具/
 * 技能/其他/系统提示词）、平均缓存命中率（无源不显示行）。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'

interface TurnUsage {
  prompt: number
  completion: number
  total: number
}

interface CompositionData {
  agent_id: string
  total_tokens: number
  context_window: number | null
  messages: { buckets: Record<string, { count: number; tokens: number }>; total_tokens: number }
  tools: Record<string, { count: number; tokens: number }>
  cache_hit_rate: number | null
  cache_source: string
}

const props = defineProps<{
  usage: TurnUsage | null
  contextWindow?: number | null
  agentId?: string | null
  sessionId?: string | null
}>()

const { t } = useI18n()

const composition = ref<CompositionData | null>(null)
const compositionFetched = ref(false)
const panelOpen = ref(false)
let closeTimer: ReturnType<typeof setTimeout> | null = null

const visible = computed(() => Boolean(props.usage || composition.value))

/** 环图分母优先级：模型窗口 > composition 实测窗口 > completion/prompt 密度。 */
const effectiveWindow = computed<number | null>(() => props.contextWindow || composition.value?.context_window || null)

const usedTokens = computed<number>(() => {
  if (props.usage?.total) return props.usage.total
  return composition.value?.total_tokens ?? 0
})

const dash = computed<number>(() => {
  if (!visible.value) return 0
  const win = effectiveWindow.value
  if (win && win > 0) {
    return Math.min(100, Math.round((usedTokens.value / win) * 100))
  }
  const prompt = props.usage?.prompt || composition.value?.messages?.buckets?.user?.tokens || 0
  const denom = prompt || 1
  const completion = props.usage?.completion || 0
  return Math.min(100, Math.round((completion / denom) * 100))
})

const level = computed<'ok' | 'warn' | 'danger'>(() => {
  if (dash.value >= 90) return 'danger'
  if (dash.value >= 75) return 'warn'
  return 'ok'
})

const usedPct = computed<number>(() => {
  const win = effectiveWindow.value
  if (win && win > 0) return Math.min(100, Math.round((usedTokens.value / win) * 100))
  return dash.value
})

const shortTotal = computed<string>(() => (visible.value ? fmtCompact(usedTokens.value) : ''))

const cacheHitRate = computed<number | null>(() => composition.value?.cache_hit_rate ?? null)

/** 面板分类行配色：与图二契约对齐（消息/系统工具/MCP 工具/其他/技能/系统提示词）。 */
const SECTION_COLORS: Record<string, string> = {
  Messages: '#6aa5ff',
  SystemTools: '#7f8ea3',
  McpTools: '#9f7fff',
  Other: '#b0b6c0',
  Skills: '#4fc3a1',
  SystemPrompt: '#e6a23c',
}

const panelRows = computed(() => {
  const c = composition.value
  if (!c) return []
  const msgs = c.messages?.buckets ?? {}
  const tools = c.tools ?? {}
  const total = Math.max(1, c.total_tokens || 0)
  // key → i18n camelCase 键尾（ctxSectionMessages / ctxSectionSystemTools / ...）
  const raw: Array<{ key: string; tokens: number }> = [
    { key: 'Messages', tokens: (msgs.user?.tokens || 0) + (msgs.assistant?.tokens || 0) + (msgs.tool?.tokens || 0) },
    { key: 'SystemTools', tokens: tools.system?.tokens || 0 },
    { key: 'McpTools', tokens: tools.mcp?.tokens || 0 },
    { key: 'Other', tokens: (msgs.other?.tokens || 0) },
    { key: 'Skills', tokens: tools.skill?.tokens || 0 },
    { key: 'SystemPrompt', tokens: msgs.system?.tokens || 0 },
  ]
  return raw
    .filter((r) => r.tokens > 0)
    .map((r) => ({
      key: r.key,
      label: t(`chat.ctxSection${r.key}`),
      color: SECTION_COLORS[r.key] || '#b0b6c0',
      pct: Math.max(1, Math.round((r.tokens / total) * 100)),
    }))
})

const barSegments = computed(() =>
  panelRows.value.map((r) => ({ key: r.key, pct: r.pct, color: r.color })),
)

function fmtCompact(n: number | null | undefined): string {
  if (!n && n !== 0) return '—'
  if (n >= 100_000_000) return `${(n / 100_000_000).toFixed(1)}亿`
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)}万`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

/** 拉 composition 快照（usage 空时环图兜底 + 面板数据源）。404=尚无实测。 */
async function fetchComposition(): Promise<void> {
  if (!props.agentId || compositionFetched.value) return
  compositionFetched.value = true
  try {
    const res: any = await api.get('/context/composition', { params: { agent_id: props.agentId } })
    const data = res?.data ?? res
    if (data && data.total_tokens !== undefined) composition.value = data
  } catch {
    // 404/网络失败 = 暂无实测快照，环图退回 usage 语义，面板不渲染
  }
}

function openPanel(): void {
  panelOpen.value = true
  cancelClose()
  void fetchComposition()
}

function scheduleClose(): void {
  cancelClose()
  closeTimer = setTimeout(() => {
    panelOpen.value = false
  }, 250)
}

function cancelClose(): void {
  if (closeTimer) {
    clearTimeout(closeTimer)
    closeTimer = null
  }
}

// 会话/agent 切换后允许重拉（同 agent 快照不变，仅在从未拉过时取）
watch(
  () => [props.agentId, props.sessionId],
  () => {
    compositionFetched.value = false
    composition.value = null
    if (props.agentId && !props.usage) void fetchComposition()
  },
  { immediate: true },
)
</script>

<style scoped>
.nr-ctx-usage {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 10px;
  cursor: default;
}
.nr-ctx-ring-bg {
  stroke: var(--nr-border, rgba(128, 128, 128, 0.25));
}
.nr-ctx-ring-fg {
  stroke: var(--nr-primary, #4a9eff);
  transition: stroke-dasharray 0.4s ease, stroke 0.3s ease;
}
.nr-ctx-usage--warn .nr-ctx-ring-fg {
  stroke: #e6a23c;
}
.nr-ctx-usage--danger .nr-ctx-ring-fg {
  stroke: #f56c6c;
}
.nr-ctx-usage-text {
  font-size: 11px;
  color: var(--nr-text-secondary, #8a8f99);
  line-height: 1;
  white-space: nowrap;
}

/* ── 悬停明细面板（玻璃风格，向上弹出） ── */
.nr-ctx-panel {
  position: absolute;
  right: 0;
  bottom: calc(100% + 10px);
  width: 264px;
  padding: 14px 16px 12px;
  border-radius: 14px;
  border: 1px solid var(--nr-border, rgba(128, 128, 128, 0.25));
  background: var(--nr-bg-elevated, rgba(28, 32, 44, 0.92));
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.28);
  z-index: 60;
}

.nr-ctx-panel-title {
  font-size: 12px;
  color: var(--nr-text-secondary, #9aa0ac);
  margin-bottom: 6px;
}

.nr-ctx-panel-headline {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 10px;
}

.nr-ctx-panel-big {
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary, #e8eaf0);
}

.nr-ctx-panel-sep,
.nr-ctx-panel-total {
  font-size: 12px;
  color: var(--nr-text-tertiary, #7a7f8a);
}

.nr-ctx-panel-pct {
  margin-left: auto;
  font-size: 12px;
  color: var(--nr-text-secondary, #9aa0ac);
}

.nr-ctx-panel-bar {
  display: flex;
  height: 6px;
  border-radius: 3px;
  overflow: hidden;
  gap: 2px;
  margin-bottom: 10px;
}

.nr-ctx-panel-bar-seg {
  height: 100%;
  border-radius: 2px;
  min-width: 3px;
  opacity: 0.85;
}

.nr-ctx-panel-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nr-ctx-panel-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.nr-ctx-panel-dot {
  width: 8px;
  height: 8px;
  border-radius: 3px;
  flex-shrink: 0;
}

.nr-ctx-panel-label {
  color: var(--nr-text-secondary, #b6bcc8);
}

.nr-ctx-panel-value {
  margin-left: auto;
  color: var(--nr-text-primary, #e8eaf0);
  font-variant-numeric: tabular-nums;
}

.nr-ctx-panel-footer {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
  font-size: 12px;
  color: var(--nr-text-secondary, #9aa0ac);
  display: flex;
  justify-content: space-between;
}

.nr-ctx-panel-footer b {
  color: #67c23a;
  font-weight: 600;
}

/* 弹出过渡 */
.nr-ctx-pop-enter-active,
.nr-ctx-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}
.nr-ctx-pop-enter-from,
.nr-ctx-pop-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.97);
}
</style>
