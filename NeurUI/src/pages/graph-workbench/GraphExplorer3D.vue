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
      <GlassButton size="sm" :loading="loading" @click="refetch">
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
 * 3D 探索器（升级计划 S4）：`3d-force-graph` 动态 import 懒加载——
 * WebGL 与 three 系依赖不进主包，2D 视图不因此变重。
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

const currentNodeId = ref('')

const typeOptions = computed(() => {
  const kinds = new Set(rawNodes.map((n) => n.type).filter(Boolean))
  return Array.from(kinds).sort().map((k) => ({ value: k, label: k }))
})

// 渲染集按类型过滤：边只保留两端都可见的——带半截边就是"看不见的节点还在拉线"。
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

const refetch = async () => {
  if (!containerRef.value) return
  loading.value = true
  try {
    const params: Record<string, unknown> = { hops: hops.value, limit: 500 }
    if (currentNodeId.value || props.focusId || focusInput.value.trim()) {
      params.focus = currentNodeId.value || props.focusId || focusInput.value.trim()
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
}

let initPromise: Promise<void> | null = null
const _createGraph = async () => {
    const mod = await import('3d-force-graph')
    // v1.80 起是类构造 new ForceGraph3D(element)：旧版 Kapsule 双调用
    // ForceGraph3D()(el) 会把 class 当普通函数调，TypeError 后静默空白。
    const ForceGraph3D = (mod as any).default ?? mod
    if (!containerRef.value || disposed) return
    try {
      graph = new ForceGraph3D(containerRef.value)
        .backgroundColor('rgba(0,0,0,0)')
        .nodeLabel((node: any) => String(node?.name ?? node?.id ?? ''))
        .nodeColor((node: any) =>
          node?.id === currentNodeId.value ? '#f59e0b' : '#6366f1')
        .onNodeClick((node: any) => {
          currentNodeId.value = String(node?.id ?? '')
          emit('select', currentNodeId.value, String(node?.name ?? ''))
          if (graph) graph.nodeColor(graph.nodeColor())
        })
        // 点空白处回全图：聚焦视图的退出路径不能只靠找工具条按钮。
        .onBackgroundClick(() => resetToFull())
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
  void refetch()
}

const handleResize = () => {
  if (graph && containerRef.value) {
    graph.width(containerRef.value.clientWidth)
    graph.height(containerRef.value.clientHeight)
  }
}

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  await refetch()
  handleResize()
})

onBeforeUnmount(() => {
  disposed = true
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
  min-height: 420px;
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-md, 12px);
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
