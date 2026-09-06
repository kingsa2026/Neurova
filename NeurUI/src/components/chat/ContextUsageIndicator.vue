<template>
  <div
    v-if="usage"
    class="nr-ctx-usage"
    :class="{ 'nr-ctx-usage--warn': level === 'warn', 'nr-ctx-usage--danger': level === 'danger' }"
    :title="tooltip"
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
  </div>
</template>

<script setup lang="ts">
/**
 * Token/上下文用量环形仪表（QwenPaw ContextUsageIndicator 对齐）。
 *
 * 双语义：
 * - 有 context-window（当前模型限额已知）：环 = context 占比，双色告警
 *   （75% 变橙 / 90% 变红）；
 * - 无 context-window：环 = completion/prompt 比（产出密度），仅展示 token 总量。
 * 无任何 usage 记录时整个指示器不渲染。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

interface TurnUsage {
  prompt: number
  completion: number
  total: number
}

const props = defineProps<{
  usage: TurnUsage | null
  contextWindow?: number | null
}>()

const { t } = useI18n()

/** 环形进度百分比（0-100，封顶）。 */
const dash = computed<number>(() => {
  if (!props.usage) return 0
  if (props.contextWindow && props.contextWindow > 0) {
    return Math.min(100, Math.round((props.usage.total / props.contextWindow) * 100))
  }
  const denom = props.usage.prompt || 1
  return Math.min(100, Math.round((props.usage.completion / denom) * 100))
})

const level = computed<'ok' | 'warn' | 'danger'>(() => {
  if (dash.value >= 90) return 'danger'
  if (dash.value >= 75) return 'warn'
  return 'ok'
})

const shortTotal = computed<string>(() => {
  if (!props.usage) return ''
  const n = props.usage.total
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
})

const tooltip = computed<string>(() => {
  if (!props.usage) return ''
  const parts = [
    t('chat.usagePrompt', { n: props.usage.prompt }),
    t('chat.usageCompletion', { n: props.usage.completion }),
  ]
  if (props.contextWindow && props.contextWindow > 0) {
    parts.push(t('chat.usageContextPct', { pct: dash.value }))
  }
  return parts.join(' · ')
})
</script>

<style scoped>
.nr-ctx-usage {
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
</style>
