<template>
  <div class="explorer3d-wrap">
    <div class="explorer3d-toolbar">
      <a-input v-model:value="focusInput" size="sm"
               :placeholder="t('knowledge.workbenchFocus')"
               class="focus-input" />
      <span class="hop-label">{{ t('knowledge.workbenchHops') }}</span>
      <a-select v-model:value="hops" size="sm" class="hops-select">
        <!-- 与后端 subgraph 的 le=12 对齐：跳数是探索半径旋钮，被 limit 截断
             时有 truncated 提示兜底；后端收录满 limit 即提前终止 BFS。 -->
        <a-select-option v-for="h in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]" :key="h" :value="h">{{ h }}</a-select-option>
      </a-select>
      <GlassButton size="sm" :loading="loading" @click="refetch()">
        {{ t('common.refresh') }}
      </GlassButton>
      <GlassButton
        v-if="currentNodeId || props.focusId || focusInput.trim()"
        size="sm"
        variant="secondary"
        @click="resetToFull"
      >
        {{ t('knowledge.workbenchFullGraph') }}
      </GlassButton>
      <a-select
        v-model:value="visibleTypes"
        mode="multiple"
        size="sm"
        allow-clear
        class="types-select"
        :max-tag-count="2"
        :placeholder="t('knowledge.workbenchFilterTypes')"
        :options="typeOptions"
      />
      <a-tag v-if="truncated" color="orange">{{ t('knowledge.workbenchTruncatedHint', { total: totalNodes }) }}</a-tag>
    </div>
    <div ref="containerRef" class="explorer3d-canvas"></div>
    <div v-if="empty3d && !loading" class="explorer3d-empty">
      <a-empty :description="t('common.noData')" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 3D 探索器（升级计划 S4 → B12 UI 增强）：
 * - 生物电信号动画：linkDirectionalParticles 沿边流动 + 脉冲色 + 曲率
 * - 节点常态标签：nodeThreeObject 自定义 Group（球体 + Canvas Sprite 文字贴图）
 * - 科技感氛围：暗底 + 辉光材质 + 点光源 + 节点脉冲
 *
 * `3d-force-graph` 动态 import 懒加载不变——WebGL 与 three 系依赖不进主包。
 * 子图由服务端裁剪（focus/hops/limit），客户端不养一张大图；
 * 节点点击 emit('select')，与 2D 画布选中同步。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassButton from '@/components/GlassButton.vue'
import { request } from '@/api'

const props = defineProps<{
  agentId: string
  focusId?: string
}>()
const emit = defineEmits<{
  (e: 'select', nodeId: string, label: string): void
  (e: 'clear'): void
}>()

const { t } = useI18n()
const containerRef = ref<HTMLElement | null>(null)
const loading = ref(false)
const focusInput = ref('')
const hops = ref(2)
const empty3d = ref(false)
const truncated = ref(false)
const totalNodes = ref(0)
// 类型过滤器（渲染降噪）：只影响显示集，不改服务端数据；空=全部显示。
const visibleTypes = ref<string[]>([])
let rawNodes: Array<{ id: string; name: string; type: string }> = []
let rawLinks: Array<{ source: string; target: string; relation: string }> = []

let graph: any = null
let disposed = false
// 一次性 fit 标记：每次 graphData 后置位，引擎冷却消费一次——避免用户拖拽/ reheats
// 后的每次冷却都把相机抢回全图。
let fitPending = false

// 全节点入视：把力导布局的包围盒框进当前视口（修「固定相机裁掉边缘节点」）。
// 空集不 fit（无包围盒可框）。resize/全屏后视口变了也走这里重框。
const fitToView = (durationMs = 400) => {
  if (graph && rawNodes.length) graph.zoomToFit(durationMs, 40)
}

const currentNodeId = ref('')

// ── B12 UI：生物电信号配色 ────────────────────────────────────────
/** 节点类型 → 辉光色（生物荧光盘：靛/青/翠/琥珀/洋红/冰蓝） */
const NEURON_PALETTE: Record<string, string> = {
  concept: '#00e5ff',
  person: '#7c4dff',
  organization: '#00c853',
  location: '#ffab00',
  event: '#f50057',
  document: '#40c4ff',
  product: '#76ff03',
  custom: '#b388ff',
}
const FALLBACK_NEURON = '#6366f1'
/** 连接线基准色（亮青高饱）与信号粒子色（亮白闪） */
const LINK_BASE = '#00fff2'
const LINK_PARTICLE = '#ffffff'
const LINK_HIGHLIGHT = '#ffab40'
const SELECT_NEURON = '#f59e0b'

const neuronColor = (node: any) =>
  node?.id === currentNodeId.value
    ? SELECT_NEURON
    : NEURON_PALETTE[node?.type] ?? FALLBACK_NEURON

const typeOptions = computed(() => {
  const kinds = new Set(rawNodes.map((n) => n.type).filter(Boolean))
  return Array.from(kinds).sort().map((k) => ({ value: k, label: k }))
})

// ── Canvas 文字 Sprite 工厂 ──────────────────────────────────────
// 每个节点一张离屏 canvas → CanvasTexture → THREE.Sprite（始终面向相机）。
// 字号 64px 保证缩放后清晰；透明底 + 发光描边，暗底上一目了然。
const labelTextureCache = new Map<string, { texture: any; canvas: any }>()

const makeLabelSprite = (text: string, three: any, color: string) => {
  const cached = labelTextureCache.get(text)
  if (cached) return cached

  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')!
  const fontSize = 64
  ctx.font = `${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`
  const metrics = ctx.measureText(text)
  canvas.width = Math.ceil(metrics.width + 24)
  canvas.height = fontSize + 20

  const ctx2 = canvas.getContext('2d')!
  ctx2.font = `${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`
  ctx2.textBaseline = 'middle'
  // 发光描边（暗底衬托）
  ctx2.shadowColor = color
  ctx2.shadowBlur = 12
  ctx2.fillStyle = '#e0f7fa'
  ctx2.fillText(text, 12, canvas.height / 2)
  // 再画一遍去阴影纯色填充（清晰主体）
  ctx2.shadowColor = 'transparent'
  ctx2.fillStyle = '#e0f7fa'
  ctx2.fillText(text, 12, canvas.height / 2)

  const texture = new three.CanvasTexture(canvas)
  texture.needsUpdate = true
  const entry = { texture, canvas }
  labelTextureCache.set(text, entry)
  return entry
}

// ── 自定义节点对象：球体（辉光材质）+ 文字 Sprite ────────────────
// nodeThreeObject 每个节点调用一次；返回 THREE.Group 代替默认球体。
// selected 节点额外放大＋琥珀色；标签用节点类型对应辉光色。
const makeNodeObject = (node: any, three: any) => {
  const group = new three.Group()
  const color = neuronColor(node)
  const isSelected = node?.id === currentNodeId.value
  const radius = isSelected ? 6 : 4

  // 核心球体：MeshStandardMaterial 带自发光（暗场中发亮）
  const sphereGeo = new three.SphereGeometry(radius, 16, 16)
  const sphereMat = new three.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: isSelected ? 0.8 : 0.4,
    roughness: 0.3,
    metalness: 0.1,
  })
  const sphere = new three.Mesh(sphereGeo, sphereMat)
  group.add(sphere)

  // 外圈辉光：半透明放大球壳（呼吸感）
  const glowGeo = new three.SphereGeometry(radius * 1.6, 12, 12)
  const glowMat = new three.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: isSelected ? 0.15 : 0.08,
    side: three.BackSide,
  })
  const glow = new three.Mesh(glowGeo, glowMat)
  group.add(glow)

  // 常态标签 Sprite
  const label = String(node?.name ?? node?.id ?? '')
  if (label) {
    const { texture, canvas } = makeLabelSprite(label, three, color)
    const spriteMat = new three.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
    })
    const sprite = new three.Sprite(spriteMat)
    // 缩放比 = canvas 宽高比 × 全局因子（确保文字不压缩变形）
    const scaleFactor = 0.08
    sprite.scale.set(canvas.width * scaleFactor, canvas.height * scaleFactor, 1)
    sprite.position.set(0, radius + canvas.height * scaleFactor * 0.5 + 2, 0)
    group.add(sprite)
  }

  return group
}

// ── 渲染集按类型过滤：边只保留两端都可见的 ────────────────────────
const applyRender = () => {
  const nodes = visibleTypes.value.length
    ? rawNodes.filter((n) => visibleTypes.value.includes(n.type))
    : rawNodes
  const ids = new Set(nodes.map((n) => n.id))
  const links = visibleTypes.value.length
    ? rawLinks.filter((l) => ids.has(l.source) && ids.has(l.target))
    : rawLinks
  void render({ nodes, links })
}

watch(visibleTypes, () => {
  applyRender()
})

const refetch = async (opts?: { forceFull?: boolean }) => {
  if (!containerRef.value) return
  loading.value = true
  try {
    // limit 不在客户端定值：缺省跟全局设置 advanced.graph_studio_limit（高级设置卡），
    // 服务端单点解析（显式参数 > 设置 > 200）；这里带 limit 会造出第二份口径。
    const params: Record<string, unknown> = { hops: hops.value }
    if (!opts?.forceFull) {
      const focus = currentNodeId.value || props.focusId || focusInput.value.trim()
      if (focus) params.focus = focus
    }
    const res: any = await request.get(
      `/knowledge-graph/${props.agentId}/subgraph`, { params })
    const data = res?.data ?? res
    truncated.value = Boolean(data?.truncated)
    totalNodes.value = Number(data?.total_nodes ?? 0)
    rawNodes = (data?.nodes ?? []).map((n: any) => ({
      id: n.id, name: n.label, type: n.type,
    }))
    rawLinks = (data?.edges ?? []).map((e: any) => ({
      source: e.source, target: e.target, relation: e.relation,
    }))
    applyRender()
    if (!currentNodeId.value) currentNodeId.value = ''
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const render = async (data: { nodes: Array<{ id: string; name: string; type: string }>; links: Array<{ source: string; target: string; relation: string }> }) => {
  if (!containerRef.value || disposed) return
  const nodes = data.nodes
  const links = data.links
  empty3d.value = nodes.length === 0
  if (!graph) {
    // 批 W2：记忆化为单 Promise——修前 await import 期间第二次 render
    // 同样通过判空，同一容器 new 两个 ForceGraph3D（WebGL 上下文泄漏）
    if (!initPromise) {
      initPromise = _createGraph()
    }
    await initPromise
  }
  graph.graphData({ nodes, links })
  fitPending = nodes.length > 0
}

let initPromise: Promise<void> | null = null
const _createGraph = async () => {
    const mod = await import('3d-force-graph')
    // v1.80 起是类构造 new ForceGraph3D(element)：旧版 Kapsule 双调用
    // ForceGraph3D()(el) 会把 class 当普通函数调，TypeError 后静默空白。
    const ForceGraph3D = (mod as any).default ?? mod
    if (!containerRef.value || disposed) return

    // 动态 import three（3d-force-graph 的 peer dependency，不进主包）
    const threeMod = await import('three')
    const three = threeMod

    try {
      graph = new ForceGraph3D(containerRef.value)
        // 暗宇宙底色（生物电信号在暗场中最醒目）
        .backgroundColor('rgba(4, 8, 18, 0.92)')
        // ── 节点：自定义 Group（辉光球体＋常态标签 Sprite） ──
        .nodeThreeObject((node: any) => makeNodeObject(node, three))
        .nodeThreeObjectExtend(false)
        .nodeLabel((node: any) => String(node?.name ?? node?.id ?? ''))
        .onNodeClick((node: any) => {
          currentNodeId.value = String(node?.id ?? '')
          emit('select', currentNodeId.value, String(node?.name ?? ''))
          if (graph) graph.nodeThreeObject(graph.nodeThreeObject())
        })
        // 点空白两态：聚焦视图里退回全图；全图态至多清节点高亮。
        // 此前无条件 resetToFull——全图态点空白＝刷新图谱（实测 bug）。
        .onBackgroundClick(() => {
          if (props.focusId || focusInput.value.trim()) {
            resetToFull()
            return
          }
          if (currentNodeId.value) {
            currentNodeId.value = ''
            emit('clear')
            if (graph) graph.nodeThreeObject(graph.nodeThreeObject())
          }
        })
        // 力导冷却后框全图：布局 settled 的包围盒才真实，此时 fit 才能把全部节点入视。
        .onEngineStop(() => {
          if (fitPending) {
            fitPending = false
            fitToView()
          }
        })
        // ── 连接线：生物电信号 ──
        // 暗青色基线（低透明度作底），选中节点的关联边亮琥珀
        .linkColor((link: any) => {
          const sid = typeof link.source === 'object' ? link.source?.id : link.source
          const tid = typeof link.target === 'object' ? link.target?.id : link.target
          return sid === currentNodeId.value || tid === currentNodeId.value
            ? LINK_HIGHLIGHT : LINK_BASE
        })
        .linkWidth(4)
        .linkOpacity(0.85)
        // 微曲率——有机感，不是 CAD 直线
        .linkCurvature(0.18)
        // ── 生物电粒子：沿线流动的信号脉冲 ──
        .linkDirectionalParticles(5)
        .linkDirectionalParticleSpeed(0.015)
        .linkDirectionalParticleWidth(4.5)
        .linkDirectionalParticleColor(LINK_PARTICLE)
        // ── 灯光：暗场点光＋环境光（辉光材质需要） ──
        .lights([
          new three.AmbientLight(0x1a1a2e, Math.PI * 0.5),
          new three.DirectionalLight(0x00e5ff, 0.4 * Math.PI),
          new three.PointLight(0x7c4dff, Math.PI * 0.3, 500),
        ])
      if (containerRef.value.clientWidth) {
        graph.width(containerRef.value.clientWidth)
        graph.height(containerRef.value.clientHeight)
      }
    } catch (e: any) {
      // 渲染器初始化失败（WebGL 缺席/依赖形状变化）落可见提示，不静默空白。
      message.error(e?.message || t('common.error'))
      empty3d.value = true
      return
    }
}

watch(() => props.focusId, (next) => {
  if (next) {
    currentNodeId.value = next
    focusInput.value = ''
    void refetch()
  }
})

watch(hops, () => {
  void refetch()
})

const resetToFull = () => {
  // 焦点三处状态一起清：内部焦点、手动输入、父组件选中态——
  // 漏任何一处，下一次 refetch 都会带着旧 focus 又回到邻域视图。
  currentNodeId.value = ''
  focusInput.value = ''
  emit('clear')
  // forceFull：emit('clear') 后父级 prop 同步晚于本次请求，若读 props.focusId
  // 会把原聚焦视图原样拉回来——「回到全图」按钮与点空白退出同根因。
  void refetch({ forceFull: true })
}

const handleResize = () => {
  if (graph && containerRef.value) {
    graph.width(containerRef.value.clientWidth)
    graph.height(containerRef.value.clientHeight)
    // 视口尺寸变了（含全屏切换派发的 resize）：重框全图，否则仍按旧包围盒裁节点。
    fitToView(200)
  }
}

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  await refetch()
  handleResize()
})

onBeforeUnmount(() => {
  disposed = true
  labelTextureCache.clear()
  window.removeEventListener('resize', handleResize)
  try {
    graph?._destructor?.()
  } catch {
    // WebGL 上下文释放失败不阻断页面卸载
  }
  graph = null
})
</script>

<style scoped>
.explorer3d-wrap {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--nr-space-sm);
  height: 100%;
}

.explorer3d-toolbar {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm);
  /* 不随父级伸缩：高度自留，剩余全给画布；窄屏换行不挤压画布宽度。 */
  flex: none;
  flex-wrap: wrap;
}

.focus-input {
  max-width: 240px;
}

.hops-select {
  width: 76px;
}

.hop-label {
  opacity: 0.7;
  font-size: 12px;
}

.explorer3d-canvas {
  position: relative;
  /* 撑满 flex 父级剩余高度：全屏时父级长高画布跟随（修「只有上半屏」）；
     高度交给 flex 而非库内联内容，handleResize 才能量到真实新尺寸。 */
  flex: 1;
  width: 100%;
  min-height: 0;
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-md, 12px);
  /* 暗宇宙底色：与生物电信号配色一体化 */
  background: var(--nr-bg-inset);
  overflow: hidden;
}

.explorer3d-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
</style>
