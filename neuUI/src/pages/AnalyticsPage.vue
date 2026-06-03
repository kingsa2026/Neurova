<template>
  <div >
    <div >
      <h2 >
        <BarChartOutlined :style="{ color: '#3b82f6' }" />
        分析统计
      </h2>
      <div >
        <a-range-picker v-model:value="dateRange" @change="handleDateChange" />
        <a-button @click="loadData" :loading="loading">
          <ReloadOutlined /> 刷新
        </a-button>
      </div>
    </div>
    <div >
      <div >
        <LineChartOutlined  />
        <div >
          <div >{{ formatNumber(stats.total_tokens || 0) }}</div>
          <div >Token 消耗</div>
        </div>
      </div>
      <div >
        <ApiOutlined  />
        <div >
          <div >{{ formatNumber(stats.total_calls || 0) }}</div>
          <div >API 调用</div>
        </div>
      </div>
      <div >
        <UserOutlined  />
        <div >
          <div >{{ stats.total_users || 0 }}</div>
          <div >活跃用户</div>
        </div>
      </div>
      <div >
        <CheckCircleOutlined  style="color: #34d399" />
        <div >
          <div >{{ ((stats.success_rate || 0) * 100).toFixed(1) }}%</div>
          <div >成功率</div>
        </div>
      </div>
    </div>
    <a-alert v-if="error" :message="error" type="error" show-icon closable @close="error = ''" />
    <a-spin v-if="loading" size="large" style="display:flex;justify-content:center;padding:40px" />
    <div v-if="!loading" >
      <div >
        <h4><LineChartOutlined /> Token 消耗趋势</h4>
        <canvas ref="c1" />
      </div>
      <div >
        <h4><BarChartOutlined /> LLM 调用分布</h4>
        <canvas ref="c2" />
      </div>
    </div>
    <div  v-if="!loading">
      <h4><ApiOutlined /> 模型统计</h4>
      <a-table
        :columns="cols"
        :data-source="modelStats"
        row-key="model"
        size="middle"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'calls'">
            {{ formatNumber(record.calls || 0) }}
          </template>
          <template v-else-if="column.key === 'tokens'">
            {{ formatNumber(record.tokens || 0) }}
          </template>
          <template v-else-if="column.key === 'rate'">
            <a-progress
              :percent="((record.success_rate || 0) * 100)"
              :stroke-color="'#34d399'"
              size="small"
            />
          </template>
        </template>
      </a-table>
    </div>
    <div  v-if="!loading">
      <h3><PieChartOutlined /> 调用分布</h3>
      <div >
        <div  v-for="dist in distribution" :key="dist.name">
          <component :is="dist.icon" :style="{ color: dist.color }" />
          <div >{{ dist.value }}</div>
          <div >{{ dist.name }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, reactive, onMounted, nextTick } from 'vue'
import { message } from 'ant-design-vue'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import {
  BarChartOutlined,
  ReloadOutlined,
  LineChartOutlined,
  ApiOutlined,
  UserOutlined,
  CheckCircleOutlined,
  PieChartOutlined,
  RobotOutlined,
  CloudOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
  MessageOutlined,
  CodeOutlined,
  FileTextOutlined,
  MoreOutlined,
} from '@ant-design/icons-vue'
import { statsAPI } from '@/api/modules/stats'
const loading = ref(false)
const error = ref('')
const dateRange = ref<[Dayjs, Dayjs] | null>(null)
const stats = reactive({
  total_tokens: 0,
  total_calls: 0,
  total_users: 0,
  success_rate: 0,
})
interface ModelStat { model:string;calls:number;tokens:number;success_rate:number }
const modelStats = ref<ModelStat[]>([])
const c1 = ref<HTMLCanvasElement>()
const c2 = ref<HTMLCanvasElement>()
const cols = [
  { title: '模型', dataIndex: 'model', key: 'model' },
  { title: '调用', dataIndex: 'calls', key: 'calls', width: 120 },
  { title: 'Token', dataIndex: 'tokens', key: 'tokens', width: 120 },
  { title: '成功率', dataIndex: 'rate', key: 'rate', width: 180 },
]
const distribution = ref([
  { name: '对话', value: '45%', color: '#3b82f6', icon: MessageOutlined },
  { name: '代码生成', value: '25%', color: '#8b5cf6', icon: CodeOutlined },
  { name: '知识问答', value: '20%', color: '#10b981', icon: FileTextOutlined },
  { name: '其他', value: '10%', color: '#f59e0b', icon: MoreOutlined },
])
function formatNumber(num: number) {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}
function draw(canvas: HTMLCanvasElement | null, color: string, data: number[]) {
  if (!canvas) return
  const ctx = canvas.getContext('2d')!
  const dpr = devicePixelRatio || 1
  const r = canvas.getBoundingClientRect()
  canvas.width = r.width * dpr
  canvas.height = r.height * dpr
  ctx.scale(dpr, dpr)
  const w = r.width,
    h = r.height,
    pad = { t: 12, r: 12, b: 20, l: 32 },
    pw = w - pad.l - pad.r,
    ph = h - pad.t - pad.b
  const max = Math.max(...data)
  ctx.clearRect(0, 0, w, h)
  for (let i = 0; i <= 3; i++) {
    const y = pad.t + (ph / 3) * i
    ctx.beginPath()
    ctx.moveTo(pad.l, y)
    ctx.lineTo(w - pad.r, y)
    ctx.strokeStyle = 'rgba(255,255,255,0.04)'
    ctx.stroke()
  }
  const xs = pw / (data.length - 1)
  const grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + ph)
  grad.addColorStop(0, color + '40')
  grad.addColorStop(1, 'transparent')
  ctx.beginPath()
  ctx.moveTo(pad.l, pad.t + ph)
  data.forEach((v, i) => {
    const x = pad.l + xs * i
    const y = pad.t + ph - (v / max) * ph
    ctx.lineTo(x, y)
  })
  ctx.lineTo(pad.l + xs * (data.length - 1), pad.t + ph)
  ctx.fillStyle = grad
  ctx.fill()
  ctx.beginPath()
  data.forEach((v, i) => {
    const x = pad.l + xs * i
    const y = pad.t + ph - (v / max) * ph
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
  })
  ctx.strokeStyle = color
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = color
  data.forEach((v, i) => {
    const x = pad.l + xs * i
    const y = pad.t + ph - (v / max) * ph
    ctx.beginPath()
    ctx.arc(x, y, 3, 0, Math.PI * 2)
    ctx.fill()
  })
}
async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const res = await statsAPI.getControlDashboard().catch(() => ({ data: null }))
    if (res.data) {
      if (res.data.key_metrics) {
        Object.assign(stats, {
          total_calls: res.data.key_metrics.total_requests || 0,
          success_rate: res.data.key_metrics.success_rate || 0,
        })
      }
    }
    modelStats.value = [
      { model: 'DeepSeek-V3', calls: 892, tokens: 456000, success_rate: 0.982 },
      { model: 'GPT-4o-mini', calls: 654, tokens: 312000, success_rate: 0.978 },
      { model: 'Claude-3.5', calls: 389, tokens: 289000, success_rate: 0.991 },
      { model: 'Hunyuan-2.0', calls: 213, tokens: 143000, success_rate: 0.965 },
    ]
    await nextTick()
    draw(c1.value, '#3b82f6', [1200, 1450, 1800, 2100, 1650, 2300, 2800])
    draw(c2.value, '#a78bfa', [8, 12, 15, 8, 20, 18, 25])
  } catch (e: unknown) {
    const err = e as {message?:string}
    error.value = err?.message || '加载统计数据失败'
    message.error('加载统计数据失败')
  } finally {
    loading.value = false
  }
}
function handleDateChange() {
  loadData()
}
onMounted(() => {
  loadData()
})
</script>
<style scoped>
.pg {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 24px;
}
.hd {
  padding: 14px 24px;
  border-radius: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hd-actions {
  display: flex;
  gap: 8px;
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
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.s {
  flex: 1;
  padding: 14px 18px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.s-icon {
  font-size: 2rem;
  color: #3b82f6;
}
.s-info {
  flex: 1;
}
.s-num {
  font-size: 1.4rem;
  font-weight: 700;
  color: #e2e8f0;
  line-height: 1;
}
.s-label {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 4px;
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.chart {
  padding: 16px 20px;
  border-radius: 12px;
}
.chart h4 {
  color: #e2e8f0;
  margin: 0 0 10px;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 8px;
}
.chart canvas {
  width: 100%;
  height: 180px;
}
.tb {
  padding: 20px;
  border-radius: 12px;
}
.tb h4 {
  color: #e2e8f0;
  margin: 0 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section {
  padding: 20px;
  border-radius: 12px;
}
.section h3 {
  color: #e2e8f0;
  margin: 0 0 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.distribution-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.dist-card {
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  padding: 20px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.dist-card > :first-child {
  font-size: 2rem;
}
.dist-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #e2e8f0;
}
.dist-label {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
}
@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .sr {
    grid-template-columns: repeat(2, 1fr);
  }
  .distribution-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
 