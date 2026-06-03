<template>
  <div >
    <!-- === 宇宙星云层 === -->
    <!-- 核心亮斑 — 缓慢旋转 -->
    <div ></div>
    <!-- 蓝紫色星云团 1 -->
    <div ></div>
    <!-- 粉色星云团 2 -->
    <div ></div>
    <!-- 深蓝星云团 3 -->
    <div ></div>
    <!-- 银河尘带 — 横跨屏幕 -->
    <div ></div>
    <!-- 第二层尘带 — 反向移动 -->
    <div ></div>
    <!-- 微光粒子层 -->
    <div ></div>
    <!-- 第一层：大星星 3px，向下慢速 -->
    <div  :style="{ animationDuration: '120s' }">
      <div
        v-for="star in layer1"
        :key="'l1-' + star.id"
        :style="starStyle(star, 0)"
      ></div>
      <!-- 副本：位于容器上方 100vh 处，实现无缝循环 -->
      <div
        v-for="star in layer1"
        :key="'l1t-' + star.id"
        :style="starStyle(star, -100)"
      ></div>
    </div>
    <!-- 第二层：中等星星 2px，向上中速 -->
    <div  :style="{ animationDuration: '50s' }">
      <div
        v-for="star in layer2"
        :key="'l2-' + star.id"
        :style="starStyle(star, 0)"
      ></div>
      <!-- 副本：位于容器下方 100vh 处 -->
      <div
        v-for="star in layer2"
        :key="'l2t-' + star.id"
        :style="starStyle(star, 100)"
      ></div>
    </div>
    <!-- 第三层：小星星 1px，向上快速（2倍速） -->
    <div  :style="{ animationDuration: '30s' }">
      <div
        v-for="star in layer3"
        :key="'l3-' + star.id"
        :style="starStyle(star, 0)"
      ></div>
      <!-- 副本：位于容器下方 100vh 处 -->
      <div
        v-for="star in layer3"
        :key="'l3t-' + star.id"
        :style="starStyle(star, 100)"
      ></div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
interface Star {
  id: number
  x: number   // 0-100 %
  y: number   // 0-100 vh（相对于容器顶部）
  color: string
  size: number
  twinkleDur: number   // 闪烁周期（秒）
  twinkleDelay: number  // 闪烁负延迟（随机起始相位）
}
const PALETTE = [
  '#ffffff',
  '#e8e0ff',
  '#c8b8ff',
  '#b8a0f0',
  '#f0d0ff',
  '#ffe0c0',
  '#ffe8d0',
  '#d0d8ff',
  '#a0c8ff',
  '#ffc8d8',
]
function pick<T>(arr: T[]) { return arr[Math.floor(Math.random() * arr.length)] }
function makeStars(count: number, size: number): Star[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    x: Math.random() * 100,
    y: Math.random() * 100,
    color: pick(PALETTE),
    size,
    twinkleDur: 2 + Math.random() * 4,       // 2~6 秒
    twinkleDelay: -(Math.random() * 5),         // 负延迟 → 随机起始相位
  }))
}
const layer1 = ref<Star[]>([])
const layer2 = ref<Star[]>([])
const layer3 = ref<Star[]>([])
/**
 * 计算单颗星星的样式
 * @param yOffset 副本偏移量（vh）：-100 = 放在容器上方；100 = 放在容器下方
 */
function starStyle(star: Star, yOffset: number) {
  const s = star.size
  // 光晕：内层实色小光晕 + 外层扩散大光晕
  const glow = `0 0 ${s * 2}px ${star.color}, 0 0 ${s * 5}px ${hexAlpha(star.color, 0.25)}`
  return {
    left: `${star.x}%`,
    top: `${star.y + yOffset}vh`,
    width: `${s}px`,
    height: `${s}px`,
    background: star.color,
    borderRadius: '50%',
    boxShadow: glow,
    animationDuration: `${star.twinkleDur}s`,
    animationDelay: `${star.twinkleDelay}s`,
  } as Record<string, string>
}
function hexAlpha(hex: string, a: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${a})`
}
onMounted(() => {
  layer1.value = makeStars(20, 3)   // 第一层 20颗，3px
  layer2.value = makeStars(40, 2)   // 第二层 40颗，2px
  layer3.value = makeStars(80, 1)   // 第三层 80颗，1px
})
</script>
<style scoped>
/* ========== 宇宙星云 — 动态银河 ========== */
.nebula-core {
  position: absolute;
  top: 40%;
  left: 50%;
  width: 80vmax;
  height: 80vmax;
  transform: translate(-50%, -50%);
  background: radial-gradient(
    ellipse at center,
    rgba(100, 50, 180, 0.35) 0%,
    rgba(60, 30, 140, 0.20) 20%,
    rgba(40, 20, 100, 0.08) 45%,
    transparent 65%
  );
  border-radius: 50%;
  filter: blur(80px);
  animation: corePulse 12s ease-in-out infinite alternate;
  pointer-events: none;
}
.nebula-blob {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
}
.nebula-1 {
  top: -10%;
  right: -15%;
  width: 80vmax;
  height: 60vmax;
  background: radial-gradient(
    ellipse at 40% 60%,
    rgba(60, 40, 160, 0.40) 0%,
    rgba(100, 60, 200, 0.25) 25%,
    rgba(40, 20, 120, 0.10) 50%,
    transparent 75%
  );
  filter: blur(50px);
  animation: nebulaFloat1 20s ease-in-out infinite;
}
.nebula-2 {
  bottom: -15%;
  left: -10%;
  width: 70vmax;
  height: 70vmax;
  background: radial-gradient(
    ellipse at 55% 35%,
    rgba(180, 30, 100, 0.35) 0%,
    rgba(140, 25, 90, 0.20) 25%,
    rgba(80, 15, 60, 0.08) 50%,
    transparent 70%
  );
  filter: blur(55px);
  animation: nebulaFloat2 24s ease-in-out infinite;
}
.nebula-3 {
  top: 25%;
  left: 10%;
  width: 60vmax;
  height: 40vmax;
  background: radial-gradient(
    ellipse at 50% 50%,
    rgba(30, 80, 200, 0.30) 0%,
    rgba(20, 60, 160, 0.15) 30%,
    transparent 60%
  );
  filter: blur(45px);
  animation: nebulaFloat3 28s ease-in-out infinite alternate;
}
.nebula-dust {
  position: absolute;
  top: 25%;
  left: -30%;
  width: 160%;
  height: 50%;
  background: radial-gradient(
    ellipse at 60% 50%,
    rgba(80, 40, 160, 0.25) 0%,
    rgba(50, 25, 120, 0.10) 40%,
    transparent 70%
  );
  filter: blur(35px);
  transform: rotate(-12deg);
  animation: dustDrift 35s ease-in-out infinite alternate;
  pointer-events: none;
}
.nebula-dust-2 {
  top: 30%;
  left: -40%;
  width: 180%;
  height: 40%;
  background: radial-gradient(
    ellipse at 40% 60%,
    rgba(100, 70, 200, 0.15) 0%,
    rgba(60, 40, 150, 0.06) 40%,
    transparent 65%
  );
  filter: blur(40px);
  transform: rotate(6deg);
  animation: dustDrift 45s ease-in-out infinite alternate-reverse;
  pointer-events: none;
}
.nebula-particles {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(3px 3px at 20% 30%, rgba(200, 160, 255, 0.7), transparent),
    radial-gradient(4px 4px at 70% 55%, rgba(150, 120, 255, 0.6), transparent),
    radial-gradient(2px 2px at 45% 65%, rgba(220, 180, 255, 0.5), transparent),
    radial-gradient(3px 3px at 25% 20%, rgba(255, 200, 240, 0.6), transparent),
    radial-gradient(2px 2px at 85% 25%, rgba(200, 140, 255, 0.5), transparent),
    radial-gradient(4px 4px at 55% 40%, rgba(180, 150, 255, 0.5), transparent),
    radial-gradient(3px 3px at 15% 75%, rgba(160, 120, 255, 0.4), transparent),
    radial-gradient(2px 2px at 90% 70%, rgba(200, 160, 255, 0.5), transparent);
  animation: particlesShimmer 5s ease-in-out infinite alternate;
  pointer-events: none;
}
@keyframes corePulse {
  0%, 100% { opacity: 0.5; transform: translate(-50%, -50%) scale(1); }
  50%      { opacity: 0.9; transform: translate(-50%, -50%) scale(1.12); }
}
@keyframes nebulaFloat1 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33%      { transform: translate(4%, -3%) scale(1.06); }
  66%      { transform: translate(-3%, 2%) scale(0.95); }
}
@keyframes nebulaFloat2 {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50%      { transform: translate(-4%, 4%) scale(1.08); }
}
@keyframes nebulaFloat3 {
  0%   { opacity: 0.5; transform: scale(1) rotate(0deg); }
  100% { opacity: 0.9; transform: scale(1.15) rotate(4deg); }
}
@keyframes dustDrift {
  0%   { opacity: 0.4; transform: rotate(-12deg) translateX(0); }
  100% { opacity: 0.8; transform: rotate(-12deg) translateX(4%); }
}
@keyframes particlesShimmer {
  0%, 100% { opacity: 0.3; }
  50%      { opacity: 0.8; }
}
/* ========== 背景 ========== */
.star-background {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
  /* 深空渐变 — 中心偏紫、边缘深邃 */
  background:
    radial-gradient(ellipse at 50% 50%, #0d0b2e 0%, #06051a 45%, #020108 80%, #000000 100%);
}
/* ========== 滚动容器 ========== */
.star-scroll-layer {
  position: absolute;
  inset: 0;
  height: 200vh;          /* 视口高度的两倍 → 容纳正本 + 副本 */
  will-change: transform;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
}
/* 滚动方向 */
.scroll-down {
  animation-name: scrollDown;
}
.scroll-up {
  animation-name: scrollUp;
}
/* ========== 星星基础样式 ========== */
.star {
  position: absolute;
  will-change: transform, opacity;
  animation-name: twinkle;
  animation-timing-function: ease-in-out;
  animation-iteration-count: infinite;
}
.star-large {
  filter: blur(0px);
}
.star-medium {
  filter: blur(0.5px);
}
.star-small {
  filter: blur(1px);
}
/* ========== 关键帧 ========== */
/* 闪烁：亮度 + 缩放 */
@keyframes twinkle {
  0%, 100% {
    opacity: 0.25;
    transform: scale(0.7);
  }
  50% {
    opacity: 1;
    transform: scale(1.4);
  }
}
/*
 * 无缝循环原理：
 *   - 容器高度 = 200vh， stars 分布在 0~200vh 范围内
 *   - 正本在 0~100vh，副本在 ±100vh 偏移处
 *   - 动画移动 100vh 后，正本完全离开视口、副本正好填满视口
 *   - animation 从 100% 跳回 0% 时，正本与副本视觉完全相同 → 无跳帧
 */
/* 向上滚动：从 0 移到 -100vh */
@keyframes scrollUp {
  from { transform: translateY(0); }
  to   { transform: translateY(-100vh); }
}
/* 向下滚动：从 0 移到 +100vh */
@keyframes scrollDown {
  from { transform: translateY(0); }
  to   { transform: translateY(100vh); }
}
</style>
 