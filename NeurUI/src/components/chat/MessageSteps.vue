<template>
  <div ref="rootRef" class="nr-msg-steps">
    <!-- 步骤化时间轴：推理/工具按到达顺序成段，独立折叠 -->
    <div v-if="steps && steps.length > 0" class="nr-steps-timeline">
      <div
        v-for="step in steps"
        :key="step.id"
        class="nr-step-item"
        :class="[`nr-step--${step.kind}`, { 'is-active': step.active, 'is-open': step.open }]"
      >
        <div class="nr-step-header" @click="onToggle(step.id)">
          <span class="nr-step-icon"><UiIcon :name="stepIcon(step)" :size="14" /></span>
          <span class="nr-step-title">{{ stepTitle(step) }}</span>
          <span v-if="step.active" class="nr-step-badge is-running">{{ t('chat.stepRunning') }}</span>
          <span v-else-if="step.kind === 'tool'" class="nr-step-badge" :class="!step.result || isToolFailureResult(step.result) ? 'is-error' : 'is-done'">
            {{ !step.result ? t('chat.stepNoResult') : isToolFailureResult(step.result) ? t('chat.toolFailed') : t('chat.toolDone') }}
          </span>
          <span v-if="stepDurationText(step)" class="nr-step-duration">{{ stepDurationText(step) }}</span>
          <span class="nr-step-toggle">{{ step.open ? '▾' : '▸' }}</span>
        </div>
        <div v-show="step.open" class="nr-step-body">
          <template v-if="step.kind !== 'tool'">
            <div class="nr-step-reasoning" @scroll="onReasoningScroll">{{ step.text }}</div>
          </template>
          <template v-else>
            <pre class="nr-tool-args">{{ formatJSON(step.arguments) }}</pre>
            <div v-if="isBackgroundResult(step.result)" class="nr-tool-background">
              {{ t('chat.toolBackgroundHint') }}
            </div>
            <div v-if="step.result" class="nr-tool-result">
              <div class="nr-tool-result-header">
                {{ t('chat.toolResult') }}
                <button
                  class="nr-tool-result-preview-btn"
                  :title="t('chat.openInPreview')"
                  @click.stop="emit('openToolArtifacts', step.result)"
                ><UiIcon name="eye" :size="12" /></button>
              </div>
              <pre class="nr-tool-result-content">{{ step.result }}</pre>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- Legacy reasoning block（旧消息无 steps 时兜底） -->
    <div v-if="!steps?.length && reasoning" class="nr-msg-reasoning">
      <div class="nr-reasoning-header" @click="reasoningOpen = !reasoningOpen">
        <span>💭 {{ t('chat.reasoning') }}</span>
        <span class="nr-reasoning-toggle">{{ reasoningOpen ? '▾' : '▸' }}</span>
      </div>
      <div v-show="reasoningOpen" class="nr-reasoning-content">
        {{ reasoning }}
      </div>
    </div>

    <!-- Legacy tool call blocks（旧消息无 steps 时兜底，含历史兼容单工具） -->
    <template v-if="!steps?.length && legacyTools && legacyTools.length > 0">
      <div v-for="(tc, tcIdx) in legacyTools" :key="tcIdx" class="nr-msg-tool-call">
        <div class="nr-tool-header" @click="toolOpen = !toolOpen">
          <span class="nr-tool-icon"><UiIcon :name="variantIcon(toolCardVariant(tc.name))" :size="14" /></span>
          <span class="nr-tool-name">{{ tc.name }}</span>
          <a-tag :color="isBackgroundResult(tc.result) ? 'warning' : isToolFailureResult(tc.result) ? 'error' : tc.result ? 'success' : 'processing'">
            {{ isBackgroundResult(tc.result) ? t('chat.toolBackground') : isToolFailureResult(tc.result) ? t('chat.toolFailed') : tc.result ? t('chat.toolDone') : t('chat.toolCalling') }}
          </a-tag>
          <span class="nr-tool-toggle">{{ toolOpen ? '▾' : '▸' }}</span>
        </div>
        <div v-show="toolOpen">
          <pre class="nr-tool-args">{{ formatJSON(tc.arguments) }}</pre>
          <div v-if="isBackgroundResult(tc.result)" class="nr-tool-background">
            {{ t('chat.toolBackgroundHint') }}
          </div>
          <div v-if="tc.result" class="nr-tool-result">
            <div class="nr-tool-result-header">
              {{ t('chat.toolResult') }}
              <button
                class="nr-tool-result-preview-btn"
                :title="t('chat.openInPreview')"
                @click.stop="emit('openToolArtifacts', tc.result)"
              ><UiIcon name="eye" :size="12" /></button>
            </div>
            <pre class="nr-tool-result-content">{{ tc.result }}</pre>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * MessageSteps.vue — 助手消息"过程"（推理/工具步骤时间轴）的共享渲染单元。
 *
 * 与 MessageContent 分工：本组件只呈现"怎么做出来的"（步骤段 + 旧数据兜底），
 * 正文由 MessageContent 呈现。折叠态、思考段滚动跟随等纯 UI 内聚于此；
 * 数据契约与所有派生逻辑复用 @/utils/chatSteps、toolCardVariant、toolCallStatus。
 * 工具结果"打开预览"属宿主能力（dock），以 emit 交回。
 */
import { nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import UiIcon from '@/components/UiIcon.vue'
import { toggleStep, isNearBottom, followActiveReasoningScroll, type ChatStep } from '@/utils/chatSteps'
import { toolCardVariant, variantIcon } from '@/utils/toolCardVariant'
import { isToolFailureResult, isBackgroundResult } from '@/utils/toolCallStatus'
import '@/styles/messageRender.css'

const props = defineProps<{
  steps?: ChatStep[]
  reasoning?: string
  legacyTools?: Array<{ name: string; arguments: string; result?: string }>
}>()

const emit = defineEmits<{ (e: 'openToolArtifacts', result?: string): void }>()

const { t } = useI18n()
const rootRef = ref<HTMLElement | null>(null)
const reasoningOpen = ref(!!props.reasoning)
const toolOpen = ref(false)

// 思考段滚动跟随：贴底则随流式追加自动滚到底，用户上翻即暂停。
const reasoningStick = ref(true)

function onToggle(stepId: string): void {
  if (props.steps) toggleStep(props.steps, stepId)
}

function stepIcon(step: ChatStep): string {
  if (step.kind === 'reasoning') return 'brain'
  if (step.kind === 'plan') return 'check'
  return variantIcon(toolCardVariant(step.name))
}

function stepTitle(step: ChatStep): string {
  if (step.kind === 'reasoning') return t('chat.stepThinking')
  if (step.kind === 'plan') return t('chat.stepPlan')
  return step.taskName || step.name || ''
}

/** 段落耗时文案（"持续 N 秒"；未封口的活跃段按当前时刻计）。 */
function stepDurationText(step: ChatStep): string {
  if (!step.startedAt) return ''
  const end = step.endedAt ?? Date.now()
  const secs = Math.max(1, Math.round((end - step.startedAt) / 1000))
  return t('chat.stepDuration', { n: secs })
}

function formatJSON(str?: string): string {
  if (!str) return ''
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch {
    return str
  }
}

function onReasoningScroll(e: Event): void {
  const el = e.target as HTMLElement
  reasoningStick.value = isNearBottom(el.scrollTop, el.scrollHeight, el.clientHeight)
}

function follow(): void {
  if (!reasoningStick.value) return
  nextTick(() => followActiveReasoningScroll(rootRef.value ?? undefined))
}

onMounted(follow)
watch(
  () => props.steps?.map((s) => `${s.id}:${(s.text || '').length}:${s.active ? 1 : 0}`).join('|'),
  follow,
)
</script>
