<script setup lang="ts">
/**
 * DebugPanel.vue — 调试面板（断点 + Mock + 单步控制）
 *
 * 渲染 DebugController 状态；用户操作通过 emit 通知父组件。
 * 不在此组件内直接调 API（保持纯渲染，便于单测与复用）。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  buildStepModePayload,
  type DebugController,
  type StepMode,
} from './DebugPanel'

const props = defineProps<{
  controller: DebugController
  executionId: string
}>()

const emit = defineEmits<{
  (e: 'toggle-breakpoint', nodeId: string): void
  (e: 'clear-mock', nodeId: string): void
  (e: 'resume', payload: Record<string, unknown>): void
}>()

const { t } = useI18n()

const breakpointList = computed(() => Array.from(props.controller.breakpoints.value))
const mockList = computed(() => Array.from(props.controller.nodeMocks.value.entries()))

function handleResume() {
  emit('resume', buildStepModePayload(props.controller.stepMode.value))
}

function handleStepChange(mode: StepMode) {
  props.controller.setStepMode(mode)
  // 单步按钮触发立即 resume（带 step 模式）
  emit('resume', buildStepModePayload(mode))
}

function handleToggle(nodeId: string) {
  props.controller.toggleBreakpoint(nodeId)
  emit('toggle-breakpoint', nodeId)
}

function handleClearMock(nodeId: string) {
  props.controller.clearMock(nodeId)
  emit('clear-mock', nodeId)
}
</script>

<template>
  <div class="debug-panel" data-testid="debug-panel">
    <div class="debug-panel-header">
      <span class="debug-panel-title">{{ t('debug.panelTitle') }}</span>
      <span class="debug-panel-exec" :title="executionId">{{ executionId.slice(0, 12) }}</span>
    </div>

    <section class="debug-section">
      <div class="debug-section-title">
        {{ t('debug.breakpointsTitle') }}
        <span class="debug-count">({{ breakpointList.length }})</span>
      </div>
      <div v-if="breakpointList.length === 0" class="debug-empty">
        {{ t('debug.breakpointsEmpty') }}
      </div>
      <ul v-else class="debug-list">
        <li v-for="nodeId in breakpointList" :key="nodeId" class="debug-list-item">
          <span class="debug-node-id">{{ nodeId }}</span>
          <a-button size="small" type="text" danger @click="handleToggle(nodeId)">
            {{ t('debug.removeBreakpoint') }}
          </a-button>
        </li>
      </ul>
    </section>

    <section class="debug-section">
      <div class="debug-section-title">
        {{ t('debug.mocksTitle') }}
        <span class="debug-count">({{ mockList.length }})</span>
      </div>
      <div v-if="mockList.length === 0" class="debug-empty">
        {{ t('debug.mocksEmpty') }}
      </div>
      <ul v-else class="debug-list">
        <li v-for="[nodeId, value] in mockList" :key="nodeId" class="debug-list-item">
          <span class="debug-node-id">{{ nodeId }}</span>
          <code class="debug-mock-value">{{ JSON.stringify(value).slice(0, 40) }}</code>
          <a-button size="small" type="text" danger @click="handleClearMock(nodeId)">
            {{ t('debug.clearMock') }}
          </a-button>
        </li>
      </ul>
    </section>

    <section class="debug-section">
      <div class="debug-section-title">{{ t('debug.stepControlTitle') }}</div>
      <div class="debug-step-buttons">
        <a-button size="small" @click="handleStepChange('in')" data-testid="step-in">
          {{ t('debug.stepIn') }}
        </a-button>
        <a-button size="small" @click="handleStepChange('over')" data-testid="step-over">
          {{ t('debug.stepOver') }}
        </a-button>
        <a-button size="small" @click="handleStepChange('out')" data-testid="step-out">
          {{ t('debug.stepOut') }}
        </a-button>
      </div>
      <a-button
        type="primary"
        block
        class="debug-resume-btn"
        data-testid="resume"
        @click="handleResume"
      >
        {{ t('debug.resume') }}
      </a-button>
    </section>
  </div>
</template>

<style scoped>
.debug-panel {
  position: fixed;
  right: 16px;
  top: 80px;
  width: 320px;
  max-height: calc(100vh - 100px);
  overflow-y: auto;
  background: var(--nr-bg-elevated, #ffffff);
  border: 1px solid var(--nr-border, #e5e7eb);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  padding: 12px;
  z-index: 100;
}
.debug-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--nr-border, #e5e7eb);
}
.debug-panel-title {
  font-weight: 600;
  font-size: 14px;
}
.debug-panel-exec {
  font-size: 11px;
  color: var(--nr-text-tertiary, #6b7280);
  font-family: monospace;
}
.debug-section {
  margin-bottom: 16px;
}
.debug-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--nr-text-secondary, #4b5563);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.debug-count {
  color: var(--nr-text-tertiary, #6b7280);
  font-weight: 400;
}
.debug-empty {
  font-size: 12px;
  color: var(--nr-text-tertiary, #6b7280);
  font-style: italic;
  padding: 8px 0;
}
.debug-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.debug-list-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 12px;
}
.debug-node-id {
  flex: 0 0 auto;
  font-family: monospace;
  background: var(--nr-bg-muted, #f3f4f6);
  padding: 2px 6px;
  border-radius: 3px;
}
.debug-mock-value {
  flex: 1;
  font-size: 11px;
  color: var(--nr-text-tertiary, #6b7280);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.debug-step-buttons {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}
.debug-resume-btn {
  margin-top: 4px;
}
</style>