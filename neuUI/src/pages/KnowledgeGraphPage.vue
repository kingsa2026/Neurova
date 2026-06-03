<template>
  <div >
    <div >
      <h2 ><ShareAltOutlined :style="{color:'#06b6d4'}" /> 知识图谱</h2>
    </div>
    <div >
      <div >节点数<b >{{ stats.nodes }}</b></div>
      <div >关系数<b >{{ stats.edges }}</b></div>
      <div >社区<b >{{ stats.communities }}</b></div>
    </div>
    <div >
      <canvas ref="c"></canvas>
    </div>
    <div >
      <a-input-search v-model:value="keyword" placeholder="搜索节点..." style="width:280px" @search="onSearch" />
      <a-space>
        <a-button size="small" @click="zoomIn"><ZoomInOutlined />放大</a-button>
        <a-button size="small" @click="zoomOut"><ZoomOutOutlined />缩小</a-button>
        <a-button size="small" @click="resetView"><SyncOutlined />重置</a-button>
      </a-space>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref, nextTick, computed } from 'vue'
import { message } from 'ant-design-vue'
import { request } from '@/api'
import { useAgentPage } from '@/composables/useAgentPage'
import { ShareAltOutlined, ZoomInOutlined, ZoomOutOutlined, SyncOutlined } from '@ant-design/icons-vue'
const { agentId } = useAgentPage('/agent/:agentId/knowledge-graph', () => loadData())
const c = ref<HTMLCanvasElement>()
const keyword = ref('')
const stats = ref({ nodes: 0, edges: 0, communities: 0 })
interface GraphNode {
  id: string
  label: string
  color: string
  x?: number
  y?: number
  r?: number
}
interface GraphEdge {
  source: string
  target: string
  from?: string
  to?: string
}
const nodes = ref<GraphNode[]>([])
const edges = ref<GraphEdge[]>([])
const scale = ref(1)
const msg = message
async function loadData() {
  try {
    const res = await request.get(`/agents/${agentId.value}/knowledge-graph`)
    if (res.code === 0 && res.data) {
      const d = res.data
      stats.value = {
        nodes: d.node_count ?? d.nodes?.length ?? 0,
        edges: d.edge_count ?? d.edges?.length ?? 0,
        communities: d.community_count ?? d.communities ?? 0,
      }
      nodes.value = d.nodes ?? []
      edges.value = d.edges ?? []
      await nextTick()
      draw()
    }
  } catch (e: unknown) {
    msg.warning('知识图谱数据加载失败，使用演示数据')
    useDemoData()
  }
}
function useDemoData() {
  stats.value = { nodes: 8, edges: 9, communities: 3 }
  nodes.value = [
    { id: 'n1', label: '记忆', color: '#06b6d4', x: 0.3, y: 0.2, r: 12 },
    { id: 'n2', label: '对话', color: '#3b82f6', x: 0.6, y: 0.3, r: 14 },
    { id: 'n3', label: '技能', color: '#a78bfa', x: 0.5, y: 0.6, r: 10 },
    { id: 'n4', label: '知识', color: '#f59e0b', x: 0.2, y: 0.5, r: 11 },
    { id: 'n5', label: '文档', color: '#34d399', x: 0.7, y: 0.6, r: 13 },
    { id: 'n6', label: '经验', color: '#f472b6', x: 0.4, y: 0.4, r: 9 },
    { id: 'n7', label: '规则', color: '#ef4444', x: 0.65, y: 0.15, r: 10 },
    { id: 'n8', label: '元数据', color: '#6366f1', x: 0.15, y: 0.35, r: 8 },
  ]
  edges.value = [
    { source: 'n1', target: 'n2' },
    { source: 'n1', target: 'n6' },
    { source: 'n2', target: 'n3' },
    { source: 'n2', target: 'n4' },
    { source: 'n3', target: 'n5' },
    { source: 'n4', target: 'n7' },
    { source: 'n5', target: 'n8' },
    { source: 'n6', target: 'n7' },
    { source: 'n2', target: 'n8' },
  ]
}
function draw() {
  const cv = c.value; if (!cv) return
  const ctx = cv.getContext('2d')!
  const dpr = devicePixelRatio || 1
  const r = cv.getBoundingClientRect()
  cv.width = r.width * dpr; cv.height = r.height * dpr
  ctx.scale(dpr * scale.value, dpr * scale.value)
  const w = r.width, h = r.height
  ctx.clearRect(0, 0, w, h)
  interface RenderedNode {
    id: string
    x: number
    y: number
    r: number
    l: string
    c: string
  }
  const nodeMap: Record<string, RenderedNode> = {}
  const renderedNodes = nodes.value.map((n, i) => {
    const x = (n.x ?? (0.1 + Math.random() * 0.8)) * w
    const y = (n.y ?? (0.1 + Math.random() * 0.8)) * h
    const obj = {
      id: n.id,
      x: n.x ? n.x * w : x,
      y: n.y ? n.y * h : y,
      r: n.r ?? 12,
      l: n.label ?? n.l ?? `Node ${i}`,
      c: n.color ?? '#06b6d4',
    }
    nodeMap[obj.id] = obj
    return obj
  })
  edges.value.forEach((e) => {
    const a = nodeMap[e.source] || nodeMap[e.from] || renderedNodes[0]
    const b = nodeMap[e.target] || nodeMap[e.to] || renderedNodes[1]
    if (!a || !b) return
    ctx.beginPath()
    ctx.moveTo(a.x, a.y)
    ctx.lineTo(b.x, b.y)
    ctx.strokeStyle = 'rgba(255,255,255,0.08)'
    ctx.lineWidth = 1
    ctx.stroke()
  })
  renderedNodes.forEach(n => {
    ctx.beginPath()
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
    ctx.fillStyle = n.c + '30'
    ctx.fill()
    ctx.strokeStyle = n.c
    ctx.lineWidth = 2
    ctx.stroke()
    ctx.fillStyle = '#e2e8f0'
    ctx.font = '11px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(n.l, n.x, n.y - n.r - 4)
  })
}
function zoomIn() { scale.value = Math.min(scale.value + 0.2, 3); nextTick(draw) }
function zoomOut() { scale.value = Math.max(scale.value - 0.2, 0.3); nextTick(draw) }
function resetView() { scale.value = 1; nextTick(draw) }
function onSearch() { loadData() }
onMounted(async () => {
  await loadData()
  await nextTick()
  draw()
})
</script>
<style scoped>
.pg{display:flex;flex-direction:column;gap:14px;}
.hd{padding:16px 24px;border-radius:12px;}
.t{font-size:1.2rem;color:#e2e8f0;margin:0;display:flex;align-items:center;gap:8px;}
.sr{display:flex;gap:12px;}
.s{flex:1;padding:14px 18px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;color:rgba(255,255,255,0.5);font-size:.85rem;}
.s b{font-size:1.4rem;}
.c1{color:#06b6d4;}
.cv{padding:20px;border-radius:12px;}
.cv canvas{width:100%;height:300px;cursor:grab;}
.bt{padding:12px 16px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;}
</style>
 