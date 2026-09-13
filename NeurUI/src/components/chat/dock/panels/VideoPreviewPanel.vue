<template>
  <div class="nr-dock-video">
    <div class="nr-dock-video-card">
      <div class="nr-dock-video-name">{{ tab.title }}</div>
      <video v-if="src" :src="src" controls class="nr-dock-video-player" />
      <div v-else class="nr-dock-error">{{ t('chat.artifactUnavailable') }}</div>
      <a v-if="src" class="nr-dock-video-dl" :href="src" :download="tab.title">{{ t('dock.download') }}</a>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * dock 视频预览（批次4：AIGC 视频/成片产物）。
 * 与 AudioPreviewPanel 同模式：产物端点带 JWT 鉴权 → 直链或 Bearer 转 object URL；
 * 仅释放面板自建的 URL，外来直链不 revoke。
 */
import { ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { artifactContentObjectUrl } from '@/utils/artifacts'
import type { DockTab } from '@/stores/rightDock'

const props = defineProps<{ tab: DockTab }>()
const { t } = useI18n()

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
  try {
    if (props.tab.data.url) {
      src.value = props.tab.data.url
      if (props.tab.data.createdBy === 'panel') ownedUrl = src.value
    } else if (props.tab.data.artifactId) {
      src.value = ownedUrl = await artifactContentObjectUrl(props.tab.data.artifactId)
    }
  } catch {
    src.value = ''
  }
}

watch(() => [props.tab.data.url, props.tab.data.artifactId], loadSrc, { immediate: true })

onBeforeUnmount(releaseSrc)
</script>

<style scoped>
.nr-dock-video {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.nr-dock-video-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: 640px;
  padding: 16px;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  border-radius: 12px;
  background: var(--nr-bg-secondary, rgba(0, 0, 0, 0.25));
}
.nr-dock-video-name {
  font-size: 13px;
  color: var(--nr-text-primary, #e8eaf2);
  text-align: center;
  word-break: break-all;
}
.nr-dock-video-player {
  width: 100%;
  max-height: 60vh;
  border-radius: 8px;
}
.nr-dock-video-dl {
  font-size: 12px;
  color: var(--nr-primary, #6366f1);
  text-decoration: none;
}
.nr-dock-video-dl:hover {
  text-decoration: underline;
}
.nr-dock-error {
  padding: 12px;
  color: #e5484d;
  font-size: 13px;
}
</style>
