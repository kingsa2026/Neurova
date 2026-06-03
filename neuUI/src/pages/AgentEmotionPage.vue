<template>
  <div >
    <div >
      <h2 ><HeartOutlined :style="{color:'#f472b6'}"/> 情绪分析</h2>
    </div>
    <div >
      <div >当前<b >{{ currentEmotion }}</b></div>
      <div >波动<b >{{ volatility }}</b></div>
      <div >触发<b >{{ triggersCount }}</b></div>
    </div>
    <div >
      <div >
        <h4>情绪雷达</h4>
        <canvas ref="c"></canvas>
      </div>
      <div >
        <h4>历史记录</h4>
        <div v-for="h in history" :key="h.id" >
          <div  :style="{background:h.color}"></div>
          <div>
            <div >
              <span >{{ h.emotion }}</span>
              <span >{{ h.time }}</span>
            </div>
            <div >{{ h.trigger }}</div>
            <div >
              <div  :style="{width:h.intensity+'%',background:h.color}"></div>
              <span>{{ h.intensity }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { request } from '@/api'
import { emotionAPI } from '@/api/modules/emotion'
import { useAgentPage } from '@/composables/useAgentPage'
import { HeartOutlined } from '@ant-design/icons-vue'
const { agentId, initAgent } = useAgentPage('/agent/:agentId/emotion', () => loadData())
const c = ref<HTMLCanvasElement>()
const currentEmotion = ref('愉悦')
const volatility = ref('低')
const triggersCount = ref('3')
const history = ref([
  { id: 1, emotion: '愉悦', trigger: '用户正面反馈', intensity: 85, time: '2分钟前', color: '#f472b6' },
  { id: 2, emotion: '好奇', trigger: '新类型问题', intensity: 65, time: '15分钟前', color: '#a78bfa' },
  { id: 3, emotion: '平静', trigger: '常规任务', intensity: 40, time: '1小时前', color: '#60a5fa' },
  { id: 4, emotion: '满足', trigger: '任务完成确认', intensity: 78, time: '2小时前', color: '#34d399' },
  { id: 5, emotion: '困惑', trigger: '模糊指令', intensity: 55, time: '4小时前', color: '#fbbf24' }
])
function draw() {
  const canvas = c.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')!
  const dpr = devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = rect.width * dpr
  canvas.height = rect.height * dpr
  ctx.scale(dpr, dpr)
  const w = rect.width, h = rect.height, cx = w / 2, cy = h / 2, rad = Math.min(w, h) / 2 - 30
  const labels = ['愉悦', '好奇', '平静', '满足', '困惑']
  const angles = labels.map((_, i) => (Math.PI * 2 / labels.length) * i - Math.PI / 2)
  const values = [85, 65, 40, 78, 55]
  ctx.clearRect(0, 0, w, h)
  for (let i = 1; i <= 4; i++) {
    ctx.beginPath()
    const rr = (rad / 4) * i
    angles.forEach((a, j) => {
      const x = cx + Math.cos(a) * rr
      const y = cy + Math.sin(a) * rr
      j === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.closePath()
    ctx.strokeStyle = 'rgba(255,255,255,0.08)'
    ctx.stroke()
  }
  angles.forEach((a, i) => {
    const x = cx + Math.cos(a) * rad
    const y = cy + Math.sin(a) * rad
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(x, y)
    ctx.strokeStyle = 'rgba(255,255,255,0.1)'
    ctx.stroke()
    ctx.fillStyle = 'rgba(255,255,255,0.7)'
    ctx.font = '12px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    const lx = cx + Math.cos(a) * (rad + 20)
    const ly = cy + Math.sin(a) * (rad + 20)
    ctx.fillText(labels[i], lx, ly)
  })
  ctx.beginPath()
  values.forEach((v, i) => {
    const x = cx + Math.cos(angles[i]) * (v / 100 * rad)
    const y = cy + Math.sin(angles[i]) * (v / 100 * rad)
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
  })
  ctx.closePath()
  ctx.fillStyle = 'rgba(244,114,182,0.25)'
  ctx.fill()
  ctx.strokeStyle = '#f472b6'
  ctx.lineWidth = 2
  ctx.stroke()
  values.forEach((v, i) => {
    const x = cx + Math.cos(angles[i]) * (v / 100 * rad)
    const y = cy + Math.sin(angles[i]) * (v / 100 * rad)
    ctx.beginPath()
    ctx.arc(x, y, 4, 0, Math.PI * 2)
    ctx.fillStyle = '#f472b6'
    ctx.fill()
  })
}
async function loadData() {
  try {
    const res = await emotionAPI.getAgentEmotion(agentId.value)
    const d = (res as { data?: Record<string, unknown> })?.data
    if (d) {
      if (d.emotion) currentEmotion.value = d.emotion as string
      if (d.volatility) volatility.value = d.volatility as string
      const triggers = d.triggers as unknown[]
      if (triggers?.length) triggersCount.value = String(triggers.length)
      const moodHistory = d.mood_history as { emotion: string; intensity: number; timestamp: string }[]
      if (moodHistory?.length) {
        const emotionColors: Record<string, string> = {
          joy: '#f472b6', sadness: '#60a5fa', anger: '#ef4444', fear: '#fbbf24',
          surprise: '#a78bfa', love: '#ec4899', hope: '#34d399', neutral: '#94a3b8',
        }
        history.value = moodHistory.map((h, i) => ({
          id: i + 1,
          emotion: h.emotion || '中性',
          trigger: (triggers?.[i] as string) || '',
          intensity: Math.round((h.intensity || 0) * 100),
          time: h.timestamp || '',
          color: emotionColors[h.emotion] || '#94a3b8',
        }))
      }
      await nextTick()
      draw()
    }
  } catch {
    try {
      const res = await request.get(`/agents/${agentId.value}/emotion`)
      const d = (res as { data?: Record<string, unknown> })?.data
      if (d) {
        if (d.current_emotion) currentEmotion.value = d.current_emotion as string
        if (d.volatility) volatility.value = d.volatility as string
        if (d.triggers_count) triggersCount.value = d.triggers_count as string
        const hist = d.history as { id: number; emotion: string; trigger: string; intensity: number; time: string; color: string }[]
        if (hist?.length) history.value = hist
        await nextTick()
        draw()
      }
    } catch { /* 使用静态数据 */ }
  }
}
onMounted(async () => {
  await initAgent()
  loadData()
  await nextTick()
  draw()
})
</script>
<style scoped>
.pg {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.hd {
  padding: 16px 24px;
  border-radius: 12px;
}
.t {
  font-size: 1.2rem;
  color: #e2e8f0;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sr {
  display: flex;
  gap: 12px;
}
.s {
  flex: 1;
  padding: 14px 18px;
  border-radius: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.85rem;
}
.s b {
  font-size: 1.4rem;
}
.c1 {
  color: #f472b6;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.chart {
  padding: 20px;
  border-radius: 12px;
}
.chart h4 {
  color: #e2e8f0;
  margin: 0 0 10px;
}
.chart canvas {
  width: 100%;
  height: 260px;
}
.list {
  padding: 20px;
  border-radius: 12px;
  overflow-y: auto;
  max-height: 360px;
}
.list h4 {
  color: #e2e8f0;
  margin: 0 0 12px;
}
.hitem {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.hdot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
}
.hrow {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hem {
  color: #e2e8f0;
  font-weight: 500;
}
.htime {
  color: rgba(255, 255, 255, 0.2);
  font-size: 0.72rem;
}
.htrigger {
  color: rgba(255, 255, 255, 0.35);
  font-size: 0.78rem;
  margin: 2px 0 4px;
}
.hbar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.hbf {
  height: 4px;
  border-radius: 2px;
}
.hbar span {
  color: rgba(255, 255, 255, 0.25);
  font-size: 0.7rem;
}
@media (max-width: 768px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
 