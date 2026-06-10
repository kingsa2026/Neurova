<template>
  <div class="nr-star-bg" aria-hidden="true">
    <div class="nr-nebula" />
    <canvas ref="canvasRef" class="nr-star-canvas" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const canvasRef = ref<HTMLCanvasElement | null>(null)
let animId = 0
let stars: { x: number; y: number; r: number; speed: number; opacity: number }[] = []

const initStars = (canvas: HTMLCanvasElement) => {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  canvas.width = window.innerWidth
  canvas.height = window.innerHeight
  stars = Array.from({ length: 200 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    r: Math.random() * 1.2 + 0.3,
    speed: Math.random() * 0.15 + 0.02,
    opacity: Math.random() * 0.5 + 0.2,
  }))

  const animate = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    for (const s of stars) {
      s.y -= s.speed
      if (s.y < -2) { s.y = canvas.height + 2; s.x = Math.random() * canvas.width }
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(255,255,255,${s.opacity})`
      ctx.fill()
    }
    animId = requestAnimationFrame(animate)
  }
  animate()
}

const onResize = () => {
  if (canvasRef.value) {
    canvasRef.value.width = window.innerWidth
    canvasRef.value.height = window.innerHeight
  }
}

onMounted(() => {
  if (canvasRef.value) initStars(canvasRef.value)
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  cancelAnimationFrame(animId)
  window.removeEventListener('resize', onResize)
})
</script>

<style scoped>
.nr-star-bg { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.nr-nebula {
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse 50% 40% at 15% 30%, rgba(99,102,241,0.07) 0%, transparent 70%),
    radial-gradient(ellipse 40% 30% at 85% 15%, rgba(34,211,238,0.05) 0%, transparent 60%),
    radial-gradient(ellipse 45% 35% at 50% 85%, rgba(167,139,250,0.04) 0%, transparent 60%),
    var(--nr-bg-deep);
}
.nr-star-canvas { position: absolute; inset: 0; }
</style>
