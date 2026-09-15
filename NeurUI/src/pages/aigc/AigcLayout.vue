<script setup lang="ts">
/**
 * AIGC 二级页布局壳（2026-09-14 R1）：页头 + 子路由出口。
 * 五个生成页（文本/图片/音频/视频/创作专区）挂在「模型与工具」菜单下。
 */
import GlassPanel from '@/components/GlassPanel.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <div class="aigc-wrap">
    <GlassPanel class="aigc-header">
      <h2 class="aigc-page-title">{{ t('aigc.title') }}</h2>
    </GlassPanel>
    <router-view :key="$route.path" />
  </div>
</template>

<style>
/* AIGC 五页共享布局类（页级 scoped 只留个性样式） */
.aigc-wrap {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.aigc-header {
  padding: 16px 24px;
}

.aigc-page-title {
  font-family: var(--nr-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--nr-text-primary);
  margin: 0;
}

.aigc-gen-layout {
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 20px;
  align-items: start;
}

.aigc-input-panel {
  position: sticky;
  top: 0;
}

.aigc-result-panel {
  min-height: 300px;
}

.aigc-text-result {
  font-size: 14px;
  line-height: 1.7;
  color: var(--nr-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.aigc-text-result pre {
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}

.aigc-text-result code {
  font-family: var(--nr-font-mono);
  font-size: 13px;
}

.aigc-image-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.aigc-gallery-item {
  aspect-ratio: 1;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
}

.aigc-gallery-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.aigc-gallery-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.aigc-audio-player audio {
  width: 100%;
}

.aigc-ref-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.aigc-ref-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: rgba(125, 125, 125, 0.15);
}

.aigc-ref-chip-x {
  border: none;
  background: transparent;
  cursor: pointer;
  color: inherit;
  font-size: 11px;
  padding: 0;
}

.aigc-download {
  font-size: 13px;
  color: var(--nr-accent, #4096ff);
}

/* 2026-09-15 模型自适应推导展示（图/视频页选模型后只读协议/服务商徽标） */
.aigc-derived-hint {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--nr-text-secondary, rgba(255, 255, 255, 0.65));
}

@media (max-width: 900px) {
  .aigc-gen-layout {
    grid-template-columns: 1fr;
  }
}
</style>
