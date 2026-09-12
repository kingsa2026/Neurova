<template>
  <div class="nr-dock-image" @dblclick="scale = 1">
    <div class="nr-dock-image-bar">
      <span class="nr-dock-image-title">{{ tab.title }}</span>
      <span class="nr-dock-image-zoom">{{ Math.round(scale * 100) }}%</span>
      <button class="nr-dock-image-btn" :title="t('dock.download')" @click="download"><UiIcon name="download" :size="13" /></button>
    </div>
    <div class="nr-dock-image-viewport" @wheel.prevent="onWheel">
      <div v-if="error" class="nr-dock-error">{{ t('chat.artifactUnavailable') }}</div>
      <img
        v-else-if="src"
        :src="src"
        :alt="tab.title"
        :style="{ transform: `scale(${scale})` }"
        @load="error = ''"
        @error="error = 'load'"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * dock 图片预览：滚轮缩放 + 双击复位 + 下载。吸收原消息 Lightbox 职责
 * （lightbox 模态删除，统一入 dock）。
 */
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { artifactContentObjectUrl, fileContentObjectUrl } from '@/utils/artifacts'
import UiIcon from '@/components/UiIcon.vue'
import type { DockTab } from '@/stores/rightDock'

const props = defineProps<{ tab: DockTab }>()
const { t } = useI18n()

const scale = ref(1)
const error = ref('')
const src = ref('')

/**
 * 面板负责释放的 object URL（台账 #11 根修，2026-09-11）：
 * - 自建（artifactId/fileId 经 fetch 转 object URL）；
 * - data.url 且 data.createdBy === 'panel'（调用方为面板专属创建）。
 * 外来 URL（服务端直链/消息自有 blob）一律不 revoke——消息 blob 由
 * store.revokeMessageBlobUrls 统一释放，面板误撤会使消息缩略图失效。
 */
let ownedUrl = ''

function releaseSrc(): void {
  if (ownedUrl) {
    URL.revokeObjectURL(ownedUrl)
    ownedUrl = ''
  }
  src.value = ''
}

/** 内容端点有 JWT 鉴权，<img> 直链必 401 → 经 Bearer 取 blob 转 object URL */
async function loadSrc(): Promise<void> {
  releaseSrc()
  error.value = ''
  try {
    if (props.tab.data.url) {
      src.value = props.tab.data.url
      if (props.tab.data.createdBy === 'panel') ownedUrl = src.value
    } else if (props.tab.data.artifactId) {
      src.value = ownedUrl = await artifactContentObjectUrl(props.tab.data.artifactId)
    } else if (props.tab.data.fileId) {
      src.value = ownedUrl = await fileContentObjectUrl(props.tab.data.fileId)
    } else if (props.tab.data.content && props.tab.data.language === 'svg') {
      // 台账 N5（2026-09-11）：openCodeBlockTab 的 svg 代码块走 kind:'image'
      // 但只带 content（无 url/artifactId/fileId）——旧实现三个分支都不命中，
      // 视口恒空白。面板自建 object URL 渲染，所有权归面板统一释放；
      // 经 <img> 加载的 SVG 内脚本不执行。
      const blob = new Blob([props.tab.data.content], { type: 'image/svg+xml' })
      src.value = ownedUrl = URL.createObjectURL(blob)
    }
  } catch {
    error.value = 'load'
  }
}

watch(
  () => [props.tab.data.url, props.tab.data.artifactId, props.tab.data.fileId, props.tab.data.content],
  loadSrc,
  { immediate: true },
)

onBeforeUnmount(releaseSrc)

function onWheel(e: WheelEvent): void {
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  scale.value = Math.min(6, Math.max(0.2, scale.value + delta))
}

async function download(): Promise<void> {
  if (!src.value) return
  try {
    const res = await fetch(src.value)
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = props.tab.title || 'artifact'
    a.click()
    URL.revokeObjectURL(a.href)
  } catch {
    /* 下载失败静默（同源受限时 img 展示仍可用） */
  }
}

watch(() => props.tab.id, () => {
  scale.value = 1
  error.value = ''
})
</script>

<style scoped>
.nr-dock-image {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.nr-dock-image-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
}
.nr-dock-image-title {
  flex: 1;
  font-size: 12px;
  color: var(--nr-text-primary, #e8eaf2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-dock-image-zoom {
  font-size: 11px;
  color: var(--nr-text-secondary, #8b8fa3);
}
.nr-dock-image-btn {
  flex: none;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--nr-text-secondary, #8b8fa3);
  cursor: pointer;
}
.nr-dock-image-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}
.nr-dock-image-viewport {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--nr-bg-secondary, rgba(0, 0, 0, 0.25));
}
.nr-dock-image-viewport img {
  max-width: 100%;
  transition: transform 0.12s ease;
}
.nr-dock-error {
  padding: 20px;
  color: #e5484d;
  font-size: 13px;
}
</style>
