<template>
  <div class="nr-dock-md">
    <div v-if="loading" class="nr-dock-loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="nr-dock-error">{{ error }}</div>
    <div v-else ref="bodyRef" class="nr-dock-md-body" v-html="renderedHtml" @click="onBodyClick" />
  </div>
</template>

<script setup lang="ts">
/**
 * dock markdown 预览面板：复用 renderMarkdown（hljs+KaTeX+mermaid 占位）
 * 全管线；DOM 插入后交给 useMermaidRenderer 渲染 mermaid。
 * 数据源优先级：tab.data.content（本地内容） > artifactId（fetch）。
 */
import { computed, ref, watch, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { renderMarkdown } from '@/utils/markdown'
import { useMermaidRenderer } from '@/composables/useMermaidRenderer'
import { fetchArtifactText } from '@/utils/artifacts'
import type { DockTab } from '@/stores/rightDock'

const props = defineProps<{ tab: DockTab }>()
const { t } = useI18n()
const appStore = useAppStore()

const bodyRef = ref<HTMLElement | null>(null)
const fetchedContent = ref('')
const loading = ref(false)
const error = ref('')

const { renderIn } = useMermaidRenderer(() => !appStore.isDark)

const source = computed(() => props.tab.data.content ?? fetchedContent.value)
const renderedHtml = computed(() => renderMarkdown(source.value, t('chat.copy')))

async function loadRemote(): Promise<void> {
  const id = props.tab.data.artifactId
  if (!id) return
  loading.value = true
  error.value = ''
  try {
    fetchedContent.value = await fetchArtifactText(id)
  } catch {
    error.value = t('chat.artifactUnavailable')
  } finally {
    loading.value = false
  }
}

async function renderMermaid(): Promise<void> {
  await nextTick()
  if (bodyRef.value) renderIn(bodyRef.value)
}

// 点击正文链接新窗打开（v-html 内 <a> 无 target）
function onBodyClick(e: MouseEvent): void {
  const a = (e.target as HTMLElement).closest('a')
  if (a) {
    e.preventDefault()
    window.open(a.href, '_blank', 'noopener')
  }
}

watch(() => [props.tab.id, props.tab.data.artifactId, props.tab.data.content], () => {
  if (!props.tab.data.content && props.tab.data.artifactId) void loadRemote()
  void renderMermaid()
})

onMounted(async () => {
  if (!props.tab.data.content && props.tab.data.artifactId) await loadRemote()
  await renderMermaid()
})
</script>

<style scoped>
.nr-dock-md {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 16px;
}
.nr-dock-md-body {
  font-size: 14px;
  line-height: 1.65;
  color: var(--nr-text-primary, #e8eaf2);
  word-break: break-word;
}
.nr-dock-md-body :deep(h1),
.nr-dock-md-body :deep(h2),
.nr-dock-md-body :deep(h3) {
  margin: 14px 0 8px;
  line-height: 1.3;
}
.nr-dock-md-body :deep(pre) {
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.05));
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  border-radius: 8px;
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 12.5px;
}
.nr-dock-md-body :deep(code) {
  font-family: 'JetBrains Mono', Consolas, monospace;
}
.nr-dock-md-body :deep(img) {
  max-width: 100%;
  border-radius: 8px;
}
.nr-dock-md-body :deep(blockquote) {
  border-left: 3px solid var(--nr-border, rgba(255, 255, 255, 0.15));
  margin: 8px 0;
  padding: 2px 12px;
  color: var(--nr-text-secondary, #8b8fa3);
}
.nr-dock-md-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
.nr-dock-md-body :deep(th),
.nr-dock-md-body :deep(td) {
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.12));
  padding: 4px 10px;
  font-size: 13px;
}
.nr-dock-loading,
.nr-dock-error {
  padding: 20px;
  text-align: center;
  color: var(--nr-text-secondary, #8b8fa3);
  font-size: 13px;
}
.nr-dock-error {
  color: #e5484d;
}
</style>
