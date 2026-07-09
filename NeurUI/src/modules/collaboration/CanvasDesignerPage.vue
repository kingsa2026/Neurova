<template>
  <!--
    CanvasDesignerPage.vue — 可视化画布设计器
    职责：可视化拖拽编排工作流节点 + 多 Agent 协作流程
    设计：三栏布局（左侧节点库 | 中间画布 | 右侧属性面板）

    当前为骨架版本，后续可集成 Vue Flow / reactflow 风格的节点画布。
    Infinite-Canvas 整合后可复用其画布组件。
  -->
  <div class="canvas-designer">
    <!-- 顶部工具栏 -->
    <div class="canvas-toolbar">
      <div class="toolbar-left">
        <GlassButton variant="ghost" size="sm" @click="$router.push('/collaboration/workflows')">
          <ArrowLeftOutlined /> {{ t('common.back') }}
        </GlassButton>
        <h3 class="canvas-title">
          {{ workflowName || t('collab.canvasNew') }}
        </h3>
      </div>
      <div class="toolbar-right">
        <GlassButton variant="ghost" size="sm" @click="handleSave">{{ t('common.save') }}</GlassButton>
        <GlassButton variant="primary" size="sm" @click="handleRun">{{ t('workflow.execute') }}</GlassButton>
      </div>
    </div>

    <!-- 三栏布局 -->
    <div class="canvas-body">
      <!-- 左侧：节点库 -->
      <aside class="canvas-sidebar canvas-palette">
        <h4 class="sidebar-title">{{ t('collab.nodeLibrary') }}</h4>
        <a-input-search v-model:value="nodeSearch" :placeholder="t('common.search')" size="small" style="margin-bottom: 12px" />

        <div class="palette-categories">
          <div v-for="cat in filteredCategories" :key="cat.name" class="palette-category">
            <div class="category-header" @click="toggleCategory(cat.name)">
              <component :is="cat.icon" />
              <span>{{ t(cat.labelKey) }}</span>
              <DownOutlined class="category-arrow" :class="{ expanded: expandedCategories.has(cat.name) }" />
            </div>
            <div v-show="expandedCategories.has(cat.name)" class="category-items">
              <div
                v-for="node in cat.nodes"
                :key="node.type"
                class="palette-node"
                draggable="true"
                @dragstart="handleDragStart($event, node)"
                @dblclick="addNodeToCanvas(node)"
              >
                <span class="node-icon">{{ node.icon }}</span>
                <span class="node-label">{{ node.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <!-- 中间：画布区域 -->
      <main
        class="canvas-main"
        ref="canvasRef"
        @dragover.prevent
        @drop="handleDrop"
      >
        <div v-if="canvasNodes.length === 0" class="canvas-empty">
          <BgColorsOutlined class="empty-icon" />
          <p>{{ t('collab.canvasEmpty') }}</p>
          <p class="empty-hint">{{ t('collab.canvasEmptyHint') }}</p>
        </div>

        <!-- 节点画布（简化版：绝对定位的节点卡片） -->
        <div v-else class="canvas-graph">
          <div
            v-for="node in canvasNodes"
            :key="node.id"
            class="graph-node"
            :class="{ selected: selectedNodeId === node.id }"
            :style="{ left: node.position.x + 'px', top: node.position.y + 'px' }"
            @mousedown="startDrag($event, node)"
            @click.stop="selectNode(node.id)"
          >
            <div class="graph-node-header">
              <span class="graph-node-icon">{{ node.icon }}</span>
              <span class="graph-node-title">{{ node.label }}</span>
            </div>
            <div class="graph-node-body">
              <div v-for="input in node.inputs" :key="input.id" class="port port-in">
                <span class="port-dot" />
                <span class="port-label">{{ input.label }}</span>
              </div>
              <div v-for="output in node.outputs" :key="output.id" class="port port-out">
                <span class="port-label">{{ output.label }}</span>
                <span class="port-dot" />
              </div>
            </div>
          </div>

          <!-- 连线层（SVG 占位，后续可替换为 Vue Flow） -->
          <svg class="canvas-edges" v-if="canvasEdges.length > 0">
            <line
              v-for="edge in canvasEdges"
              :key="edge.id"
              :x1="edge.x1" :y1="edge.y1"
              :x2="edge.x2" :y2="edge.y2"
              stroke="rgba(99, 102, 241, 0.5)"
              stroke-width="2"
            />
          </svg>
        </div>
      </main>

      <!-- 右侧：属性面板 -->
      <aside class="canvas-sidebar canvas-properties">
        <h4 class="sidebar-title">{{ t('collab.properties') }}</h4>
        <div v-if="!selectedNode" class="props-empty">
          <p>{{ t('collab.selectNode') }}</p>
        </div>
        <div v-else class="props-content">
          <div class="prop-group">
            <label>{{ t('common.name') }}</label>
            <a-input v-model:value="selectedNode.label" size="small" />
          </div>
          <div class="prop-group">
            <label>{{ t('common.type') }}</label>
            <a-input :value="selectedNode.type" size="small" disabled />
          </div>
          <div class="prop-group" v-for="(value, key) in selectedNode.config" :key="key">
            <label>{{ key }}</label>
            <a-input v-model:value="selectedNode.config[key]" size="small" />
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 画布设计器 — 可视化工作流编排
 *
 * 三栏布局：
 * - 左：节点库（按分类折叠，支持搜索 + 拖拽）
 * - 中：画布（节点卡片 + SVG 连线，支持拖拽移动）
 * - 右：属性面板（选中节点的配置编辑）
 *
 * 骨架版本：使用原生 HTML5 拖拽 + 绝对定位实现。
 * 后续可升级为 Vue Flow（@vue-flow/core）获得完整画布能力。
 *
 * 数据流：所有持久化通过 useCollaboration composable → store → api，页面不直接调用后端。
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeftOutlined, DownOutlined, BgColorsOutlined,
  ApartmentOutlined, RobotOutlined, BulbOutlined,
  ClockCircleOutlined, DatabaseOutlined,
} from '@ant-design/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { useCollaboration } from '@/composables/useCollaboration'
import type { CanvasNodeSnapshot, CanvasEdgeSnapshot } from '@/api/modules/collaboration'

const route = useRoute()
const { t } = useI18n()

// 节点库条目（UI 概念，非持久化类型）：含分类与默认配置，落到画布后转为 CanvasNodeSnapshot
interface PaletteNode {
  type: string
  label: string
  icon: string
  category: string
  inputs: { id: string; label: string }[]
  outputs: { id: string; label: string }[]
  defaultConfig: Record<string, unknown>
}

// ── 统一通过 composable 访问 store ──
// saveCanvas / runCanvas / loadCanvas 已封装 uiMessage 与错误处理
const { saveCanvas, runCanvas, loadCanvas } = useCollaboration()

const workflowName = ref('')
const canvasNodes = ref<CanvasNodeSnapshot[]>([])
const canvasEdges = ref<CanvasEdgeSnapshot[]>([])
const canvasId = ref<string | null>(null)
const selectedNodeId = ref<string | null>(null)
const nodeSearch = ref('')
const canvasRef = ref<HTMLElement>()

// 节点库分类
const paletteCategories = [
  {
    name: 'builtin',
    labelKey: 'collab.catBuiltin',
    icon: BulbOutlined,
    nodes: [
      { type: 'builtin:start', label: '开始', icon: '▶', category: 'builtin', inputs: [], outputs: [{ id: 'out', label: '输出' }], defaultConfig: {} },
      { type: 'builtin:end', label: '结束', icon: '⏹', category: 'builtin', inputs: [{ id: 'in', label: '输入' }], outputs: [], defaultConfig: {} },
      { type: 'builtin:llm', label: 'LLM 调用', icon: '🤖', category: 'builtin', inputs: [{ id: 'prompt', label: '提示词' }], outputs: [{ id: 'response', label: '响应' }], defaultConfig: { model: 'gpt-4' } },
      { type: 'builtin:agent', label: 'Agent 调用', icon: '🧠', category: 'builtin', inputs: [{ id: 'task', label: '任务' }], outputs: [{ id: 'result', label: '结果' }], defaultConfig: {} },
      { type: 'builtin:condition', label: '条件分支', icon: '❓', category: 'builtin', inputs: [{ id: 'in', label: '输入' }], outputs: [{ id: 'true', label: '真' }, { id: 'false', label: '假' }], defaultConfig: {} },
    ] as PaletteNode[],
  },
  {
    name: 'comfyui',
    labelKey: 'collab.catComfyui',
    icon: BgColorsOutlined,
    nodes: [
      { type: 'comfyui:KSampler', label: 'KSampler', icon: '🎨', category: 'comfyui', inputs: [{ id: 'model', label: '模型' }, { id: 'positive', label: '正向' }, { id: 'negative', label: '负向' }], outputs: [{ id: 'latent', label: '潜空间' }], defaultConfig: { seed: 42, steps: 20 } },
      { type: 'comfyui:VAEDecode', label: 'VAE 解码', icon: '🖼', category: 'comfyui', inputs: [{ id: 'samples', label: '采样' }, { id: 'vae', label: 'VAE' }], outputs: [{ id: 'image', label: '图像' }], defaultConfig: {} },
      { type: 'comfyui:CheckpointLoaderSimple', label: '模型加载', icon: '📦', category: 'comfyui', inputs: [], outputs: [{ id: 'model', label: '模型' }, { id: 'clip', label: 'CLIP' }, { id: 'vae', label: 'VAE' }], defaultConfig: { ckpt_name: 'model.safetensors' } },
    ] as PaletteNode[],
  },
  {
    name: 'data',
    labelKey: 'collab.catData',
    icon: DatabaseOutlined,
    nodes: [
      { type: 'builtin:memory-load', label: '记忆加载', icon: '💾', category: 'data', inputs: [], outputs: [{ id: 'memory', label: '记忆' }], defaultConfig: {} },
      { type: 'builtin:memory-save', label: '记忆保存', icon: '📝', category: 'data', inputs: [{ id: 'data', label: '数据' }], outputs: [], defaultConfig: {} },
    ] as PaletteNode[],
  },
]

const expandedCategories = reactive(new Set<string>(['builtin']))

function toggleCategory(name: string) {
  if (expandedCategories.has(name)) {
    expandedCategories.delete(name)
  } else {
    expandedCategories.add(name)
  }
}

const filteredCategories = computed(() => {
  if (!nodeSearch.value) return paletteCategories
  const q = nodeSearch.value.toLowerCase()
  return paletteCategories
    .map(cat => ({
      ...cat,
      nodes: cat.nodes.filter(n => n.label.toLowerCase().includes(q) || n.type.toLowerCase().includes(q)),
    }))
    .filter(cat => cat.nodes.length > 0)
})

// 节点拖拽
let dragCounter = 0

function handleDragStart(event: DragEvent, node: PaletteNode) {
  event.dataTransfer?.setData('application/json', JSON.stringify(node))
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  const data = event.dataTransfer?.getData('application/json')
  if (!data) return
  const paletteNode = JSON.parse(data) as PaletteNode
  const rect = canvasRef.value?.getBoundingClientRect()
  const x = event.clientX - (rect?.left ?? 0)
  const y = event.clientY - (rect?.top ?? 0)
  addNodeAt(paletteNode, x, y)
}

function addNodeToCanvas(node: PaletteNode) {
  addNodeAt(node, 100 + Math.random() * 200, 100 + Math.random() * 100)
}

function addNodeAt(paletteNode: PaletteNode, x: number, y: number) {
  dragCounter += 1
  const canvasNode: CanvasNodeSnapshot = {
    id: `node-${Date.now()}-${dragCounter}`,
    type: paletteNode.type,
    label: paletteNode.label,
    icon: paletteNode.icon,
    position: { x: Math.max(0, x - 60), y: Math.max(0, y - 20) },
    inputs: paletteNode.inputs,
    outputs: paletteNode.outputs,
    config: { ...paletteNode.defaultConfig },
  }
  canvasNodes.value.push(canvasNode)
  selectNode(canvasNode.id)
}

// 节点选中
const selectedNode = computed(() => canvasNodes.value.find(n => n.id === selectedNodeId.value) || null)

function selectNode(id: string) {
  selectedNodeId.value = id
}

// 节点拖拽移动
let draggingNode: CanvasNodeSnapshot | null = null
let dragOffset = { x: 0, y: 0 }

function startDrag(event: MouseEvent, node: CanvasNodeSnapshot) {
  draggingNode = node
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  dragOffset.x = event.clientX - rect.left
  dragOffset.y = event.clientY - rect.top

  const onMove = (e: MouseEvent) => {
    if (!draggingNode || !canvasRef.value) return
    const canvasRect = canvasRef.value.getBoundingClientRect()
    draggingNode.position.x = e.clientX - canvasRect.left - dragOffset.x
    draggingNode.position.y = e.clientY - canvasRect.top - dragOffset.y
  }

  const onUp = () => {
    draggingNode = null
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

// 工具栏操作 ── 通过 composable 落库，不再 console.log 占位
async function handleSave() {
  const name = workflowName.value || t('collab.canvasNew')
  const saved = await saveCanvas({
    id: canvasId.value ?? undefined,
    name,
    nodes: canvasNodes.value,
    edges: canvasEdges.value,
  })
  if (saved?.id) {
    canvasId.value = saved.id
    workflowName.value = saved.name
  }
}

async function handleRun() {
  // 没保存过则先保存，拿到 id 再执行
  if (!canvasId.value) {
    await handleSave()
    if (!canvasId.value) return
  }
  await runCanvas(canvasId.value)
}

// 初始化：如果 URL 有 :id 参数，加载已有工作流
onMounted(async () => {
  const workflowId = route.params.id as string | undefined
  if (!workflowId) {
    workflowName.value = ''
    return
  }
  const snapshot = await loadCanvas(workflowId)
  if (snapshot) {
    canvasId.value = snapshot.id ?? workflowId
    workflowName.value = snapshot.name
    canvasNodes.value = snapshot.nodes ?? []
    canvasEdges.value = snapshot.edges ?? []
  } else {
    workflowName.value = `工作流 ${workflowId}`
  }
})
</script>

<style scoped>
.canvas-designer { display: flex; flex-direction: column; height: calc(100vh - 64px); background: var(--nr-bg-primary, #0a0e1a); }

/* 工具栏 */
.canvas-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: rgba(255, 255, 255, 0.03); border-bottom: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08)); }
.toolbar-left { display: flex; align-items: center; gap: 12px; }
.canvas-title { color: var(--nr-text-primary); font-size: 15px; font-weight: 600; margin: 0; }
.toolbar-right { display: flex; gap: 8px; }

/* 三栏布局 */
.canvas-body { display: flex; flex: 1; overflow: hidden; }

/* 侧边栏通用 */
.canvas-sidebar { width: 240px; background: rgba(255, 255, 255, 0.02); border-right: 1px solid var(--nr-border, rgba(255, 255, 255, 0.06)); overflow-y: auto; padding: 12px; }
.canvas-properties { border-right: none; border-left: 1px solid var(--nr-border, rgba(255, 255, 255, 0.06)); }
.sidebar-title { color: var(--nr-text-primary); font-size: 13px; font-weight: 600; margin: 0 0 12px 0; text-transform: uppercase; letter-spacing: 0.5px; }

/* 节点库 */
.palette-categories { display: flex; flex-direction: column; gap: 8px; }
.palette-category { }
.category-header { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; color: var(--nr-text-secondary); font-size: 12px; font-weight: 600; }
.category-header:hover { background: rgba(255, 255, 255, 0.04); }
.category-arrow { font-size: 9px; transition: transform 0.2s; }
.category-arrow.expanded { transform: rotate(180deg); }
.category-items { display: flex; flex-direction: column; gap: 4px; padding: 4px 0 4px 12px; }
.palette-node { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 6px; background: rgba(255, 255, 255, 0.03); cursor: grab; transition: all 0.15s; }
.palette-node:hover { background: rgba(99, 102, 241, 0.1); }
.palette-node:active { cursor: grabbing; }
.node-icon { font-size: 14px; }
.node-label { color: var(--nr-text-secondary); font-size: 12px; }

/* 画布主区域 */
.canvas-main { flex: 1; position: relative; overflow: hidden; background-image: radial-gradient(circle, rgba(255, 255, 255, 0.04) 1px, transparent 1px); background-size: 20px 20px; }
.canvas-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: var(--nr-text-tertiary); gap: 8px; }
.empty-icon { font-size: 48px; opacity: 0.3; }
.canvas-empty p { margin: 0; font-size: 14px; }
.empty-hint { font-size: 12px !important; opacity: 0.6; }

.canvas-graph { position: relative; width: 100%; height: 100%; }
.canvas-edges { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }

/* 画布节点 */
.graph-node { position: absolute; min-width: 140px; background: rgba(20, 25, 40, 0.95); border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.1)); border-radius: 10px; cursor: move; user-select: none; transition: border-color 0.15s; }
.graph-node:hover { border-color: rgba(99, 102, 241, 0.3); }
.graph-node.selected { border-color: var(--nr-primary-light, #818cf8); box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2); }
.graph-node-header { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.graph-node-icon { font-size: 14px; }
.graph-node-title { color: var(--nr-text-primary); font-size: 12px; font-weight: 600; }
.graph-node-body { padding: 6px 10px; display: flex; flex-direction: column; gap: 4px; }
.port { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--nr-text-tertiary); }
.port-in { justify-content: flex-start; }
.port-out { justify-content: flex-end; }
.port-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--nr-primary-light, #818cf8); }

/* 属性面板 */
.props-empty { display: flex; align-items: center; justify-content: center; height: 100px; color: var(--nr-text-tertiary); font-size: 12px; }
.props-content { display: flex; flex-direction: column; gap: 12px; }
.prop-group { display: flex; flex-direction: column; gap: 4px; }
.prop-group label { color: var(--nr-text-tertiary); font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
</style>
