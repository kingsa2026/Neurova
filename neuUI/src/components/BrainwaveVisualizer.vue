<template>
  <div >
    <canvas ref="canvasRef"  />
    <div >
      <div v-for="wave in activeWaves" :key="wave.type" >
        <span  :style="{ background: wave.color }"></span>
        <span >{{ wave.label }}</span>
        <span >{{ wave.percent }}%</span>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted, computed } from 'vue'
/**
 * 脑波可视化组件
 * 基于神经科学理论，实现6种脑波状态的实时动画
 * 
 * 脑波类型：
 * - δ波 (Delta): 0.5~4Hz, 深度修复、无意识状态
 * - θ波 (Theta): 4~8Hz, 浅睡、创造力、梦境
 * - α波 (Alpha): 8~13Hz, 放松清醒、闭眼状态
 * - β波 (Beta): 13~30Hz, 专注、逻辑思维、警觉
 * - γ波 (Gamma): 30~100Hz, 认知整合、注意力、记忆
 */
const props = defineProps<{
  stage: 'active' | 'light' | 'rem' | 'deep'
}>()
const canvasRef = ref<HTMLCanvasElement | null>(null)
let animationId: number | null = null
let lastTime = 0
// 脑波类型定义
interface BrainWave {
  type: string
  label: string
  frequency: { min: number; max: number }
  amplitude: { min: number; max: number }
  color: string
  percent: number
}
// 五种核心脑波配置
const brainwaveTypes: Record<string, Omit<BrainWave, 'percent'>> = {
  delta: {
    type: 'delta',
    label: 'δ波',
    frequency: { min: 0.5, max: 4 },
    amplitude: { min: 75, max: 200 },
    color: '#1e3a8a', // 深蓝
  },
  theta: {
    type: 'theta',
    label: 'θ波',
    frequency: { min: 4, max: 8 },
    amplitude: { min: 100, max: 150 },
    color: '#7c3aed', // 紫色
  },
  alpha: {
    type: 'alpha',
    label: 'α波',
    frequency: { min: 8, max: 13 },
    amplitude: { min: 20, max: 100 },
    color: '#06b6d4', // 青色
  },
  beta: {
    type: 'beta',
    label: 'β波',
    frequency: { min: 13, max: 30 },
    amplitude: { min: 5, max: 50 },
    color: '#f59e0b', // 橙色
  },
  gamma: {
    type: 'gamma',
    label: 'γ波',
    frequency: { min: 30, max: 100 },
    amplitude: { min: 1, max: 5 },
    color: '#fbbf24', // 黄色
  },
}
// 四种状态的脑波分布
const stageWaveDistribution: Record<string, Record<string, number>> = {
  active: { // 活跃状态 - 整合空闲/思考/工作
    alpha: 30,   // 放松成分
    beta: 45,    // 专注成分
    gamma: 15,   // 认知成分
    theta: 8,    // 创意成分
    delta: 2,
    smr: 5,      // 专注节律
  },
  light: { // 浅睡状态 - N1+N2期
    theta: 65,
    spindle: 20, // 睡眠纺锤波（特殊）
    kcomplex: 10, // K复合波（特殊）
    alpha: 5,
    delta: 0,
    beta: 0,
    gamma: 0,
  },
  rem: { // 眼动期 - REM睡眠
    theta: 55,
    beta: 35,
    gamma: 10,
    alpha: 0,
    delta: 0,
  },
  deep: { // 深睡状态 - N3期
    delta: 85,
    theta: 15,
    alpha: 0,
    beta: 0,
    gamma: 0,
  },
}
// 当前活跃的脑波列表
const activeWaves = computed(() => {
  const distribution = stageWaveDistribution[props.stage] || stageWaveDistribution.active
  const waves: BrainWave[] = []
  for (const [type, percent] of Object.entries(distribution)) {
    if (percent > 0 && brainwaveTypes[type]) {
      waves.push({
        ...brainwaveTypes[type],
        percent,
      })
    }
  }
  return waves.sort((a, b) => b.percent - a.percent)
})
// 状态参数配置
const stageConfig = {
  active: { // 活跃状态 - 混合α/β/γ/θ
    baseFrequency: 15, // 混合频率
    baseAmplitude: 50,
    speed: 1.2,
    noise: 0.2,
    description: '活跃状态',
  },
  light: { // 浅睡状态 - θ波主导
    baseFrequency: 6, // θ波主导
    baseAmplitude: 70,
    speed: 0.3,
    noise: 0.4,
    description: '浅睡期',
  },
  rem: { // 眼动期 - θ/β混合
    baseFrequency: 6, // θ波 + β波混合
    baseAmplitude: 45,
    speed: 0.8,
    noise: 0.5,
    description: '眼动期',
  },
  deep: { // 深睡状态 - δ波主导
    baseFrequency: 2, // δ波主导
    baseAmplitude: 90,
    speed: 0.1,
    noise: 0.05,
    description: '深度睡眠',
  },
}
// 特殊波形配置
interface SpecialWave {
  type: string
  frequency: number
  duration: number
  amplitude: number
  color: string
  label: string
}
const specialWaves: Record<string, SpecialWave[]> = {
  light: [ // N2期睡眠纺锤波和K复合波
    {
      type: 'spindle',
      frequency: 13, // 11~16Hz
      duration: 1.5, // 0.5~2秒
      amplitude: 45,
      color: '#e5e7eb', // 银白色
      label: '睡眠纺锤波',
    },
    {
      type: 'kcomplex',
      frequency: 2,
      duration: 0.8,
      amplitude: 125,
      color: '#60a5fa', // 蓝白色
      label: 'K复合波',
    },
  ],
  rem: [ // REM期的锯齿波
    {
      type: 'sawtooth',
      frequency: 5,
      duration: 2,
      amplitude: 60,
      color: '#22d3ee', // 青色
      label: '锯齿波',
    },
  ],
}
// 状态转换过渡
let currentStage = ref(props.stage)
let transitionProgress = ref(1) // 0-1, 1表示完全过渡完成
let previousParams = ref(stageConfig[props.stage as keyof typeof stageConfig])
watch(() => props.stage, (newStage, oldStage) => {
  if (newStage !== oldStage) {
    previousParams.value = stageConfig[oldStage as keyof typeof stageConfig]
    transitionProgress.value = 0
    // 过渡动画
    const transitionDuration = 1500 // 1.5秒过渡
    const startTime = Date.now()
    const animateTransition = () => {
      const elapsed = Date.now() - startTime
      transitionProgress.value = Math.min(elapsed / transitionDuration, 1)
      if (transitionProgress.value < 1) {
        requestAnimationFrame(animateTransition)
      }
    }
    animateTransition()
    currentStage.value = newStage
  }
})
// 插值计算
function lerp(start: number, end: number, t: number): number {
  return start + (end - start) * t
}
// 生成脑波值
function generateBrainwave(
  x: number,
  time: number,
  stage: string,
  transitionT: number
): number {
  const current = stageConfig[stage as keyof typeof stageConfig] || stageConfig.active
  const prev = previousParams.value
  // 平滑过渡参数
  const t = easeInOutCubic(transitionT)
  const baseFreq = lerp(prev.baseFrequency, current.baseFrequency, t)
  const baseAmp = lerp(prev.baseAmplitude, current.baseAmplitude, t)
  const speed = lerp(prev.speed, current.speed, t)
  const noise = lerp(prev.noise, current.noise, t)
  const width = canvasRef.value?.width || 800
  const height = canvasRef.value?.height || 200
  const centerY = height / 2
  // 标准化x坐标
  const normalizedX = x / width
  // 多层脑波叠加
  let wave = 0
  // 1. 主脑波（基于状态的主导波）
  const distribution = stageWaveDistribution[stage] || stageWaveDistribution.active
  // α波（8~13Hz）- 空闲状态主导
  if (distribution.alpha > 0) {
    const alphaFreq = lerp(9, 10, Math.sin(time * 0.1) * 0.5 + 0.5) // 9~10Hz波动
    const alphaAmp = baseAmp * 0.6 * (distribution.alpha / 100)
    wave += Math.sin(normalizedX * alphaFreq * Math.PI * 2 + time * speed) * alphaAmp
  }
  // β波（13~30Hz）- 思考和工作状态主导
  if (distribution.beta > 0) {
    const betaFreq = lerp(18, 25, Math.sin(time * 0.15) * 0.5 + 0.5) // 18~25Hz
    const betaAmp = baseAmp * 0.35 * (distribution.beta / 100)
    // 添加高频锯齿成分
    wave += Math.sin(normalizedX * betaFreq * Math.PI * 2 + time * speed * 1.2) * betaAmp
    wave += Math.sin(normalizedX * betaFreq * 2 * Math.PI * 3 + time * speed * 2) * betaAmp * 0.2
  }
  // γ波（30~100Hz）- 认知整合
  if (distribution.gamma > 0) {
    const gammaFreq = 40 // 40Hz为主
    const gammaAmp = baseAmp * 0.15 * (distribution.gamma / 100)
    wave += Math.sin(normalizedX * gammaFreq * Math.PI * 2 + time * speed * 3) * gammaAmp
  }
  // θ波（4~8Hz）- 浅睡和REM主导
  if (distribution.theta > 0) {
    const thetaFreq = lerp(4, 7, Math.sin(time * 0.05) * 0.5 + 0.5) // 4~7Hz
    const thetaAmp = baseAmp * 0.7 * (distribution.theta / 100)
    wave += Math.sin(normalizedX * thetaFreq * Math.PI * 2 + time * speed * 0.5) * thetaAmp
  }
  // δ波（0.5~4Hz）- 深睡主导
  if (distribution.delta > 0) {
    const deltaFreq = lerp(1, 2, Math.sin(time * 0.02) * 0.5 + 0.5) // 0.5~2Hz
    const deltaAmp = baseAmp * 0.9 * (distribution.delta / 100)
    wave += Math.sin(normalizedX * deltaFreq * Math.PI * 2 + time * speed * 0.2) * deltaAmp
  }
  // 2. 特殊波形
  // 睡眠纺锤波（N2期特征）
  if (distribution.spindle && distribution.spindle > 0) {
    const spindleTime = (time * 3) % 5 // 每3~5秒一次
    if (spindleTime < 1.5) {
      const spindlePhase = spindleTime / 1.5
      const spindleAmp = Math.sin(spindlePhase * Math.PI) * 40 * (distribution.spindle / 100)
      wave += Math.sin(normalizedX * 13 * Math.PI * 2 + time * 8) * spindleAmp
    }
  }
  // K复合波（N2期特征）
  if (distribution.kcomplex && distribution.kcomplex > 0) {
    const kTime = (time * 2) % 8 // 随机出现
    if (kTime > 7.5 && kTime < 8) {
      const kPhase = (kTime - 7.5) / 0.5
      const kAmp = Math.sin(kPhase * Math.PI) * 100 * (distribution.kcomplex / 100)
      wave += Math.sin(normalizedX * 2 * Math.PI + time * 2) * kAmp
    }
  }
  // SMR波（感觉运动节律，12~15Hz）
  if (distribution.smr && distribution.smr > 0) {
    const smrFreq = 13.5 // 12~15Hz中心值
    const smrAmp = baseAmp * 0.4 * (distribution.smr / 100)
    wave += Math.sin(normalizedX * smrFreq * Math.PI * 2 + time * speed * 0.8) * smrAmp
  }
  // 3. 噪声和随机波动
  const randomNoise = (Math.random() - 0.5) * noise * baseAmp * 0.1
  wave += randomNoise
  // 4. 边界衰减（边缘逐渐减小）
  const edgeFade = 1 - Math.pow(Math.abs(normalizedX - 0.5) * 2, 2) * 0.3
  return centerY + wave * edgeFade * 0.5
}
// 缓动函数
function easeInOutCubic(t: number): number {
  return t < 0.5
    ? 4 * t * t * t
    : 1 - Math.pow(-2 * t + 2, 3) / 2
}
// 绘制函数
function draw(timestamp: number) {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  // 计算时间差
  const deltaTime = timestamp - lastTime
  lastTime = timestamp
  const time = timestamp / 1000
  const width = canvas.width
  const height = canvas.height
  // 清空画布（带渐变尾迹效果）
  ctx.fillStyle = 'rgba(15, 23, 42, 0.15)'
  ctx.fillRect(0, 0, width, height)
  // 获取当前状态的活跃波
  const waves = activeWaves.value
  const currentConfig = stageConfig[currentStage.value as keyof typeof stageConfig]
  // 绘制多层波形
  for (let layer = 0; layer < 3; layer++) {
    const layerOffset = layer * 0.3
    const layerAlpha = 1 - layer * 0.25
    ctx.beginPath()
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    // 根据主导波选择颜色
    const dominantWave = waves[0]
    const layerColor = dominantWave?.color || '#6366f1'
    ctx.strokeStyle = layer === 1 
      ? layerColor 
      : `${layerColor}${Math.round(layerAlpha * 80).toString(16).padStart(2, '0')}`
    ctx.lineWidth = layer === 1 ? 2.5 : 1.5
    for (let x = 0; x <= width; x += 2) {
      const y = generateBrainwave(x, time + layerOffset, currentStage.value, transitionProgress.value)
      if (x === 0) {
        ctx.moveTo(x, y)
      } else {
        ctx.lineTo(x, y)
      }
    }
    ctx.stroke()
    // 为顶层添加发光效果
    if (layer === 1) {
      ctx.shadowColor = layerColor
      ctx.shadowBlur = 10
      ctx.stroke()
      ctx.shadowBlur = 0
    }
  }
  // 绘制中心参考线
  ctx.beginPath()
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)'
  ctx.lineWidth = 1
  ctx.setLineDash([5, 5])
  ctx.moveTo(0, height / 2)
  ctx.lineTo(width, height / 2)
  ctx.stroke()
  ctx.setLineDash([])
  // 添加状态标识
  ctx.fillStyle = currentConfig ? `${currentConfig.description} - ${currentConfig.baseFrequency}Hz` : ''
  ctx.font = '12px Arial'
  ctx.fillText(currentConfig ? `${currentConfig.description} | ${currentConfig.baseFrequency}Hz` : '', 10, 20)
  animationId = requestAnimationFrame(draw)
}
// 调整画布大小
function resizeCanvas() {
  const canvas = canvasRef.value
  if (!canvas) return
  const parent = canvas.parentElement
  if (parent) {
    const rect = parent.getBoundingClientRect()
    canvas.width = rect.width
    canvas.height = 200
  }
}
onMounted(() => {
  resizeCanvas()
  lastTime = performance.now()
  animationId = requestAnimationFrame(draw)
  window.addEventListener('resize', resizeCanvas)
})
onUnmounted(() => {
  if (animationId) {
    cancelAnimationFrame(animationId)
  }
  window.removeEventListener('resize', resizeCanvas)
})
</script>
<style scoped>
.brainwave-visualizer {
  position: relative;
  width: 100%;
  height: 200px;
}
.brainwave-canvas {
  width: 100%;
  height: 100%;
  border-radius: 8px;
}
.brainwave-legend {
  position: absolute;
  top: 8px;
  right: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 8px 12px;
  background: rgba(15, 23, 42, 0.8);
  border-radius: 6px;
  backdrop-filter: blur(8px);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
}
.legend-color {
  width: 12px;
  height: 12px;
  border-radius: 3px;
}
.legend-label {
  color: rgba(255, 255, 255, 0.8);
  font-weight: 500;
}
.legend-percent {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.7rem;
}
</style>
 