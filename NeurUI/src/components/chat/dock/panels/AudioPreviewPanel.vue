<template>
  <div class="nr-dock-audio">
    <div class="nr-dock-audio-card">
      <div class="nr-dock-audio-icon"><UiIcon name="audio" :size="34" /></div>
      <div class="nr-dock-audio-name">{{ tab.title }}</div>
      <audio v-if="src" :src="src" controls class="nr-dock-audio-player" />
      <div v-else class="nr-dock-error">{{ t('chat.artifactUnavailable') }}</div>
      <a v-if="src" class="nr-dock-audio-dl" :href="src" :download="tab.title">{{ t('dock.download') }}</a>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * dock 音频预览（TTS 工具产物 / 注册为 artifact 的音频文件）。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { artifactContentUrl } from '@/utils/artifacts'
import UiIcon from '@/components/UiIcon.vue'
import type { DockTab } from '@/stores/rightDock'

const props = defineProps<{ tab: DockTab }>()
const { t } = useI18n()

const src = computed(() => {
  if (props.tab.data.url) return props.tab.data.url
  if (props.tab.data.artifactId) return artifactContentUrl(props.tab.data.artifactId)
  return ''
})
</script>

<style scoped>
.nr-dock-audio {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.nr-dock-audio-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: 320px;
  padding: 24px;
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  border-radius: 12px;
  background: var(--nr-bg-secondary, rgba(255, 255, 255, 0.04));
}
.nr-dock-audio-icon {
  font-size: 36px;
}
.nr-dock-audio-name {
  font-size: 13px;
  color: var(--nr-text-primary, #e8eaf2);
  text-align: center;
  word-break: break-all;
}
.nr-dock-audio-player {
  width: 100%;
}
.nr-dock-audio-dl {
  font-size: 12px;
  color: var(--nr-primary, #6366f1);
  text-decoration: none;
}
.nr-dock-audio-dl:hover {
  text-decoration: underline;
}
.nr-dock-error {
  padding: 12px;
  color: #e5484d;
  font-size: 13px;
}
</style>
