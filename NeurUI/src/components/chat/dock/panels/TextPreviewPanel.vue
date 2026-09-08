<template>
  <div class="nr-dock-text">
    <div class="nr-dock-text-bar">
      <span class="nr-dock-text-lang">{{ tab.data.language || tab.title }}</span>
      <button class="nr-dock-text-btn" :title="t('chat.copy')" @click="copy"><UiIcon name="copy" :size="13" /></button>
    </div>
    <div v-if="loading" class="nr-dock-loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="nr-dock-error">{{ error }}</div>
    <pre v-else class="nr-dock-text-pre"><code v-html="highlighted" /></pre>
  </div>
</template>

<script setup lang="ts">
/**
 * dock 纯文本/代码预览：hljs 高亮（未注册语言退纯转义）+ 复制。
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import hljs from 'highlight.js/lib/core'
import { fetchArtifactText } from '@/utils/artifacts'
import UiIcon from '@/components/UiIcon.vue'
import { escapeHtml } from '@/utils/security'
import type { DockTab } from '@/stores/rightDock'

const props = defineProps<{ tab: DockTab }>()
const { t } = useI18n()

const fetchedContent = ref('')
const loading = ref(false)
const error = ref('')

const source = computed(() => props.tab.data.content ?? fetchedContent.value)

const highlighted = computed(() => {
  const text = source.value
  const lang = (props.tab.data.language || '').toLowerCase()
  if (lang && hljs.getLanguage(lang)) {
    try {
      return hljs.highlight(text, { language: lang }).value
    } catch {
      /* 退纯转义 */
    }
  }
  return escapeHtml(text)
})

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(source.value)
  } catch {
    /* 剪贴板受限静默 */
  }
}

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

watch(
  () => [props.tab.id, props.tab.data.artifactId, props.tab.data.content],
  () => {
    if (!props.tab.data.content && props.tab.data.artifactId) void loadRemote()
    else if (!props.tab.data.content && !props.tab.data.artifactId) {
      // 仅 path 的 tab（历史会话/后端重启后）：无注册 id 拉不到内容，
      // 空白体是误导——明示不可用原因
      error.value = t('chat.artifactUnavailable')
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.nr-dock-text {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.nr-dock-text-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
}
.nr-dock-text-lang {
  flex: 1;
  font-size: 11px;
  color: var(--nr-text-secondary, #8b8fa3);
  font-family: 'JetBrains Mono', Consolas, monospace;
}
.nr-dock-text-btn {
  flex: none;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--nr-text-secondary, #8b8fa3);
  cursor: pointer;
}
.nr-dock-text-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}
.nr-dock-text-pre {
  flex: 1;
  min-height: 0;
  overflow: auto;
  margin: 0;
  padding: 12px 14px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--nr-text-primary, #e8eaf2);
  font-family: 'JetBrains Mono', Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-word;
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
