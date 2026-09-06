<template>
  <div v-if="open" class="nr-xsearch-overlay" @click.self="close">
    <div class="nr-xsearch-panel">
      <div class="nr-xsearch-head">
        <input
          ref="inputRef"
          v-model="query"
          class="nr-xsearch-input"
          :placeholder="t('chat.crossSearchPlaceholder')"
          @keydown.esc.prevent="close"
          @keydown.enter.prevent="search()"
        />
        <button class="nr-xsearch-close" @click="close">✕</button>
      </div>
      <div class="nr-xsearch-body">
        <div v-if="searching" class="nr-xsearch-status">{{ t('chat.crossSearchSearching', { n: scannedCount, total: sessions.length }) }}</div>
        <div v-else-if="query.trim() && results.length === 0" class="nr-xsearch-status">{{ t('chat.crossSearchNoHit') }}</div>
        <div
          v-for="(hit, i) in results"
          :key="`${hit.sessionId}:${hit.index}:${i}`"
          class="nr-xsearch-hit"
          @click="$emit('jump', hit.sessionId, hit.snippet)"
        >
          <div class="nr-xsearch-hit-session">{{ hit.sessionTitle }}</div>
          <div class="nr-xsearch-hit-snippet" v-html="hit.highlighted"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 跨会话全文搜索面板（QwenPaw ChatSearchPanel 对齐）。
 *
 * 行为：输入关键词 → 串行遍历会话历史（防内存爆，逐会话请求、可取消）→
 * 命中列表（会话名 + 高亮片段）→ 点击跳转会话。竞态防护：搜索序号守卫，
 * 旧查询结果不覆盖新查询。
 */
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import { escapeHtml } from '@/utils/security'

interface SessionLike {
  id: string
  title?: string
}

interface CrossSearchHit {
  sessionId: string
  sessionTitle: string
  index: number
  snippet: string
  highlighted: string
}

const props = defineProps<{
  open: boolean
  sessions: SessionLike[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'jump', sessionId: string, keyword: string): void
}>()

const { t } = useI18n()

const query = ref('')
const results = ref<CrossSearchHit[]>([])
const searching = ref(false)
const scannedCount = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

let searchEpoch = 0

watch(
  () => props.open,
  (open) => {
    if (open) {
      results.value = []
      scannedCount.value = 0
      void nextTick(() => inputRef.value?.focus())
    } else {
      searchEpoch++ // 关闭即取消在途遍历
      searching.value = false
    }
  },
)

function close(): void {
  emit('close')
}

/** 高亮关键词（escape 后再包 mark，避免注入）。 */
function highlight(text: string, keyword: string): string {
  const safe = escapeHtml(text)
  if (!keyword) return safe
  const safeKw = escapeHtml(keyword)
  return safe.replace(new RegExp(`(${safeKw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>')
}

function snippetOf(content: string, keyword: string, radius = 60): string {
  const idx = content.toLowerCase().indexOf(keyword.toLowerCase())
  if (idx < 0) return content.slice(0, radius * 2)
  const start = Math.max(0, idx - radius)
  const end = Math.min(content.length, idx + keyword.length + radius)
  return `${start > 0 ? '…' : ''}${content.slice(start, end)}${end < content.length ? '…' : ''}`
}

async function search(): Promise<void> {
  const keyword = query.value.trim()
  if (!keyword) return
  const epoch = ++searchEpoch
  results.value = []
  searching.value = true
  scannedCount.value = 0

  const collected: CrossSearchHit[] = []
  for (const session of props.sessions) {
    if (epoch !== searchEpoch) return // 面板已关闭或新搜索启动
    try {
      const res: any = await api.get(`/console/chat/history?session_id=${session.id}`)
      const data = res?.data ?? res
      const messages: Array<Record<string, unknown>> = Array.isArray(data) ? data : (data?.messages ?? [])
      for (let i = 0; i < messages.length; i++) {
        const content = String(messages[i]?.content ?? '')
        if (content.toLowerCase().includes(keyword.toLowerCase())) {
          const snippet = snippetOf(content, keyword)
          collected.push({
            sessionId: session.id,
            sessionTitle: session.title || session.id,
            index: i,
            snippet,
            highlighted: highlight(snippet, keyword),
          })
          if (collected.length >= 50) break
        }
      }
    } catch {
      // 单会话拉取失败跳过（存档/无权限等），不中断全局搜索
    }
    scannedCount.value++
    if (collected.length >= 50) break
  }
  if (epoch !== searchEpoch) return
  results.value = collected
  searching.value = false
}
</script>

<style scoped>
.nr-xsearch-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 100;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 10vh;
}

.nr-xsearch-panel {
  width: min(560px, 92vw);
  max-height: 70vh;
  border-radius: 12px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-secondary, rgba(30, 32, 40, 0.98));
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.nr-xsearch-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--nr-glass-border);
}

.nr-xsearch-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--nr-text-primary);
  font-size: 14px;
}

.nr-xsearch-close {
  border: none;
  background: none;
  color: var(--nr-text-secondary);
  cursor: pointer;
  font-size: 14px;
}

.nr-xsearch-body {
  overflow-y: auto;
  padding: 6px;
}

.nr-xsearch-status {
  padding: 12px;
  text-align: center;
  font-size: 12px;
  color: var(--nr-text-tertiary);
}

.nr-xsearch-hit {
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
}

.nr-xsearch-hit:hover {
  background: rgba(74, 158, 255, 0.12);
}

.nr-xsearch-hit-session {
  font-size: 12px;
  font-weight: 600;
  color: var(--nr-text-secondary);
  margin-bottom: 2px;
}

.nr-xsearch-hit-snippet {
  font-size: 13px;
  color: var(--nr-text-primary);
  word-break: break-word;
}

.nr-xsearch-hit-snippet :deep(mark) {
  background: rgba(230, 162, 60, 0.4);
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}
</style>
