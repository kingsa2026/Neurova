<template>
  <div class="nr-dock-pdf">
    <div class="nr-dock-pdf-bar">
      <span class="nr-dock-pdf-title">{{ tab.title }}</span>
      <button class="nr-dock-pdf-btn" :title="t('dock.download')" @click="download">
        <UiIcon name="download" :size="13" />
      </button>
    </div>
    <p v-if="error" class="nr-dock-pdf-note">{{ t('chat.artifactUnavailable') }}</p>
    <embed v-else-if="src" :src="src" type="application/pdf" class="nr-dock-pdf-viewer" :title="tab.title" />
    <p v-else class="nr-dock-pdf-note">{{ t('chat.artifactUnavailable') }}</p>
  </div>
</template>

<script setup lang="ts">
/**
 * dock PDF 预览：浏览器原生查看器（<embed>）+ 下载兜底。
 *
 * 选原生而不引 pdf.js：零新依赖、零打包体积，Chrome/Edge 内置查看器即可翻页缩放。
 * 代价如实写在下载兜底上——Firefox/Linux 无内置查看器时 <embed> 会变成下载，
 * 所以下载按钮不是可选项而是这条取舍的补偿。
 *
 * 所有权口径同图片面板（台账 #11/#12）：只释放面板自建的 object URL；
 * 服务端直链经 withFileToken 追加凭证（资源标签带不了 Authorization 头）。
 */
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { artifactContentObjectUrl, fileContentObjectUrl } from '@/utils/artifacts'
import { withFileToken } from '@/utils/genFiles'
import UiIcon from '@/components/UiIcon.vue'
import type { DockTab } from '@/stores/rightDock'

const props = defineProps<{ tab: DockTab }>()
const { t } = useI18n()

const error = ref('')
const src = ref('')
let ownedUrl = ''

function releaseSrc(): void {
  if (ownedUrl) {
    URL.revokeObjectURL(ownedUrl)
    ownedUrl = ''
  }
  src.value = ''
}

async function loadSrc(): Promise<void> {
  releaseSrc()
  error.value = ''
  try {
    if (props.tab.data.url) {
      const url = withFileToken(props.tab.data.url)
      src.value = props.tab.data.createdBy === 'panel' ? (ownedUrl = url) : url
    } else if (props.tab.data.artifactId) {
      src.value = ownedUrl = await artifactContentObjectUrl(props.tab.data.artifactId)
    } else if (props.tab.data.fileId) {
      src.value = ownedUrl = await fileContentObjectUrl(props.tab.data.fileId)
    }
  } catch {
    error.value = 'load'
  }
}

async function download(): Promise<void> {
  if (!src.value) {
    error.value = 'empty'
    return
  }
  try {
    const res = await fetch(src.value)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = props.tab.title || 'document.pdf'
    a.click()
    URL.revokeObjectURL(a.href)
  } catch {
    // 与图片面板的静默 catch 不同：下载失败必须可见，否则用户以为文件不存在
    error.value = 'download'
  }
}

watch(
  () => [props.tab.data.url, props.tab.data.artifactId, props.tab.data.fileId],
  loadSrc,
  { immediate: true },
)

onBeforeUnmount(releaseSrc)
</script>

<style scoped>
.nr-dock-pdf {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.nr-dock-pdf-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex: 0 0 auto;
}
.nr-dock-pdf-title {
  flex: 1 1 auto;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-dock-pdf-btn {
  display: inline-flex;
  align-items: center;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  opacity: 0.72;
}
.nr-dock-pdf-btn:hover {
  opacity: 1;
}
.nr-dock-pdf-viewer {
  flex: 1 1 auto;
  width: 100%;
  min-height: 0;
  border: none;
  background: #1f1f1f;
}
.nr-dock-pdf-note {
  padding: 18px 12px;
  font-size: 12px;
  opacity: 0.7;
  text-align: center;
}
</style>
