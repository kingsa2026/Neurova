<script setup lang="ts">
/**
 * 子 Agent 对话小窗（蜂群编排可视化）
 *
 * 显示主 Agent 派生的子 Agent 的任务与流式输出；支持最小化（折叠为标题条）、
 * 恢复、关闭。多个小窗在聊天页右下角堆叠（由父容器 flex 布局管理）。
 */
import { computed, ref } from 'vue'

export interface SubAgentWindowState {
  subagentId: string
  agentName: string
  task: string
  chunks: { type: string; data: string }[]
  status: 'running' | 'completed' | 'failed'
  report: string
  error?: string | null
}

const props = defineProps<{ state: SubAgentWindowState }>()
const emit = defineEmits<{ (e: 'close', subagentId: string): void }>()

const minimized = ref(false)

const title = computed(() => `${props.state.agentName || '子 Agent'} · ${props.state.status}`)

const bodyText = computed(() => {
  if (props.state.status !== 'running' && props.state.report) return props.state.report
  return props.state.chunks.map(c => c.data).join('')
})

const statusIcon = computed(() => {
  if (props.state.status === 'running') return '⏳'
  if (props.state.status === 'failed') return '❌'
  return '✅'
})

function toggleMinimize() {
  minimized.value = !minimized.value
}
</script>

<template>
  <div class="subagent-panel" :class="[`status-${state.status}`, { minimized }]">
    <div class="panel-header" @click="toggleMinimize">
      <span class="panel-icon">{{ statusIcon }}</span>
      <span class="panel-title" :title="state.task">{{ title }}</span>
      <button class="panel-btn" :title="minimized ? '展开' : '最小化'" @click.stop="toggleMinimize">
        {{ minimized ? '▢' : '—' }}
      </button>
      <button class="panel-btn" title="关闭" @click.stop="emit('close', state.subagentId)">✕</button>
    </div>
    <div v-if="!minimized" class="panel-body">
      <div class="panel-task" :title="state.task">{{ state.task }}</div>
      <div class="panel-content">
        <template v-if="state.status === 'failed'">⚠ {{ state.error || '执行失败' }}</template>
        <template v-else-if="bodyText">{{ bodyText }}<span v-if="state.status === 'running'" class="cursor">▌</span></template>
        <template v-else-if="state.status === 'running'"><span class="cursor">▌</span> 思考中…</template>
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
.panel-btn {
  border: none;
  background: transparent;
  color: var(--nr-text-tertiary, #94a3b8);
  cursor: pointer;
  font-size: 12px;
  padding: 0 3px;
}
.panel-btn:hover { color: var(--nr-text-primary, #e2e8f0); }

.panel-body { display: flex; flex-direction: column; min-height: 0; }
.panel-task {
  padding: 6px 10px 2px;
  font-size: 11px;
  color: var(--nr-text-tertiary, #94a3b8);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
</style>
