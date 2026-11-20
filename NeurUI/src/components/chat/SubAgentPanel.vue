<script setup lang="ts">
/**
 * 子 Agent 对话小窗（蜂群编排可视化）
 *
 * 显示主 Agent 派生的子 Agent 的任务与流式输出；支持最小化（折叠为标题条）、
 * 恢复、关闭。多个小窗在聊天页右下角堆叠（由父容器 flex 布局管理）。
 */
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import UiIcon from '@/components/UiIcon.vue'
import { isNearBottom } from '@/utils/chatSteps'
import { getConsoleSubagentEvents, type SubagentEvent } from '@/api/modules/console'

export interface SubAgentWindowState {
  subagentId: string
  agentName: string
  task: string
  /** 流式增量缓存（P2-15）：chunk 到达即追加，替代原 chunks 数组 + 每 chunk 全量 join */
  bodyText: string
  /** 已接收 chunk 计数 */
  chunkCount: number
  /** P1-3：in_review = 监督评审相位（验收通过后、终态前的把关段，占派生槽） */
  status: 'running' | 'in_review' | 'completed' | 'failed'
  report: string
  error?: string | null
  /** P1（蜂群对照）：子代理类型（general/explore）；explore = 工具面收窄为只读白名单 */
  subagentType?: string
  /** S10：团队溯源标（dispatch_team 派生的 run 带团队徽标） */
  teamId?: string
  /** F5：谱系归因（派生链根→叶；嵌套派生时显示派生链徽标，台账回填路径缺席属预期降级） */
  agentPath?: string[]
  /** P2（蜂群对照）：卡死渐进提醒——后端看门狗判 member 连续无产出后携带 */
  stallNotice?: { stalledSeconds: number; reminderCount: number }
}

const props = defineProps<{ state: SubAgentWindowState }>()
const emit = defineEmits<{ (e: 'close', subagentId: string): void }>()
const { t } = useI18n()

const minimized = ref(false)

const title = computed(() => `${props.state.agentName || t('ui.subagent')} · ${props.state.status}`)

/** S10：团队徽标展示名（uuid 截短显示，完整 id 进 tooltip） */
const teamBadge = computed(() => {
  const tid = props.state.teamId || ''
  if (!tid) return ''
  return tid.length > 10 ? `${tid.slice(0, 10)}…` : tid
})

/** F5：谱系徽标（仅嵌套派生显示——单元素路径是自身，展示为噪音） */
const lineageBadge = computed(() => {
  const path = props.state.agentPath || []
  if (path.length < 2) return ''
  return path.map((id) => (id.length > 10 ? `${id.slice(0, 10)}…` : id)).join(' › ')
})

const bodyText = computed(() => {
  const busy = props.state.status === 'running' || props.state.status === 'in_review'
  if (!busy && props.state.report) return props.state.report
  return props.state.bodyText
})

const statusIcon = computed(() => {
  if (props.state.status === 'running' || props.state.status === 'in_review') return 'clock'
  if (props.state.status === 'failed') return 'x'
  return 'check'
})

/** 运行中或评审中：光标/思考态/卡死提醒都按"仍在推进"处理 */
const isBusy = computed(() => props.state.status === 'running' || props.state.status === 'in_review')

function toggleMinimize() {
  minimized.value = !minimized.value
}

// 流式输出滚动跟随（2026-09-12 与 ChatPage 思考段同根因）：
// .panel-content 出内部滚动条后贴底展示最新输出；用户向上翻阅（距底超
// 阈值）暂停跟随，回到底部附近恢复。stick 判定取自滚动事件（追加前的
// 状态），不受本次 chunk 增长影响。
const outputEl = ref<HTMLElement | null>(null)
const outputStick = ref(true)

watch(bodyText, () => {
  if (!outputStick.value) return
  void nextTick(() => {
    const el = outputEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
})

function onOutputScroll(e: Event): void {
  const el = e.target as HTMLElement
  outputStick.value = isNearBottom(el.scrollTop, el.scrollHeight, el.clientHeight)
}

// ── H-4 事件时间线：subagent_status(view=events) 读侧的可视化 ──────────
const showTimeline = ref(false)
const timeline = ref<SubagentEvent[]>([])
const timelineLoading = ref(false)
let timelineTimer: ReturnType<typeof setInterval> | null = null

async function fetchTimeline(): Promise<void> {
  timelineLoading.value = true
  try {
    const res = await getConsoleSubagentEvents(props.state.subagentId)
    timeline.value = res.data?.events ?? []
  } catch {
    timeline.value = []
  } finally {
    timelineLoading.value = false
  }
}

function stopTimelinePolling(): void {
  if (timelineTimer !== null) {
    clearInterval(timelineTimer)
    timelineTimer = null
  }
}

function toggleTimeline(): void {
  showTimeline.value = !showTimeline.value
  stopTimelinePolling()
  if (showTimeline.value) {
    void fetchTimeline()
    // 运行中每 5s 刷新一次账本；终态到达时补拉最终版并停止
    if (isBusy.value) timelineTimer = setInterval(() => void fetchTimeline(), 5000)
  }
}

watch(() => props.state.status, (status) => {
  if (showTimeline.value && status !== 'running' && status !== 'in_review') {
    stopTimelinePolling()
    void fetchTimeline()
  }
})

onUnmounted(stopTimelinePolling)

function eventLabel(type: string): string {
  const map: Record<string, string> = {
    spawned: t('ui.subagentEvSpawned'),
    started: t('ui.subagentEvStarted'),
    stalled: t('ui.subagentEvStalled'),
    escalated: t('ui.subagentEvEscalated'),
    update_injected: t('ui.subagentEvUpdate'),
    cancelled: t('ui.subagentEvCancelled'),
    terminal: t('ui.subagentEvTerminal'),
  }
  return map[type] || type
}

function eventDetail(ev: SubagentEvent): string {
  const p = (ev.payload || {}) as Record<string, unknown>
  if (ev.type === 'spawned') return String(p.task || '')
  if (ev.type === 'terminal') return [p.status, p.cause || p.error].filter(Boolean).map(String).join(' · ')
  if (ev.type === 'stalled') return `${String(p.stalled_seconds || '')}s`
  if (ev.type === 'escalated') return String(p.reason || '')
  if (ev.type === 'update_injected') return String(p.message || '')
  if (ev.type === 'cancelled') return String(p.reason || '')
  return ''
}

function shortTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString()
}
</script>

<template>
  <div class="subagent-panel" :class="[`status-${state.status}`, { minimized }]">
    <div class="panel-header" @click="toggleMinimize">
      <span class="panel-icon"><UiIcon :name="statusIcon" :size="14" /></span>
      <span class="panel-title" :title="state.task">{{ title }}</span>
      <!-- P1（蜂群对照）：非默认类型的子代理显示类型徽标（explore=只读白名单收窄面） -->
      <span
        v-if="state.subagentType && state.subagentType !== 'general'"
        class="panel-type-chip"
        :title="state.subagentType"
      >{{ state.subagentType }}</span>
      <!-- S10：团队徽标（dispatch_team 派生的 run 带团队溯源标） -->
      <span
        v-if="teamBadge"
        class="panel-type-chip team-chip"
        :title="`${t('collab.teams')}: ${state.teamId}`"
      >◈ {{ teamBadge }}</span>
      <!-- F5：谱系徽标（嵌套派生链根→叶，完整链进 tooltip） -->
      <span
        v-if="lineageBadge"
        class="panel-type-chip lineage-chip"
        :title="`${t('ui.subagentLineage')}: ${(state.agentPath || []).join(' › ')}`"
      >⛓ {{ lineageBadge }}</span>
      <button class="panel-btn" :title="t('ui.subagentTimeline')" @click.stop="toggleTimeline">≡</button>
      <button class="panel-btn" :title="minimized ? t('ui.expand') : t('ui.minimize')" @click.stop="toggleMinimize">
        {{ minimized ? '▢' : '—' }}
      </button>
      <button class="panel-btn" :title="t('common.close')" @click.stop="emit('close', state.subagentId)">✕</button>
    </div>
    <div v-if="!minimized" class="panel-body">
      <div class="panel-task" :title="state.task">{{ state.task }}</div>
      <!-- H-4 事件时间线：run 事件账本的可视化（发现而不裁决的观测面） -->
      <div v-if="showTimeline" class="panel-timeline">
        <div v-if="timelineLoading && !timeline.length" class="tl-empty">{{ t('ui.thinking') }}</div>
        <div v-else-if="!timeline.length" class="tl-empty">{{ t('ui.subagentTimelineEmpty') }}</div>
        <div v-for="ev in timeline" :key="ev.event_id" class="tl-row">
          <span class="tl-dot" :class="`tl-${ev.type}`"></span>
          <div class="tl-body">
            <div class="tl-head">{{ eventLabel(ev.type) }}<span class="tl-time"> · {{ shortTime(ev.occurred_at) }}</span></div>
            <div v-if="eventDetail(ev)" class="tl-detail">{{ eventDetail(ev) }}</div>
          </div>
        </div>
      </div>
      <!-- P2（蜂群对照）：卡死渐进提醒（发现而不裁决：只提示，等/停由用户决定） -->
      <div v-if="isBusy && state.stallNotice" class="panel-stall">
        ⏸ {{ t('ui.subagentStalled', { minutes: Math.max(1, Math.round(state.stallNotice.stalledSeconds / 60)), count: state.stallNotice.reminderCount }) }}
      </div>
      <div ref="outputEl" class="panel-content" @scroll="onOutputScroll">
        <template v-if="state.status === 'failed'">⚠ {{ state.error || t('ui.execFailed') }}</template>
        <template v-else-if="bodyText">{{ bodyText }}<span v-if="isBusy" class="cursor">▌</span></template>
        <template v-else-if="isBusy"><span class="cursor">▌</span> {{ t('ui.thinking') }}</template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.subagent-panel {
  width: 300px;
  max-height: 320px;
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  border: 1px solid rgba(99, 102, 241, 0.35);
  background: rgba(15, 18, 32, 0.96);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  overflow: hidden;
  backdrop-filter: blur(8px);
}
.subagent-panel.status-running { border-color: rgba(250, 204, 21, 0.5); }
.subagent-panel.status-completed { border-color: rgba(74, 222, 128, 0.45); }
.subagent-panel.status-failed { border-color: rgba(248, 113, 113, 0.55); }
.subagent-panel.minimized { max-height: none; }

.panel-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  cursor: pointer;
  background: rgba(99, 102, 241, 0.12);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  user-select: none;
}
.subagent-panel.minimized .panel-header { border-bottom: none; }
.panel-icon { font-size: 13px; }
.panel-title {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: var(--nr-text-primary, #e2e8f0);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.panel-type-chip {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 8px;
  border: 1px solid var(--nr-border, rgba(99, 102, 241, 0.35));
  color: var(--nr-text-secondary, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.panel-type-chip.team-chip { color: var(--nr-primary-light, #818cf8); text-transform: none; }
.panel-type-chip.lineage-chip { color: var(--nr-text-secondary, #94a3b8); text-transform: none; }
.panel-btn {
  border: none;
  background: transparent;
  color: var(--nr-text-tertiary, var(--nr-text-tertiary));
  cursor: pointer;
  font-size: 12px;
  padding: 0 3px;
}
.panel-btn:hover { color: var(--nr-text-primary, #e2e8f0); }

.panel-body { display: flex; flex-direction: column; min-height: 0; }
.panel-task {
  padding: 6px 10px 2px;
  font-size: 11px;
  color: var(--nr-text-tertiary, var(--nr-text-tertiary));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.panel-stall {
  margin: 2px 10px 0;
  padding: 3px 8px;
  font-size: 11px;
  line-height: 1.4;
  border-radius: 6px;
  border: 1px solid var(--nr-warning-soft-border, rgba(245, 158, 11, 0.35));
  background: var(--nr-warning-soft-bg, rgba(245, 158, 11, 0.12));
  color: var(--nr-text-secondary, #cbd5e1);
}
.panel-content {
  padding: 4px 10px 10px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--nr-text-secondary, #cbd5e1);
  white-space: pre-wrap;
  word-break: break-all;
  overflow-y: auto;
  max-height: 240px;
}
.cursor { animation: blink 1s step-start infinite; color: var(--nr-primary-light, #818cf8); }
@keyframes blink { 50% { opacity: 0; } }

.panel-timeline {
  margin: 4px 10px 0;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--nr-border, rgba(99, 102, 241, 0.25));
  background: rgba(99, 102, 241, 0.06);
  max-height: 140px;
  overflow-y: auto;
}
.tl-empty { font-size: 11px; color: var(--nr-text-tertiary, var(--nr-text-tertiary)); }
.tl-row { display: flex; gap: 6px; padding: 3px 0; align-items: flex-start; }
.tl-row + .tl-row { border-top: 1px dashed rgba(255, 255, 255, 0.06); }
.tl-dot {
  flex-shrink: 0;
  width: 7px; height: 7px;
  margin-top: 4px;
  border-radius: 50%;
  background: var(--nr-primary-light, #818cf8);
}
.tl-dot.tl-terminal { background: var(--nr-success, rgba(74, 222, 128, 0.9)); }
.tl-dot.tl-failed, .tl-dot.tl-cancelled { background: var(--nr-error, rgba(248, 113, 113, 0.9)); }
.tl-dot.tl-stalled { background: var(--nr-warning, rgba(245, 158, 11, 0.9)); }
.tl-head { font-size: 11px; font-weight: 600; color: var(--nr-text-primary, #e2e8f0); }
.tl-time { font-weight: 400; color: var(--nr-text-tertiary, var(--nr-text-tertiary)); }
.tl-detail {
  font-size: 11px;
  color: var(--nr-text-secondary, #cbd5e1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 240px;
}
</style>
