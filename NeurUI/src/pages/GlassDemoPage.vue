<template>
  <div class="gd-page">
    <section class="gd-slot">
      <p class="gd-label">{{ t('glassDemo.caseAPill') }}</p>
      <div class="gd-stage gd-stage--pill">
        <h2 class="gd-text">{{ t('glassDemo.fallbackText') }}</h2>
        <GlassSurface
          :width="360"
          :height="100"
          :border-radius="50"
          :background-opacity="0.1"
          :displace="0.5"
        />
      </div>
    </section>

    <section class="gd-slot">
      <p class="gd-label">{{ t('glassDemo.caseCLoginCard') }}</p>
      <div class="gd-stage gd-stage--card">
        <h2 class="gd-text">{{ t('glassDemo.fallbackText') }}</h2>
        <GlassSurface
          width="365px"
          height="508px"
          :border-radius="27"
          :background-opacity="0.12"
          :displace="0.5"
        />
      </div>
    </section>

    <section class="gd-slot">
      <p class="gd-label">{{ t('glassDemo.caseDPanelSkin') }}</p>
      <div class="gd-stage gd-stage--panel">
        <h2 class="gd-text">{{ t('glassDemo.liquidGlassText') }}</h2>
        <GlassPanel :radius="28" style="width: 360px">
          <div style="height: 200px"></div>
        </GlassPanel>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
// 临时诊断页：GlassSurface 官方 demo 复刻，单变量对照找登录页无折射的根因。
// A=官方胶囊基准；C=官方字面值+登录卡尺寸；D=GlassPanel 双皮肤折射对比。
// 参数为绝对像素语义，禁止按尺寸比例放大（放大位移量会把文字扯成彩虹拱形，见 D 实验记录）。
import { useI18n } from 'vue-i18n'
import GlassSurface from '@/components/GlassSurface.vue'
import GlassPanel from '@/components/GlassPanel.vue'

const { t } = useI18n()
</script>

<style scoped>
.gd-page {
  height: 100vh;
  overflow-y: auto;
  background-image: url('https://images.unsplash.com/photo-1500673587002-1d2548cfba1b?q=80&w=1740&auto=format&fit=crop');
  background-size: cover;
  background-position: center;
  background-attachment: fixed;
  display: flex;
  flex-direction: column;
  gap: 48px;
  padding: 48px 24px 96px;
}
.gd-slot { display: flex; flex-direction: column; gap: 12px; align-items: center; }
.gd-label {
  margin: 0;
  font: 600 13px/1.4 system-ui, sans-serif;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
  padding: 4px 12px;
  border-radius: 999px;
}
.gd-stage {
  position: relative;
  width: min(92vw, 960px);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 16px;
}
.gd-stage--pill { height: 180px; }
.gd-stage--card { height: 560px; }
.gd-stage--panel { height: 300px; }
.gd-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  font: 800 clamp(36px, 6vw, 72px)/1.1 system-ui, sans-serif;
  color: #fff;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
  pointer-events: none;
}
</style>
