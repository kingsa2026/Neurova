&lt;template&gt;
  &lt;div &gt;
    &lt;div &gt;
      &lt;h2 &gt;&lt;ThunderboltOutlined :style="{color:'#f472b6'}" /&gt; 成长系统&lt;/h2&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;div &gt;成长等级&lt;b &gt;{{ growthLevel }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;问题解决&lt;b &gt;{{ problemSolved }}&lt;/b&gt;&lt;/div&gt;
      &lt;div &gt;动机水平&lt;b &gt;{{ motivation }}&lt;/b&gt;&lt;/div&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;canvas ref="c"&gt;&lt;/canvas&gt;
    &lt;/div&gt;
    &lt;div &gt;
      &lt;h4&gt;成长里程碑&lt;/h4&gt;
      &lt;a-timeline&gt;
        &lt;a-timeline-item v-for="m in ms" :key="m.id"&gt;
          &lt;template #dot&gt;&lt;span :style="{background:m.color}" /&gt;&lt;/template&gt;
          &lt;div&gt;
            &lt;b&gt;{{ m.title }}&lt;/b&gt;
            &lt;p&gt;{{ m.desc }}&lt;/p&gt;
            &lt;span &gt;{{ m.date }}&lt;/span&gt;
          &lt;/div&gt;
        &lt;/a-timeline-item&gt;
      &lt;/a-timeline&gt;
    &lt;/div&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { ref, onMounted, nextTick, computed } from 'vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { ThunderboltOutlined } from '@ant-design/icons-vue'
const { agentId, agentStore, initAgent } = useAgentPage('/agent/:agentId/growth', () =&gt; loadData())
const growthLevel = ref('Lv.--')
const problemSolved = ref('--')
const motivation = ref('--')
interface GrowthMilestone { id:number;title:string;desc:string;color:string;date:string }
const chartData = ref&lt;number[]&gt;([20, 35, 45, 55, 70, 78, 82, 85])
const ms = ref&lt;GrowthMilestone[]&gt;([])
const c = ref&lt;HTMLCanvasElement&gt;()
function draw() {
  const cv = c.value; if (!cv) return
  const ctx = cv.getContext('2d')!
  const dpr = devicePixelRatio || 1
  const r = cv.getBoundingClientRect()
  cv.width = r.width * dpr; cv.height = r.height * dpr
  ctx.scale(dpr, dpr)
  const w = r.width, h = r.height
  const pad = { t: 20, r: 20, b: 30, l: 40 }
  const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b
  const data = chartData.value
  ctx.clearRect(0, 0, w, h)
  const grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + ph)
  grad.addColorStop(0, 'rgba(244,114,182,0.3)')
  grad.addColorStop(1, 'rgba(244,114,182,0)')
  ctx.beginPath()
  const xs = pw / (data.length - 1)
  data.forEach((v, i) =&gt; {
    const x = pad.l + xs * i
    const y = pad.t + ph - (v / 100) * ph
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
  })
  ctx.lineTo(pad.l + xs * (data.length - 1), pad.t + ph)
  ctx.lineTo(pad.l, pad.t + ph)
  ctx.closePath()
  ctx.fillStyle = grad; ctx.fill()
  ctx.beginPath()
  data.forEach((v, i) =&gt; {
    const x = pad.l + xs * i
    const y = pad.t + ph - (v / 100) * ph
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
  })
  ctx.strokeStyle = '#f472b6'; ctx.lineWidth = 2; ctx.stroke()
  data.forEach((v, i) =&gt; {
    const x = pad.l + xs * i
    const y = pad.t + ph - (v / 100) * ph
    ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2)
    ctx.fillStyle = '#f472b6'; ctx.fill()
  })
  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  ctx.font = '10px sans-serif'; ctx.textAlign = 'center'
  for (let i = 0; i &lt; data.length; i++) {
    const x = pad.l + xs * i
    ctx.fillText(`Day${(i + 1) * 7}`, x, h - 8)
  }
}
const colors = ['#f472b6', '#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#ef4444', '#06b6d4', '#f472b6']
async function loadData() {
  try {
    const res = await request.get(`/growth/${agentId.value}`)
    if (res.code === 0 &amp;&amp; res.data) {
      const d = res.data
      if (d.level) growthLevel.value = `Lv.${d.level}`
      if (d.problems_solved) problemSolved.value = String(d.problems_solved)
      if (d.motivation) motivation.value = d.motivation
      if (d.level_history?.length) chartData.value = d.level_history.map((l: Record&lt;string,unknown&gt;) =&gt; ((l.value || l.score || l) as number))
      if (d.milestones?.length) ms.value = d.milestones.map((m: Record&lt;string,unknown&gt;, i: number) =&gt; ({
        id: m.id || i + 1,
        title: m.title || m.name || '',
        desc: m.description || m.desc || '',
        color: m.color || colors[i % colors.length],
        date: m.date || m.time || `Day ${(i + 1) * 7}`,
      }))
    }
  } catch { /* ignore */ }
}
onMounted(async () =&gt; {
  await initAgent()
  loadData()
  await nextTick(); draw()
})
&lt;/script&gt;
&lt;style scoped&gt;
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}.c1{color:#f472b6;}
.cv{padding:20px;border-radius:12px;}
.cv canvas{width:100%;height:200px;}
.ml{padding:20px;border-radius:12px;}
.ml h4{color:#e2e8f0;margin:0 0 16px;}
.ml b{color:#e2e8f0;}
.ml p{color:rgba(255,255,255,0.4);font-size:0.82rem;margin:2px 0;}
.md{color:rgba(255,255,255,0.2);font-size:0.72rem;}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;}
&lt;/style&gt;
&nbsp;