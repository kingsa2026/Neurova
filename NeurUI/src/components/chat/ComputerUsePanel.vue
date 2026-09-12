<script setup lang="ts">
/**
 * 电脑操作分屏面板（ZCode 式跟随视图）
 *
 * Agent 调用 computer_* 与 browser_* 工具时由聊天页自动展开：
 * 上半部分实时显示操作截图（WS computer_action 事件推送），
 * 下方为动作日志；同时保留手动控制（点击截图/导航/Shell），
 * 复用"电脑操控"页同款 REST 接口。
 */
import { ref, computed } from 'vue'
import UiIcon from '@/components/UiIcon.vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import type { ComputerPanelState } from '@/composables/useComputerPanel'
import { screenshot as apiScreenshot, click as apiClick, navigate as apiNavigate, shell as apiShell } from '@/api/modules/computer'

const props = defineProps<{
  state: ComputerPanelState
  agentId?: string
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const { t } = useI18n()

const manualNavUrl = ref('')
const manualCommand = ref('')
const manualLoading = ref(false)
const lastClickCoords = ref<{ x: number; y: number } | null>(null)
const shotImgEl = ref<HTMLImageElement | null>(null)

/** R2-5 agent 点击标记：截图像素坐标 → 图片容器百分比（跟随 object-fit 缩放） */
const markerStyle = computed(() => {
  const m = props.state.clickMarker
  const img = shotImgEl.value
  if (!m || !img || !img.naturalWidth || !img.naturalHeight) return null
  return {
    left: `${(m.x / img.naturalWidth) * 100}%`,
    top: `${(m.y / img.naturalHeight) * 100}%`,
  }
})

const statusText = computed(() => (props.state.busy ? t('computerPanel.live') : t('computerPanel.idle')))

function formatTime(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function extractPayload(resp: any): any {
  // 兼容 axios 包装 / {code,message,data} 包装 / 裸数据
  if (resp?.data?.data !== undefined) return resp.data.data
  if (resp?.data !== undefined) return resp.data
  return resp ?? {}
}

/** 手动刷新截图（REST 直取，不依赖 Agent 执行） */
async function refreshScreenshot() {
  if (!props.agentId) {
    message.warning(t('computerPanel.selectAgentFirst'))
    return
  }
  manualLoading.value = true
  try {
    const res: any = await apiScreenshot(props.agentId)
    const data = extractPayload(res)
    const b64 = data?.base64 || data?.image || ''
    if (b64) {
      props.state.latestScreenshot = `data:image/png;base64,${b64}`
    } else {
      message.warning(t('computerPanel.screenshotFailed'))
    }
  } catch {
    message.warning(t('computerPanel.screenshotFailed'))
  } finally {
    manualLoading.value = false
  }
}

/** 点击截图位置 → 换算真实屏幕坐标并控制鼠标 */
async function onScreenshotClick(e: MouseEvent) {
  if (!props.agentId) return
  const img = e.target as HTMLImageElement
  const rect = img.getBoundingClientRect()
  const x = Math.round(((e.clientX - rect.left) * img.naturalWidth) / rect.width)
  const y = Math.round(((e.clientY - rect.top) * img.naturalHeight) / rect.height)
  lastClickCoords.value = { x, y }
  try {
    await apiClick(props.agentId, x, y)
    await refreshScreenshot()
  } catch {
    message.warning(t('computerPanel.actionFailed'))
  }
}

/** 手动导航浏览器 */
async function doNavigate() {
  const url = manualNavUrl.value.trim()
  if (!url || !props.agentId) return
  manualLoading.value = true
  try {
    await apiNavigate(props.agentId, url)
    manualNavUrl.value = ''
    await refreshScreenshot()
  } catch {
    message.warning(t('computerPanel.actionFailed'))
  } finally {
    manualLoading.value = false
  }
}

/** 手动执行 Shell */
async function doRunCommand() {
  const command = manualCommand.value.trim()
  if (!command || !props.agentId) return
  manualLoading.value = true
  try {
    await apiShell(props.agentId, command)
    manualCommand.value = ''
  } catch {
    message.warning(t('computerPanel.actionFailed'))
  } finally {
    manualLoading.value = false
  }
}
</script>

<template>
  <aside class="cu-panel" :class="{ minimized: state.minimized }">
    <!-- Header -->
    <div class="cu-header">
      <span class="cu-icon"><UiIcon name="monitor" :size="15" /></span>
      <span class="cu-title">{{ t('computerPanel.title') }}</span>
      <span class="cu-status" :class="{ busy: state.busy }">
        <span class="cu-status-dot" />{{ statusText }}
      </span>
      <button class="cu-btn" :title="t('computerPanel.refreshShot')" @click.stop="refreshScreenshot"><UiIcon name="reload" :size="13" /></button>
      <button class="cu-btn" :title="state.minimized ? t('ui.expand') : t('ui.minimize')" @click.stop="state.minimized = !state.minimized">
        {{ state.minimized ? '▢' : '—' }}
      </button>
      <button class="cu-btn" :title="t('common.close')" @click.stop="emit('close')">✕</button>
    </div>

    <template v-if="!state.minimized">
      <!-- Screenshot viewport -->
      <div class="cu-shot-wrap">
        <div v-if="state.latestScreenshot" class="cu-shot-frame">
          <img
            ref="shotImgEl"
            :src="state.latestScreenshot"
            :alt="t('computerPanel.title')"
            class="cu-shot"
            :title="t('computerPanel.clickHint')"
            @click="onScreenshotClick"
          />
          <!-- R2-5 agent 点击位置标记（脉冲两次后淡出） -->
          <span v-if="markerStyle" class="cu-marker" :style="markerStyle" />
        </div>
        <div v-else class="cu-shot-empty">
          <span><UiIcon name="monitor" :size="13" /></span>
          <p>{{ t('computerPanel.empty') }}</p>
        </div>
        <div v-if="lastClickCoords" class="cu-coords">
          {{ t('computer.click') }}: ({{ lastClickCoords.x }}, {{ lastClickCoords.y }})
        </div>
      </div>

      <!-- Browser URL bar -->
      <div v-if="state.browserUrl" class="cu-urlbar">
        <span class="cu-url-icon"><UiIcon name="globe" :size="12" /></span>
        <span class="cu-url" :title="state.browserUrl">{{ state.browserUrl }}</span>
      </div>

      <!-- Action log -->
      <div class="cu-log">
        <div class="cu-log-head">
          <span>{{ t('computerPanel.actionsTitle') }}</span>
          <span class="cu-log-count">{{ state.actions.length }}</span>
        </div>
        <div class="cu-log-list">
          <div v-for="entry in [...state.actions].reverse()" :key="entry.id" class="cu-log-item" :class="{ failed: !entry.success }">
            <span class="cu-log-time">{{ formatTime(entry.timestamp) }}</span>
            <span class="cu-log-kind"><UiIcon :name="entry.kind === 'browser' ? 'globe' : 'monitor'" :size="12" /></span>
            <span class="cu-log-summary" :title="entry.error || entry.summary">
              {{ entry.summary }}
              <template v-if="entry.error"> · {{ entry.error }}</template>
            </span>
            <!-- R2-5 ActionResult 契约徽标：投递路径/效果；refused 显示精确拒绝码 -->
            <span
              v-if="entry.route"
              class="cu-badge"
              :class="{ refused: entry.effect === 'refused', unverified: entry.effect === 'unverifiable' }"
              :title="t('computerPanel.actionResultHint')"
            >
              {{ entry.effect === 'refused' ? entry.refusalCode : `${entry.route}·${entry.effect}` }}
            </span>
            <span class="cu-log-status">{{ entry.success ? '✓' : '✗' }}</span>
          </div>
          <div v-if="state.actions.length === 0" class="cu-log-empty">{{ t('computerPanel.empty') }}</div>
        </div>
      </div>

      <!-- Manual controls -->
      <div class="cu-manual">
        <input
          v-model="manualNavUrl"
          class="cu-input"
          :placeholder="t('computerPanel.navPlaceholder')"
          data-testid="cu-nav-input"
          @keydown.enter="doNavigate"
        />
        <button class="cu-go" :disabled="manualLoading || !manualNavUrl.trim()" @click="doNavigate">
          {{ t('computerPanel.go') }}
        </button>
        <input
          v-model="manualCommand"
          class="cu-input cu-input--mono"
          :placeholder="t('computerPanel.shellPlaceholder')"
          data-testid="cu-shell-input"
          @keydown.enter="doRunCommand"
        />
        <button class="cu-go" :disabled="manualLoading || !manualCommand.trim()" @click="doRunCommand">
          {{ t('computerPanel.run') }}
        </button>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.cu-panel {
  width: clamp(320px, 30vw, 480px);
  display: flex;
  flex-direction: column;
  border-left: 1px solid rgba(99, 102, 241, 0.25);
  background: rgba(13, 16, 28, 0.92);
  backdrop-filter: blur(10px);
  overflow: hidden;
}
.cu-panel.minimized {
  width: auto;
  border-left: none;
}

/* Header */
.cu-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(99, 102, 241, 0.08);
  user-select: none;
}
.cu-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary, #e2e8f0);
}
.cu-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--nr-text-tertiary, #94a3b8);
  margin-right: auto;
}
.cu-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #64748b;
}
.cu-status.busy .cu-status-dot {
  background: #facc15;
  animation: cu-pulse 1s ease-in-out infinite;
}
@keyframes cu-pulse {
  50% { opacity: 0.3; }
}
.cu-btn {
  border: none;
  background: transparent;
  color: var(--nr-text-tertiary, #94a3b8);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 5px;
  border-radius: 4px;
}
.cu-btn:hover { color: var(--nr-text-primary, #e2e8f0); background: rgba(255, 255, 255, 0.06); }

/* Screenshot */
.cu-shot-wrap {
  position: relative;
  min-height: 160px;
  max-height: 42%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.35);
  overflow: hidden;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.cu-shot {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  cursor: crosshair;
}
/* R2-5：图片容器（与 img 同尺寸），标记百分比相对它定位 */
.cu-shot-frame {
  position: relative;
  display: inline-flex;
  max-width: 100%;
  max-height: 100%;
}
/* R2-5：agent 点击位置标记（脉冲动画） */
.cu-marker {
  position: absolute;
  width: 14px;
  height: 14px;
  margin: -7px 0 0 -7px;
  border-radius: 50%;
  border: 2px solid #facc15;
  box-shadow: 0 0 0 2px rgba(250, 204, 21, 0.25);
  pointer-events: none;
  animation: cu-marker-pulse 1s ease-out 2;
}
@keyframes cu-marker-pulse {
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(1.8); opacity: 0; }
}
/* R2-5：ActionResult 契约徽标 */
.cu-badge {
  flex-shrink: 0;
  font-family: var(--nr-font-mono, monospace);
  font-size: 10px;
  line-height: 1;
  padding: 2px 5px;
  border-radius: 4px;
  color: #4ade80;
  background: rgba(74, 222, 128, 0.1);
  border: 1px solid rgba(74, 222, 128, 0.3);
}
.cu-badge.unverified {
  color: #facc15;
  background: rgba(250, 204, 21, 0.08);
  border-color: rgba(250, 204, 21, 0.3);
}
.cu-badge.refused {
  color: #fca5a5;
  background: rgba(252, 165, 165, 0.08);
  border-color: rgba(252, 165, 165, 0.3);
}
.cu-shot-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px;
  text-align: center;
}
.cu-shot-empty span { font-size: 28px; opacity: 0.4; }
.cu-shot-empty p {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--nr-text-tertiary, #94a3b8);
  max-width: 260px;
}
.cu-coords {
  position: absolute;
  left: 8px;
  bottom: 6px;
  font-family: var(--nr-font-mono, monospace);
  font-size: 11px;
  color: var(--nr-text-tertiary, #94a3b8);
  background: rgba(0, 0, 0, 0.55);
  padding: 2px 6px;
  border-radius: 4px;
}

/* URL bar */
.cu-urlbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  font-size: 11px;
  color: var(--nr-text-secondary, #cbd5e1);
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.cu-url {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
  text-align: left;
}

/* Action log */
.cu-log {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 80px;
}
.cu-log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--nr-text-tertiary, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.cu-log-count {
  font-weight: 400;
}
.cu-log-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 6px 6px;
}
.cu-log-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 4px 6px;
  font-size: 12px;
  line-height: 1.5;
  border-radius: 6px;
  color: var(--nr-text-secondary, #cbd5e1);
}
.cu-log-item:nth-child(odd) { background: rgba(255, 255, 255, 0.02); }
.cu-log-item.failed { color: #fca5a5; }
.cu-log-time {
  font-family: var(--nr-font-mono, monospace);
  font-size: 10px;
  color: var(--nr-text-tertiary, #64748b);
  flex-shrink: 0;
}
.cu-log-summary {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cu-log-status { flex-shrink: 0; font-size: 11px; }
.cu-log-item:not(.failed) .cu-log-status { color: #4ade80; }
.cu-log-empty {
  padding: 14px;
  text-align: center;
  font-size: 12px;
  color: var(--nr-text-tertiary, #64748b);
}

/* Manual controls */
.cu-manual {
  display: grid;
  grid-template-columns: 1fr auto 1fr auto;
  gap: 6px;
  padding: 8px 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
}
.cu-input {
  min-width: 0;
  height: 26px;
  padding: 0 8px;
  font-size: 11px;
  color: var(--nr-text-primary, #e2e8f0);
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  outline: none;
}
.cu-input:focus { border-color: rgba(129, 140, 248, 0.6); }
.cu-input--mono { font-family: var(--nr-font-mono, monospace); }
.cu-go {
  height: 26px;
  padding: 0 10px;
  font-size: 11px;
  color: #fff;
  background: rgba(99, 102, 241, 0.75);
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.cu-go:disabled { opacity: 0.4; cursor: not-allowed; }
.cu-go:hover:not(:disabled) { background: rgba(99, 102, 241, 0.95); }

@media (max-width: 900px) {
  .cu-panel { position: absolute; right: 0; top: 0; bottom: 0; z-index: 30; }
  .cu-manual { grid-template-columns: 1fr auto; }
}
</style>
