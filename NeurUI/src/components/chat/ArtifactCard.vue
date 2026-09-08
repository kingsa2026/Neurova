<template>
  <div class="nr-artifact-card" :class="{ 'nr-artifact-card--collapsed': !open }">
    <button class="nr-artifact-head" :title="open ? t('ui.minimize') : t('ui.expand')" @click="open = !open">
      <UiIcon name="chevronLeft" :size="13" class="nr-artifact-chevron" :class="{ 'nr-artifact-chevron--open': open }" />
      <UiIcon name="wrench" :size="13" />
      <span class="nr-artifact-title">{{ t('chat.artifactCount', { n: artifacts.length }) }}</span>
      <span v-if="totalSize" class="nr-artifact-total">{{ totalSize }}</span>
    </button>
    <div v-if="open" class="nr-artifact-list">
      <div v-for="item in artifacts" :key="artifactKey(item)" class="nr-artifact-row">
        <UiIcon :name="artifactUiIcon(item.kind)" :size="14" class="nr-artifact-row-icon" />
        <div class="nr-artifact-row-main">
          <span class="nr-artifact-row-name" :title="item.path || item.name">{{ item.name }}</span>
          <span v-if="dirOf(item)" class="nr-artifact-row-dir">{{ dirOf(item) }}</span>
        </div>
        <span class="nr-artifact-row-size">{{ sizeText(item) }}</span>
        <div class="nr-artifact-row-actions">
          <button class="nr-artifact-btn" :title="t('chat.artifactReviewTip')" @click="$emit('review', item)">
            {{ t('chat.artifactReview') }}
          </button>
          <button class="nr-artifact-btn nr-artifact-btn--primary" :title="t('chat.artifactOpenTip')" @click="$emit('open', item)">
            {{ t('chat.artifactOpen') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 回答结尾产出物卡片（2026-09-08，QwenPaw「已更改文件」形态对齐）。
 *
 * 每轮回答结尾展示本轮真实产出（SSE artifact 事件主通道 + tool_result
 * 兜底解析，读形态已剔除）。可收纳展开；每行「审验」= dock 源码审读
 * （text 强制源形态），「打开」= dock 渲染预览。
 * 数据在流式中增量到达：收集侧只增不减，组件本身无状态副作用。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import UiIcon from '@/components/UiIcon.vue'
import { artifactUiIcon, type MessageArtifact } from '@/utils/artifacts'

// 注意：Boolean 类型 prop 若无默认值，缺省时会被 Vue 运行时 cast 成 false
// （而非 undefined），`props.defaultOpen ?? true` 会恒得 false —— 必须用
// withDefaults 声明默认值来禁用该 cast。
const props = withDefaults(
  defineProps<{
    artifacts: MessageArtifact[]
    /** 默认展开态（默认开，与参考形态一致） */
    defaultOpen?: boolean
  }>(),
  { defaultOpen: true },
)

defineEmits<{
  review: [item: MessageArtifact]
  open: [item: MessageArtifact]
}>()

const { t } = useI18n()
const open = ref(props.defaultOpen ?? true)

function artifactKey(item: MessageArtifact): string {
  return item.name || item.path || item.artifactId || ''
}

function dirOf(item: MessageArtifact): string {
  if (!item.path) return ''
  const norm = item.path.replace(/\\/g, '/')
  const parts = norm.split('/')
  parts.pop()
  return parts.join('/')
}

function sizeText(item: MessageArtifact): string {
  const n = item.size
  if (!n || n <= 0) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

const totalSize = computed(() => {
  const sum = props.artifacts.reduce((acc, a) => acc + (a.size || 0), 0)
  if (sum <= 0) return ''
  if (sum < 1024) return `${sum} B`
  if (sum < 1024 * 1024) return `${(sum / 1024).toFixed(1)} KB`
  return `${(sum / 1024 / 1024).toFixed(1)} MB`
})
</script>

<style scoped>
.nr-artifact-card {
  margin-top: 8px;
  border-radius: 10px;
  border: 1px solid var(--nr-border, rgba(129, 140, 248, 0.22));
  background: var(--nr-bg-glass, rgba(20, 24, 44, 0.55));
  backdrop-filter: blur(8px);
  overflow: hidden;
  font-size: 12px;
}

.nr-artifact-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  background: transparent;
  color: var(--nr-text-secondary, rgba(226, 232, 240, 0.75));
  cursor: pointer;
  text-align: left;
}

.nr-artifact-head:hover {
  background: rgba(129, 140, 248, 0.08);
}

.nr-artifact-chevron {
  transition: transform 0.15s ease;
}

.nr-artifact-chevron--open {
  transform: rotate(-90deg);
}

.nr-artifact-title {
  font-weight: 600;
  color: var(--nr-text-primary, rgba(241, 245, 249, 0.92));
}

.nr-artifact-total {
  color: var(--nr-text-tertiary, rgba(148, 163, 184, 0.6));
}

.nr-artifact-list {
  border-top: 1px solid var(--nr-border, rgba(129, 140, 248, 0.14));
}

.nr-artifact-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
}

.nr-artifact-row + .nr-artifact-row {
  border-top: 1px solid rgba(129, 140, 248, 0.08);
}

.nr-artifact-row-icon {
  color: var(--nr-accent, #818cf8);
}

.nr-artifact-row-main {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.nr-artifact-row-name {
  font-weight: 600;
  color: var(--nr-text-primary, rgba(241, 245, 249, 0.92));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nr-artifact-row-dir {
  color: var(--nr-text-tertiary, rgba(148, 163, 184, 0.55));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
  text-align: left;
  max-width: 40%;
}

.nr-artifact-row-size {
  color: var(--nr-text-tertiary, rgba(148, 163, 184, 0.6));
  flex: none;
}

.nr-artifact-row-actions {
  display: flex;
  gap: 6px;
  flex: none;
}

.nr-artifact-btn {
  padding: 3px 10px;
  border-radius: 7px;
  border: 1px solid rgba(129, 140, 248, 0.3);
  background: transparent;
  color: var(--nr-text-secondary, rgba(226, 232, 240, 0.8));
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
}

.nr-artifact-btn:hover {
  background: rgba(129, 140, 248, 0.14);
  border-color: rgba(129, 140, 248, 0.55);
}

.nr-artifact-btn--primary {
  background: rgba(99, 102, 241, 0.22);
  border-color: rgba(129, 140, 248, 0.5);
  color: #c7d2fe;
}
</style>
