<script setup lang="ts">
/**
 * AIGC 生成记录列表（2026-09-14 R1 拆分，自 AIGCPage「历史」面板抽出）。
 *
 * 消费 GET /generation/tasks：kind 过滤、状态徽标、产物下载、错误原文、
 * 未决任务自动刷新（全部终态自停）。原面板挂在 Tab 上却无入口 tab-pane
 * （批次2 遗留缺陷），拆分后作为四生成页共享侧栏，入口问题一并消除。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { listGenerationTasks, type GenerationTask } from '@/api/modules/generation'
import { withFileToken } from '@/utils/genFiles'
import GlassButton from '@/components/GlassButton.vue'
import GlassPanel from '@/components/GlassPanel.vue'

const props = defineProps<{
  /** 默认过滤的产物类型（当前页 kind）；空 = 初始展示全部 */
  kind?: '' | 'image' | 'video' | 'audio'
}>()

const { t } = useI18n()

const tasks = ref<GenerationTask[]>([])
const kindFilter = ref<string>(props.kind ?? '')
let pollTimer: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const res: any = await listGenerationTasks(kindFilter.value ? ({ kind: kindFilter.value } as any) : undefined)
    tasks.value = res?.data?.tasks ?? res?.tasks ?? []
  } catch {
    /* 保留已渲染列表，错误不打断浏览 */
  }
  ensurePolling()
}

function ensurePolling() {
  const pending = tasks.value.some(
    (task) => task.status === 'submitted' || task.status === 'running')
  if (pending && !pollTimer) {
    pollTimer = setInterval(() => { void load() }, 5000)
  } else if (!pending && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function setKind(k: string) {
  kindFilter.value = k
  void load()
}

function statusText(status: string): string {
  const keyMap: Record<string, string> = {
    submitted: 'aigc.stSubmitted',
    running: 'aigc.stRunning',
    succeeded: 'aigc.stSucceeded',
    failed: 'aigc.stFailed',
  }
  return keyMap[status] ? t(keyMap[status]) : status
}

function statusColor(status: string): string {
  const colorMap: Record<string, string> = {
    submitted: 'default', running: 'processing', succeeded: 'success', failed: 'error',
  }
  return colorMap[status] ?? 'default'
}

function taskTime(ts: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString()
}

onMounted(load)
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })

defineExpose({ load, tasks, kindFilter, setKind })
</script>

<template>
  <GlassPanel class="aigc-history" variant="subtle">
    <div class="aigc-history-toolbar">
      <span class="aigc-history-title">{{ t('aigc.history') }}</span>
      <a-radio-group :value="kindFilter" size="small" @change="(e: any) => setKind(e.target.value)">
        <a-radio-button value="">{{ t('aigc.all') }}</a-radio-button>
        <a-radio-button value="image">{{ t('aigc.image') }}</a-radio-button>
        <a-radio-button value="video">{{ t('aigc.video') }}</a-radio-button>
        <a-radio-button value="audio">{{ t('aigc.audio') }}</a-radio-button>
      </a-radio-group>
      <GlassButton size="sm" @click="load">{{ t('common.refresh') }}</GlassButton>
    </div>
    <div v-if="tasks.length" class="aigc-history-list">
      <div v-for="task in tasks" :key="task.task_id" class="aigc-history-item">
        <div class="aigc-history-thumb">
          <img v-if="task.kind === 'image' && task.url" :src="withFileToken(task.url)" :alt="task.prompt" />
          <span v-else class="aigc-history-kind">{{ task.kind }}</span>
        </div>
        <div class="aigc-history-info">
          <div class="aigc-history-prompt">{{ task.prompt || '—' }}</div>
          <div class="aigc-history-meta">
            <a-tag :color="statusColor(task.status)">{{ statusText(task.status) }}</a-tag>
            <!-- C3：产物已被保留清理删除（账本行保留），诚实标注过期 -->
            <a-tag v-if="task.file_missing" color="default">{{ t('aigc.expired') }}</a-tag>
            <a-tag v-if="task.source && task.source !== 'rest'" color="blue">{{ task.source }}</a-tag>
            <a-tag v-if="task.ignored_params" color="orange" :title="task.ignored_params">
              {{ t('aigc.ignoredTag', { params: task.ignored_params }) }}
            </a-tag>
            <span v-if="task.model">{{ task.model }}</span>
            <span>{{ taskTime(task.submitted_at) }}</span>
          </div>
          <div v-if="task.error" class="aigc-history-error">{{ task.error }}</div>
        </div>
        <div class="aigc-history-actions">
          <a v-if="task.url" :href="withFileToken(task.url)" :download="task.url.split('/').pop()" class="aigc-history-download">
            {{ t('aigc.download') }}
          </a>
        </div>
      </div>
    </div>
    <a-empty v-else :description="t('aigc.noHistory')" />
  </GlassPanel>
</template>

<style scoped>
.aigc-history {
  padding: 16px 20px;
  margin-top: 16px;
}

.aigc-history-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.aigc-history-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
  margin-right: auto;
}

.aigc-history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.aigc-history-item {
  display: grid;
  grid-template-columns: 64px 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--nr-bg-elevated, rgba(255, 255, 255, 0.04));
}

.aigc-history-thumb img {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: 8px;
}

.aigc-history-kind {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  text-transform: uppercase;
  color: var(--nr-text-secondary);
  background: rgba(125, 125, 125, 0.15);
}

.aigc-history-prompt {
  font-size: 13px;
  color: var(--nr-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aigc-history-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--nr-text-tertiary, var(--nr-text-secondary));
}

.aigc-history-error {
  margin-top: 4px;
  font-size: 12px;
  color: var(--nr-danger, #ff4d4f);
}

.aigc-history-download {
  font-size: 13px;
  color: var(--nr-accent, #4096ff);
}
</style>
