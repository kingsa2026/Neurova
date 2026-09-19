<template>
  <div
    ref="bodyRef"
    class="nr-msg-content"
    :class="{ 'nr-msg-content--bare': bare }"
    v-html="renderedHtml"
    @click="handleClick"
  />
</template>

<script setup lang="ts">
/**
 * MessageContent.vue — 消息富文本正文的共享渲染单元（ChatPage / 协作房间同源）。
 *
 * 单一职责：把纯文本经 renderMarkdown（marked GFM + hljs 高亮 + KaTeX +
 * mermaid 占位 + DOMPurify 净化）渲染为 HTML，并在 DOM 插入后水合 mermaid。
 * 复制按钮就地处理；代码预览 / 图片放大属宿主容器的能力（dock / lightbox），
 * 以 emit 交回父页面，组件本身不耦合右侧面板。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { renderMarkdown } from '@/utils/markdown'
import { useMermaidRenderer } from '@/composables/useMermaidRenderer'
import '@/styles/messageRender.css'

const props = withDefaults(defineProps<{ content: string; bare?: boolean }>(), { bare: false })

const emit = defineEmits<{
  (e: 'openCode', lang: string, code: string): void
  (e: 'openImage', src: string, alt: string): void
}>()

const { t } = useI18n()
const appStore = useAppStore()
const bodyRef = ref<HTMLElement | null>(null)

const { renderIn, scheduleRender, dispose } = useMermaidRenderer(() => !appStore.isDark)
const renderedHtml = computed(() => renderMarkdown(props.content, t('common.copy')))

const copyResetTimers: number[] = []

/** 事件委托：复制（就地）→ 代码预览（emit）→ 内联图片放大（emit）。 */
function handleClick(e: MouseEvent): void {
  const target = e.target as HTMLElement

  const copyBtn = target.closest('.nr-code-copy-btn') as HTMLButtonElement | null
  if (copyBtn) {
    const codeEl = copyBtn.closest('.nr-code-wrap')?.querySelector('code')
    const code = codeEl ? codeEl.textContent || '' : ''
    navigator.clipboard.writeText(code).then(() => {
      copyBtn.textContent = '✓'
    }).catch(() => {
      copyBtn.textContent = '✗'
    }).finally(() => {
      copyResetTimers.push(window.setTimeout(() => {
        copyBtn.textContent = t('common.copy')
      }, 1500))
    })
    return
  }

  const previewBtn = target.closest('.nr-code-preview-btn') as HTMLElement | null
  if (previewBtn) {
    const wrap = previewBtn.closest('.nr-code-wrap')
    const codeEl = wrap?.querySelector('code')
    const langEl = wrap?.querySelector('.nr-code-lang')
    const lang = (langEl?.textContent || '').trim().toLowerCase()
    if (codeEl) emit('openCode', lang === 'code' ? '' : lang, codeEl.textContent || '')
    return
  }

  if (target.tagName === 'IMG' && target.closest('.nr-inline-image')) {
    const img = target as HTMLImageElement
    emit('openImage', img.src, img.alt || 'image')
  }
}

async function hydrate(): Promise<void> {
  await nextTick()
  renderIn(bodyRef.value)
}

onMounted(() => void hydrate())
onUnmounted(() => {
  copyResetTimers.forEach((id) => window.clearTimeout(id))
  dispose()
})

// 流式期间内容逐块增长 → 防抖水合（scheduleRender 内部去抖）。
watch(() => props.content, () => {
  scheduleRender(bodyRef.value)
})
</script>
