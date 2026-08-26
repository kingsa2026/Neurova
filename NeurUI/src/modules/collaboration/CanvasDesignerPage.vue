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
        <a-dropdown :trigger="['click']" @open-change="onMyCanvasOpen">
          <GlassButton variant="ghost" size="sm">
            {{ t('collab.myCanvases') }} <DownOutlined />
          </GlassButton>
          <template #overlay>
            <a-menu>
              <a-menu-item v-for="c in savedCanvases" :key="c.id" @click="openSavedCanvas(c.id)">
                <div class="my-canvas-item">
                  <span class="my-canvas-name">{{ c.name || c.id }}</span>
                  <span class="my-canvas-meta">{{ c.node_count }} 节点 · {{ formatTime(c.updated_at) }}</span>
                </div>
              </a-menu-item>
              <a-menu-item v-if="savedCanvases.length === 0" disabled key="empty">
                {{ t('common.noData') }}
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
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
        :style="gridStyle"
        @dragover.prevent
        @drop="handleDrop"
        @wheel="onWheel"
        @contextmenu.prevent="openCanvasMenu($event, 'blank')"
        @mousedown.self="onCanvasBlankMousedown"
      >
        <div v-if="canvasNodes.length === 0" class="canvas-empty">
          <BgColorsOutlined class="empty-icon" />
          <p>{{ t('collab.canvasEmpty') }}</p>
          <p class="empty-hint">{{ t('collab.canvasEmptyHint') }}</p>
        </div>

        <!-- 节点画布：viewport 变换实现无限画布（平移+缩放） -->
        <div
          v-else
          class="canvas-graph"
          :style="graphStyle"
          @mousedown.self="onCanvasBlankMousedown"
        >
          <div
            v-for="node in canvasNodes"
            :key="node.id"
            class="graph-node"
            :class="{
              selected: selectedNodeId === node.id,
              'run-success': runStatus[node.id]?.status === 'success',
              'run-failed': runStatus[node.id]?.status === 'failed',
              'run-skipped': runStatus[node.id]?.status === 'skipped',
              'run-running': runStatus[node.id]?.status === 'running',
            }"
            :style="{ left: node.position.x + 'px', top: node.position.y + 'px' }"
            :data-node-id="node.id"
            @mousedown="startDrag($event, node)"
            @click.stop="selectNode(node.id)"
          >
            <div class="graph-node-header">
              <span class="graph-node-icon">{{ node.icon }}</span>
              <span class="graph-node-title">{{ node.label }}</span>
              <button
                class="node-delete"
                title="删除节点"
                @mousedown.stop
                @click.stop="removeNode(node.id)"
              >×</button>
            </div>
            <div class="graph-node-body">
              <div v-for="input in node.inputs" :key="input.id" class="port port-in">
                <span
                  class="port-dot port-dot-in"
                  data-port-kind="in"
                  :data-node-id="node.id"
                  :data-port-id="input.id"
                  :title="`接入：${input.label}`"
                />
                <span class="port-label">{{ input.label }}</span>
              </div>
              <div v-for="output in node.outputs" :key="output.id" class="port port-out">
                <span class="port-label">{{ output.label }}</span>
                <span
                  class="port-dot port-dot-out"
                  data-port-kind="out"
                  :data-node-id="node.id"
                  :data-port-id="output.id"
                  :title="`拖拽连线：${output.label}`"
                  @mousedown.stop.prevent="startConnect($event, node.id, output.id)"
                />
              </div>
            </div>
          </div>

          <!-- 连线层：语义边（source/target 端口引用）+ 拖拽预览，贝塞尔曲线自适应 -->
          <svg class="canvas-edges">
            <g v-for="edge in canvasEdges" :key="edge.id" class="edge-group">
              <!-- 加粗透明命中路径：便于点选/右键 -->
              <path
                class="edge-hit"
                :d="edgePath(edge)"
                @click.stop="selectEdge(edge.id)"
                @dblclick.stop="removeEdge(edge.id)"
                @contextmenu.stop.prevent="openCanvasMenu($event, 'edge', edge.id)"
              />
              <path
                class="edge-line"
                :class="{ selected: selectedEdgeId === edge.id }"
                :d="edgePath(edge)"
              />
            </g>
            <!-- 拖拽中的预览曲线 -->
            <path v-if="connecting" class="edge-preview" :d="previewPath" />
          </svg>

          <!-- 缩放控制栏 -->
          <div class="canvas-zoombar">
            <button class="zoom-btn" title="缩小 (Ctrl+-)" @click="zoomOut">−</button>
            <span
              class="zoom-value"
              title="重置视图 (Ctrl+0)"
              @click="resetView"
            >{{ Math.round(viewport.zoom * 100) }}%</span>
            <button class="zoom-btn" title="放大 (Ctrl+=)" @click="zoomIn">＋</button>
            <span class="zoom-divider" />
            <button class="zoom-btn zoom-fit" title="适应内容" @click="fitView">⤢</button>
          </div>

          <p v-if="canvasNodes.length > 0" class="connect-hint">
            从节点右侧 ● 拖到另一节点左侧 ● 完成连线 · 单击选中连线 Delete 删除 · 右键空白/节点/连线有菜单 · Ctrl+滚轮缩放
          </p>
        </div>
      </main>

      <!-- 右侧：属性面板 -->
      <aside class="canvas-sidebar canvas-properties">
        <h4 class="sidebar-title">{{ t('collab.properties') }}</h4>        <div v-if="!selectedNode" class="props-empty">
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

          <!-- Agent 节点专用表单（蜂群编排：绑定真实子 Agent + 任务） -->
          <template v-if="selectedNode.type === 'builtin:agent'">
            <div class="prop-group">
              <label>执行 Agent</label>
              <a-select
                v-model:value="selectedNode.config.agent_id"
                :options="agentOptions"
                size="small"
                allow-clear
                show-search
                option-filter-prop="label"
                placeholder="选择子 Agent（留空用默认）"
              />
            </div>
            <div class="prop-group">
              <label>任务描述</label>
              <a-textarea
                v-model:value="selectedNode.config.task"
                :rows="4"
                size="small"
                placeholder="子 Agent 的任务描述（需自包含；可用 ${上游节点ID.output} 引用上游输出）"
              />
            </div>
          </template>

          <!-- 通用配置表单：按节点定义 sub_blocks 渲染（textarea/select/model-selector/input） -->
          <div class="prop-group" v-for="field in configFields" :key="field.key">
            <label>{{ field.title }}</label>
            <a-textarea
              v-if="field.type === 'textarea'"
              v-model:value="selectedNode.config[field.key]"
              :rows="3"
              size="small"
            />
            <template v-else-if="field.type === 'model-selector'">
              <a-select
                :value="selectedNode.config.model_name || undefined"
                :options="modelOptions"
                size="small"
                allow-clear
                show-search
                option-filter-prop="label"
                placeholder="选择可联通模型（留空用默认）"
                @change="handleModelSelect"
              />
              <a-select
                v-model:value="selectedNode.config.model_provider"
                :options="providerOptions"
                size="small"
                style="margin-top: 6px"
                placeholder="Provider（选模型后自动回填）"
              />
            </template>
            <a-select
              v-else-if="field.type === 'select'"
              v-model:value="selectedNode.config[field.key]"
              :options="field.options"
              size="small"
            />
            <a-input v-else v-model:value="selectedNode.config[field.key]" size="small" />
          </div>

          <!-- 执行结果查看 -->
          <div class="prop-group" v-if="runStatus[selectedNode.id]">
            <label>执行结果（{{ runStatus[selectedNode.id]?.status }}）</label>
            <pre class="node-output-view">{{ formatNodeOutput(runStatus[selectedNode.id]) }}</pre>
          </div>
        </div>
      </aside>
    </div>

    <!-- 画布右键菜单 -->
    <Teleport to="body">
      <div
        v-if="ctxMenu.open"
        class="canvas-ctx-menu"
        :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      >
        <template v-if="ctxMenu.kind === 'node'">
          <button class="ctx-item danger" @click="ctxDeleteNode">🗑 删除节点</button>
          <button class="ctx-item" @click="ctxDuplicateNode">⧉ 复制节点</button>
        </template>
        <template v-else-if="ctxMenu.kind === 'edge'">
          <button class="ctx-item danger" @click="ctxDeleteEdge">✕ 删除连线</button>
        </template>
        <template v-else>
          <button class="ctx-item" @click="ctxAddNode">＋ 新建 LLM 节点</button>
        </template>
        <div class="ctx-sep" />
        <button class="ctx-item" @click="ctxZoomIn">🔍 放大</button>
        <button class="ctx-item" @click="ctxZoomOut">🔍 缩小</button>
        <button class="ctx-item" @click="ctxResetView">⌖ 重置视图 (100%)</button>
      </div>
    </Teleport>
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
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeftOutlined, DownOutlined, BgColorsOutlined,
  ApartmentOutlined, RobotOutlined, BulbOutlined,
  ClockCircleOutlined, DatabaseOutlined, FileOutlined,
} from '@ant-design/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { useCollaboration } from '@/composables/useCollaboration'
import { useAgentStore } from '@/stores/agents'
import { getNodes } from '@/api/modules/neurflow'
import { useReachableModels, buildModelOptions } from '@/composables/useReachableModels'
import { runCanvas as runCanvasApi, getCanvasRun, type CanvasRunStatus } from '@/api/modules/collaboration'
import type { CanvasNodeSnapshot, CanvasEdgeSnapshot } from '@/api/modules/collaboration'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// 节点库条目（UI 概念，非持久化类型）：含分类与默认配置，落到画布后转为 CanvasNodeSnapshot
/** 配置字段定义（镜像后端 NodeDefinition.sub_blocks） */
interface SubBlockOption {
  label: string
  value: string
}
interface SubBlockDef {
  id: string
  title?: string
  type?: string // input | textarea | select | slider | model-selector
  options?: SubBlockOption[]
  default_value?: unknown
  required?: boolean
}
interface PaletteNode {
  type: string
  label: string
  icon: string
  category: string
  inputs: { id: string; label: string }[]
  outputs: { id: string; label: string }[]
  defaultConfig: Record<string, unknown>
  subBlocks?: SubBlockDef[]
}

// ── 统一通过 composable 访问 store ──
// saveCanvas / runCanvas / loadCanvas 已封装 uiMessage 与错误处理
const { saveCanvas, runCanvas, loadCanvas, listSavedCanvases } = useCollaboration()

// ── 我的画布：已保存画布列表（下拉懒加载） ──
const savedCanvases = ref<{ id: string; name: string; node_count: number; updated_at?: number }[]>([])
async function onMyCanvasOpen(open: boolean) {
  if (!open) return
  savedCanvases.value = await listSavedCanvases()
}
function openSavedCanvas(id: string) {
  router.push(`/collaboration/canvas/${id}`)
}
function formatTime(ts?: number) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const workflowName = ref('')
const canvasNodes = ref<CanvasNodeSnapshot[]>([])
const canvasEdges = ref<CanvasEdgeSnapshot[]>([])
const canvasId = ref<string | null>(null)
const selectedNodeId = ref<string | null>(null)
const nodeSearch = ref('')
const canvasRef = ref<HTMLElement>()

// ── 蜂群/编排：Agent 选择 + 执行状态可视化 ──
const agentStore = useAgentStore()
const agentOptions = computed(() => agentStore.agentOptions)
/** 节点执行状态（nodeId → 状态+输出），来自画布运行轮询 */
const runStatus = ref<Record<string, { status: string; output?: unknown; error?: string | null }>>({})
const runState = ref<'idle' | 'running' | 'completed' | 'failed'>('idle')
/** 动态节点库（/neurflow/nodes 拉取，含 tool/skill/mcp/comfyui 全量注册类型） */
const dynamicNodes = ref<PaletteNode[]>([])

// ── 无限画布视口（平移 + 缩放）──
// 所有节点/连线坐标均为「画布坐标系」；屏幕坐标经 screenToCanvas 换算
const viewport = reactive({ zoom: 1, panX: 0, panY: 0 })
const ZOOM_MIN = 0.25
const ZOOM_MAX = 3

function clampZoom(z: number) {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z))
}

/** 屏幕（客户区）坐标 → 画布坐标 */
function screenToCanvas(clientX: number, clientY: number): { x: number; y: number } {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return { x: 0, y: 0 }
  return {
    x: (clientX - rect.left - viewport.panX) / viewport.zoom,
    y: (clientY - rect.top - viewport.panY) / viewport.zoom,
  }
}

/** 以某屏幕点为锚缩放（锚点下的画布内容保持不动） */
function zoomAt(factor: number, clientX?: number, clientY?: number) {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  const ax = clientX ?? rect.left + rect.width / 2
  const ay = clientY ?? rect.top + rect.height / 2
  const old = viewport.zoom
  const nz = clampZoom(old * factor)
  if (nz === old) return
  viewport.panX = ax - rect.left - ((ax - rect.left - viewport.panX) / old) * nz
  viewport.panY = ay - rect.top - ((ay - rect.top - viewport.panY) / old) * nz
  viewport.zoom = nz
}

function zoomIn() { zoomAt(1.2) }
function zoomOut() { zoomAt(1 / 1.2) }
function resetView() { viewport.zoom = 1; viewport.panX = 0; viewport.panY = 0 }

/** 适应内容：让全部节点落入视野 */
function fitView() {
  if (!canvasNodes.value.length) { resetView(); return }
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of canvasNodes.value) {
    minX = Math.min(minX, n.position.x)
    minY = Math.min(minY, n.position.y)
    maxX = Math.max(maxX, n.position.x + 200)
    maxY = Math.max(maxY, n.position.y + 140)
  }
  const pad = 50
  const w = Math.max(1, maxX - minX)
  const h = Math.max(1, maxY - minY)
  const z = clampZoom(Math.min((rect.width - pad * 2) / w, (rect.height - pad * 2) / h))
  viewport.zoom = z
  viewport.panX = (rect.width - w * z) / 2 - minX * z
  viewport.panY = (rect.height - h * z) / 2 - minY * z
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  if (e.ctrlKey || e.metaKey) {
    zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY)
  } else {
    // 平移；Shift+滚轮切横向
    const dx = e.shiftKey ? e.deltaY : e.deltaX
    const dy = e.shiftKey ? 0 : e.deltaY
    viewport.panX -= dx
    viewport.panY -= dy
  }
}

const graphStyle = computed(() => ({
  transform: `translate(${viewport.panX}px, ${viewport.panY}px) scale(${viewport.zoom})`,
  transformOrigin: '0 0',
}))

/** 网格底纹：随缩放改变格子尺寸、随平移移动相位 */
const gridStyle = computed(() => ({
  backgroundImage:
    'linear-gradient(to right, rgba(148, 163, 184, 0.14) 1px, transparent 1px),' +
    'linear-gradient(to bottom, rgba(148, 163, 184, 0.14) 1px, transparent 1px)',
  backgroundSize: `${24 * viewport.zoom}px ${24 * viewport.zoom}px`,
  backgroundPosition: `${viewport.panX}px ${viewport.panY}px`,
}))

// ── 贝塞尔曲线连线路径 ──
function bezierD(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.abs(x2 - x1)
  const k = Math.min(160, Math.max(30, dx * 0.55))
  return `M ${x1} ${y1} C ${x1 + k} ${y1}, ${x2 - k} ${y2}, ${x2} ${y2}`
}

function edgePath(edge: CanvasEdgeSnapshot): string {
  return bezierD(edge.x1, edge.y1, edge.x2, edge.y2)
}

const previewPath = computed(() =>
  connecting.value
    ? bezierD(connecting.value.x1, connecting.value.y1, connecting.value.x2, connecting.value.y2)
    : ''
)

// ── 右键菜单 ──
const ctxMenu = reactive({
  open: false,
  x: 0,
  y: 0,
  kind: 'blank' as 'blank' | 'node' | 'edge',
  id: null as string | null,
})

function openCanvasMenu(e: MouseEvent, kind: 'blank' | 'node' | 'edge', id?: string) {
  if (kind === 'node' && id) selectNode(id)
  if (kind === 'edge' && id) selectEdge(id)
  ctxMenu.open = true
  ctxMenu.kind = kind
  ctxMenu.id = id ?? null
  // 贴边防溢出
  const mw = 190, mh = 220
  ctxMenu.x = Math.min(e.clientX, window.innerWidth - mw - 8)
  ctxMenu.y = Math.min(e.clientY, window.innerHeight - mh - 8)
}

function closeCtxMenu() {
  ctxMenu.open = false
}

function onDocMousedownClose(e: MouseEvent) {
  if (!ctxMenu.open) return
  const el = e.target as HTMLElement | null
  if (el?.closest('.canvas-ctx-menu')) return
  closeCtxMenu()
}

function ctxAddNode() {
  const def = paletteCategories
    .flatMap(c => c.nodes)
    .find(n => n.type === 'builtin:llm')
  if (def) {
    const p = screenToCanvas(ctxMenu.x, ctxMenu.y)
    addNodeAt(def, p.x, p.y)
  }
  closeCtxMenu()
}

function ctxDeleteNode() {
  if (ctxMenu.id) removeNode(ctxMenu.id)
  closeCtxMenu()
}

function ctxDuplicateNode() {
  const node = canvasNodes.value.find(n => n.id === ctxMenu.id)
  if (!node) { closeCtxMenu(); return }
  dragCounter += 1
  const copy: CanvasNodeSnapshot = JSON.parse(JSON.stringify(node))
  copy.id = `node-${Date.now()}-${dragCounter}`
  copy.position = { x: node.position.x + 28, y: node.position.y + 28 }
  canvasNodes.value.push(copy)
  selectNode(copy.id)
  closeCtxMenu()
}

function ctxDeleteEdge() {
  if (ctxMenu.id) removeEdge(ctxMenu.id)
  closeCtxMenu()
}

function ctxZoomIn() { zoomIn(); closeCtxMenu() }
function ctxZoomOut() { zoomOut(); closeCtxMenu() }
function ctxResetView() { resetView(); closeCtxMenu() }

// 节点库分类
const paletteCategories = [
  {
    name: 'builtin',
    labelKey: 'collab.catBuiltin',
    icon: BulbOutlined,
    nodes: [
      { type: 'builtin:start', label: '开始', icon: '▶', category: 'builtin', inputs: [], outputs: [{ id: 'out', label: '输出' }], defaultConfig: {} },
      { type: 'builtin:end', label: '结束', icon: '⏹', category: 'builtin', inputs: [{ id: 'in', label: '输入' }], outputs: [], defaultConfig: {} },
      { type: 'builtin:llm', label: 'LLM 调用', icon: '🤖', category: 'builtin', inputs: [{ id: 'input', label: '输入' }], outputs: [{ id: 'output', label: '输出' }, { id: 'usage', label: 'Token 用量' }], defaultConfig: { prompt: '', model_provider: 'auto', model_name: '', temperature: 0.7, max_tokens: 4096, system_prompt: '' }, subBlocks: [
        { id: 'prompt', title: '提示词', type: 'textarea' },
        { id: 'model_provider', title: '模型提供商', type: 'select', default_value: 'auto', options: [{ label: '自动选择', value: 'auto' }] },
        { id: 'model_name', title: '模型名称', type: 'model-selector' },
        { id: 'temperature', title: '温度', type: 'slider', default_value: 0.7, min: 0, max: 2 },
        { id: 'max_tokens', title: '最大 Tokens', type: 'slider', default_value: 4096, min: 100, max: 128000 },
        { id: 'system_prompt', title: '系统提示', type: 'textarea' },
      ] },
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
  {
    name: 'input',
    labelKey: 'collab.catInput',
    icon: FileOutlined,
    nodes: [
      {
        type: 'builtin:text_input',
        label: '文本输入',
        icon: '📝',
        category: 'input',
        inputs: [],
        outputs: [{ id: 'text', label: '文本' }],
        defaultConfig: { value: '' },
        subBlocks: [
          { id: 'value', title: '文本内容（支持 ${上游节点ID.output} 引用）', type: 'textarea' },
        ],
      },
      {
        type: 'builtin:media_input',
        label: '媒体输入',
        icon: '🖼️',
        category: 'input',
        inputs: [],
        outputs: [{ id: 'media', label: '媒体' }],
        defaultConfig: { media_type: 'file', source: 'url', value: '' },
        subBlocks: [
          { id: 'media_type', title: '媒体类型', type: 'select', default_value: 'file', options: [
            { label: '图片', value: 'image' },
            { label: '音频', value: 'audio' },
            { label: '视频', value: 'video' },
            { label: '文件', value: 'file' },
          ] },
          { id: 'source', title: '来源格式', type: 'select', default_value: 'url', options: [
            { label: 'URL', value: 'url' },
            { label: 'Data URL', value: 'data-url' },
            { label: 'Base64', value: 'base64' },
          ] },
          { id: 'value', title: '载荷值（URL / data-url / base64，不内联二进制）', type: 'textarea' },
        ],
      },
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
  // 静态分类 + 动态节点库（/neurflow/nodes：tool/skill/mcp/comfyui 等注册类型）
  const staticTypes = new Set(paletteCategories.flatMap(c => c.nodes.map(n => n.type)))
  const dynamicByCategory = new Map<string, PaletteNode[]>()
  for (const dn of dynamicNodes.value) {
    if (staticTypes.has(dn.type)) continue
    const list = dynamicByCategory.get(dn.category) ?? []
    list.push(dn)
    dynamicByCategory.set(dn.category, list)
  }
  const dynamicCategories = [...dynamicByCategory.entries()].map(([category, nodes]) => ({
    name: category,
    icon: ApartmentOutlined,
    labelKey: category,
    nodes,
  }))
  const allCategories = [...paletteCategories, ...dynamicCategories]

  if (!nodeSearch.value) return allCategories
  const q = nodeSearch.value.toLowerCase()
  return allCategories
    .map(cat => ({
      ...cat,
      nodes: cat.nodes.filter(n => n.label.toLowerCase().includes(q) || n.type.toLowerCase().includes(q)),
    }))
    .filter(cat => cat.nodes.length > 0)
})

/** 从 /neurflow/nodes 拉取动态节点库（失败时保留静态节点库） */
async function loadDynamicNodes() {
  try {
    const res = await getNodes()
    const items = (res?.data?.nodes ?? []) as Array<{
      type: string
      label: string
      icon?: string
      category?: string
      inputs?: { id: string; label: string }[]
      outputs?: { id: string; label: string }[]
      sub_blocks?: SubBlockDef[]
    }>
    dynamicNodes.value = items
      .filter(n => !String(n.type).startsWith('builtin:'))
      .map(n => ({
        type: n.type,
        label: n.label,
        icon: n.icon || '🧩',
        category: n.category || 'extensions',
        inputs: n.inputs ?? [],
        outputs: n.outputs ?? [],
        defaultConfig: Object.fromEntries(
          (n.sub_blocks ?? []).map(b => [b.id, b.default_value ?? '']),
        ),
        subBlocks: n.sub_blocks ?? [],
      }))
  } catch {
    // 动态节点库不可用时静默降级为静态节点库
  }
}

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
  const p = screenToCanvas(event.clientX, event.clientY)
  addNodeAt(paletteNode, p.x, p.y)
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

// ── 可联通模型下拉（builtin:llm 的 model-selector 数据源，惰性加载） ──
const { models: reachableModels, load: loadReachableModels } = useReachableModels()
const modelOptions = computed(() => buildModelOptions(reachableModels.value))
const providerOptions = computed(() => {
  const providers = new Set(reachableModels.value.filter(m => m.enabled !== false).map(m => m.provider_id))
  return [{ label: '自动选择', value: 'auto' }, ...[...providers].map(p => ({ label: p, value: p }))]
})
function handleModelSelect(value: unknown) {
  const node = selectedNode.value
  if (!node) return
  if (!value) {
    node.config.model_name = ''
    return
  }
  node.config.model_name = value
  // 选模型自动回填 provider（与 model_provider 字段联动）
  const hit = reachableModels.value.find(m => m.id === value)
  if (hit?.provider_id) node.config.model_provider = hit.provider_id
}

/** 属性面板配置字段：优先取节点定义 sub_blocks；无定义时回退为普通输入框 */
const configFields = computed(() => {
  const node = selectedNode.value
  if (!node) return []
  const def = paletteCategories
    .flatMap(c => c.nodes)
    .concat(dynamicNodes.value)
    .find(n => n.type === node.type)
  const blocks = def?.subBlocks ?? []
  if (blocks.length > 0) {
    return blocks.map(b => ({
      key: b.id,
      title: b.title || b.id,
      type: b.type || 'input',
      options: (b.options ?? []).map(o => ({ label: o.label, value: o.value })),
      min: undefined as number | undefined,
      max: undefined as number | undefined,
    }))
  }
  // 回退：遍历现有 config 键（旧快照/未知类型兼容）
  return Object.keys(node.config).map(k => ({ key: k, title: k, type: 'input', options: [] as { label: string; value: string }[], min: undefined, max: undefined }))
})

// 选中 LLM 节点时惰性拉取模型列表
watch(
  () => selectedNode.value?.type,
  (type) => {
    if (type === 'builtin:llm') void loadReachableModels()
  },
  { immediate: true },
)

function formatNodeOutput(status: { status: string; output?: unknown; error?: string | null }): string {
  if (status.error) return `错误: ${status.error}`
  const out = status.output
  if (out === null || out === undefined) return '（无输出）'
  return typeof out === 'string' ? out : JSON.stringify(out, null, 2)
}

function selectNode(id: string) {
  selectedNodeId.value = id
}

// 节点拖拽移动（相连边随节点同步平移）
let draggingNode: CanvasNodeSnapshot | null = null
let dragOffset = { x: 0, y: 0 }
// 拖拽起点快照：屏幕锚点、节点原位置、相连边的原端点坐标（画布坐标系）
let dragBase: {
  sx: number
  sy: number
  nx: number
  ny: number
  edges: { id: string; x1: number; y1: number; x2: number; y2: number }[]
} | null = null

function edgesAttachedTo(nodeId: string) {
  return canvasEdges.value.filter(
    e => e.source?.nodeId === nodeId || e.target?.nodeId === nodeId
  )
}

/** 删除节点及其所有连线 */
function removeNode(id: string) {
  canvasNodes.value = canvasNodes.value.filter(n => n.id !== id)
  canvasEdges.value = canvasEdges.value.filter(
    e => e.source?.nodeId !== id && e.target?.nodeId !== id
  )
  if (selectedNodeId.value === id) selectedNodeId.value = null
}

function startDrag(event: MouseEvent, node: CanvasNodeSnapshot) {
  // 点在端口/删除按钮上时由它们自己的 handler 接管（已 .stop）
  draggingNode = node
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  dragOffset.x = event.clientX - rect.left
  dragOffset.y = event.clientY - rect.top

  dragBase = {
    sx: event.clientX,
    sy: event.clientY,
    nx: node.position.x,
    ny: node.position.y,
    edges: edgesAttachedTo(node.id).map(e => ({
      id: e.id, x1: e.x1, y1: e.y1, x2: e.x2, y2: e.y2,
    })),
  }

  const onMove = (e: MouseEvent) => {
    if (!draggingNode || !dragBase) return
    // 屏幕位移除以缩放 = 画布坐标位移
    const dx = (e.clientX - dragBase.sx) / viewport.zoom
    const dy = (e.clientY - dragBase.sy) / viewport.zoom
    draggingNode.position.x = Math.max(0, dragBase.nx + dx)
    draggingNode.position.y = Math.max(0, dragBase.ny + dy)
    for (const base of dragBase.edges) {
      const edge = canvasEdges.value.find(ed => ed.id === base.id)
      if (!edge) continue
      if (edge.source?.nodeId === draggingNode.id) { edge.x1 = base.x1 + dx; edge.y1 = base.y1 + dy }
      if (edge.target?.nodeId === draggingNode.id) { edge.x2 = base.x2 + dx; edge.y2 = base.y2 + dy }
    }
  }

  const onUp = () => {
    draggingNode = null
    dragBase = null
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

// ── 端口连线 ────────────────────────────────────────────────────
interface ConnectingState {
  fromNodeId: string
  fromPortId: string
  x1: number
  y1: number
  x2: number
  y2: number
}
const connecting = ref<ConnectingState | null>(null)
const selectedEdgeId = ref<string | null>(null)

/** 取端口圆点中心相对于画布的坐标（画布坐标系，已含缩放/平移换算） */
function getPortCenter(nodeId: string, portId: string): { x: number; y: number } | null {
  const rect = canvasRef.value?.getBoundingClientRect()
  if (!rect) return null
  const dot = canvasRef.value?.querySelector(
    `.graph-node[data-node-id="${CSS.escape(nodeId)}"] .port-dot[data-port-id="${CSS.escape(portId)}"]`
  ) as HTMLElement | null
  if (!dot) return null
  const r = dot.getBoundingClientRect()
  return {
    x: (r.left + r.width / 2 - rect.left - viewport.panX) / viewport.zoom,
    y: (r.top + r.height / 2 - rect.top - viewport.panY) / viewport.zoom,
  }
}

function startConnect(event: MouseEvent, nodeId: string, portId: string) {
  const p = getPortCenter(nodeId, portId)
  if (!p) return
  connecting.value = {
    fromNodeId: nodeId, fromPortId: portId,
    x1: p.x, y1: p.y, x2: p.x, y2: p.y,
  }
  selectedEdgeId.value = null

  const onMove = (e: MouseEvent) => {
    if (!connecting.value) return
    const p2 = screenToCanvas(e.clientX, e.clientY)
    connecting.value.x2 = p2.x
    connecting.value.y2 = p2.y
  }

  const onUp = (e: MouseEvent) => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    if (!connecting.value) return
    // 命中检测：松手位置是否落在某个输入端口上
    const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null
    const targetDot = el?.closest('[data-port-kind="in"]') as HTMLElement | null
    const toNodeId = targetDot?.dataset.nodeId
    const toPortId = targetDot?.dataset.portId
    if (toNodeId && toPortId) {
      completeConnection(toNodeId, toPortId)
    }
    connecting.value = null
  }

  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function completeConnection(toNodeId: string, toPortId: string) {
  const st = connecting.value
  if (!st) return
  // 校验：不能连自己；不能重复同源同汇
  if (st.fromNodeId === toNodeId) {
    return
  }
  const duplicated = canvasEdges.value.some(
    e => e.source?.nodeId === st.fromNodeId && e.source?.portId === st.fromPortId &&
         e.target?.nodeId === toNodeId && e.target?.portId === toPortId
  )
  if (duplicated) return

  const p2 = getPortCenter(toNodeId, toPortId)
  canvasEdges.value.push({
    id: `edge-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    source: { nodeId: st.fromNodeId, portId: st.fromPortId },
    target: { nodeId: toNodeId, portId: toPortId },
    x1: st.x1, y1: st.y1,
    x2: p2?.x ?? st.x2, y2: p2?.y ?? st.y2,
  })
}

// ── 连线选中与删除 ──────────────────────────────────────────────
function selectEdge(id: string) {
  selectedEdgeId.value = id
  selectedNodeId.value = null
}

function removeEdge(id: string) {
  canvasEdges.value = canvasEdges.value.filter(e => e.id !== id)
  if (selectedEdgeId.value === id) selectedEdgeId.value = null
}

function onKeyDown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return

  // Esc：关闭菜单/清除选中
  if (e.key === 'Escape') {
    closeCtxMenu()
    selectedEdgeId.value = null
    selectedNodeId.value = null
    return
  }

  // Ctrl/Cmd + =/-/0 缩放快捷键
  if (e.ctrlKey || e.metaKey) {
    if (e.key === '=' || e.key === '+') { e.preventDefault(); zoomIn(); return }
    if (e.key === '-') { e.preventDefault(); zoomOut(); return }
    if (e.key === '0') { e.preventDefault(); resetView(); return }
  }

  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (selectedEdgeId.value) {
      removeEdge(selectedEdgeId.value)
    } else if (selectedNodeId.value) {
      removeNode(selectedNodeId.value)
    }
  }
}

function onCanvasBlankMousedown() {
  closeCtxMenu()
  selectedEdgeId.value = null
  selectedNodeId.value = null
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
    const isNew = !canvasId.value
    canvasId.value = saved.id
    workflowName.value = saved.name
    // 新画布首次保存后把 id 写进 URL：刷新/重开不丢（路由 :id 分支负责恢复）
    if (isNew && route.params.id !== saved.id) {
      router.replace(`/collaboration/canvas/${saved.id}`)
    }
  }
}

async function handleRun() {
  // 没保存过则先保存，拿到 id 再执行
  if (!canvasId.value) {
    await handleSave()
    if (!canvasId.value) return
  }
  // 蜂群编排：执行 + 轮询节点级状态（画布着色 + 输出查看）
  runState.value = 'running'
  runStatus.value = {}
  try {
    const res = await runCanvasApi(canvasId.value)
    const runId = res?.data?.runId
    if (!runId) {
      runState.value = 'failed'
      return
    }
    // 轮询执行状态（1s 间隔，终态停止）
    for (;;) {
      await new Promise(r => setTimeout(r, 1000))
      try {
        const statusRes = await getCanvasRun(canvasId.value, runId)
        const data = statusRes as unknown as CanvasRunStatus
        if (!data) continue
        runStatus.value = data.node_results ?? {}
        if (data.status === 'completed') {
          runState.value = 'completed'
          break
        }
        if (data.status === 'failed' || data.status === 'cancelled') {
          runState.value = 'failed'
          break
        }
      } catch {
        // 单次轮询失败忽略，继续下一轮
      }
    }
  } catch {
    runState.value = 'failed'
  }
}

// 初始化：如果 URL 有 :id 参数，加载已有工作流
async function loadFromRoute(workflowId: string | undefined) {
  if (!workflowId) {
    canvasId.value = null
    workflowName.value = ''
    canvasNodes.value = []
    canvasEdges.value = []
    runStatus.value = {}
    return
  }
  const snapshot = await loadCanvas(workflowId)
  if (snapshot) {
    canvasId.value = snapshot.id ?? workflowId
    workflowName.value = snapshot.name
    canvasNodes.value = snapshot.nodes ?? []
    canvasEdges.value = snapshot.edges ?? []
    runStatus.value = {}
  } else {
    workflowName.value = `工作流 ${workflowId}`
  }
}

onMounted(async () => {
  document.addEventListener('keydown', onKeyDown)
  document.addEventListener('mousedown', onDocMousedownClose)
  // 蜂群：agent 选择器数据 + 动态节点库
  agentStore.loadAgents().catch(() => undefined)
  loadDynamicNodes()
  await loadFromRoute(route.params.id as string | undefined)
})

// 路由参数变化（如从"我的画布"打开另一画布）时组件被复用，必须重新加载
watch(
  () => route.params.id,
  (id) => {
    void loadFromRoute(id as string | undefined)
  },
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeyDown)
  document.removeEventListener('mousedown', onDocMousedownClose)
})
</script>

<style scoped>
.canvas-designer { display: flex; flex-direction: column; height: calc(100vh - 64px); background: var(--nr-bg-primary, #0a0e1a); }

/* 工具栏 */
.canvas-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: rgba(255, 255, 255, 0.03); border-bottom: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08)); }
.toolbar-left { display: flex; align-items: center; gap: 12px; }
.canvas-title { color: var(--nr-text-primary); font-size: 15px; font-weight: 600; margin: 0; }
.toolbar-right { display: flex; gap: 8px; }
.my-canvas-item { display: flex; flex-direction: column; gap: 2px; min-width: 180px; }
.my-canvas-name { font-weight: 600; }
.my-canvas-meta { font-size: 12px; opacity: 0.6; }

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
.canvas-edges { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; filter: none; }

/* 画布节点 */
.graph-node { position: absolute; min-width: 140px; background: rgba(20, 25, 40, 0.95); border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.1)); border-radius: 10px; cursor: move; user-select: none; transition: border-color 0.15s; }
.graph-node:hover { border-color: rgba(99, 102, 241, 0.3); }
.graph-node.selected { border-color: var(--nr-primary-light, #818cf8); box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2); }
/* 执行状态着色（蜂群编排可视化） */
.graph-node.run-success { border-color: rgba(74, 222, 128, 0.7); box-shadow: 0 0 0 2px rgba(74, 222, 128, 0.15); }
.graph-node.run-failed { border-color: rgba(248, 113, 113, 0.7); box-shadow: 0 0 0 2px rgba(248, 113, 113, 0.15); }
.graph-node.run-skipped { border-color: rgba(148, 163, 184, 0.5); opacity: 0.55; }
.graph-node.run-running { border-color: rgba(250, 204, 21, 0.8); box-shadow: 0 0 0 2px rgba(250, 204, 21, 0.2); }
.node-output-view {
  max-height: 200px; overflow: auto; margin: 4px 0 0; padding: 8px;
  border-radius: 6px; background: rgba(0, 0, 0, 0.3); font-size: 11px;
  color: var(--nr-text-secondary); white-space: pre-wrap; word-break: break-all;
}
.graph-node-header { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.graph-node-icon { font-size: 14px; }
.graph-node-title { color: var(--nr-text-primary); font-size: 12px; font-weight: 600; }
.graph-node-body { padding: 6px 10px; display: flex; flex-direction: column; gap: 4px; }
.port { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--nr-text-tertiary); }
.port-in { justify-content: flex-start; }
.port-out { justify-content: flex-end; }
.port-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--nr-primary-light, #818cf8); }
/* 输出端口：拖出连线；扩大热区便于命中 */
.port-dot-out {
  cursor: crosshair;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.15);
  transition: transform 0.1s, box-shadow 0.1s;
}
.port-dot-out:hover { transform: scale(1.4); box-shadow: 0 0 0 5px rgba(129, 140, 248, 0.25); }
/* 输入端口：松手落点 */
.port-dot-in { cursor: pointer; }

/* ── 连线层（SVG）──
   注意：<line> 默认 stroke 为 none，必须显式给 .edge-line 描边，否则连线不可见；
   <path> 默认 fill 为黑色，必须显式 fill: none，否则贝塞尔曲线会以黑色填充
   曲线与首尾点连线围成的区域，看起来像曲线下有阴影；
   描边颜色必须完全不透明——半透明描边叠在网格底上会晕出暗色虚影，同样像阴影 */
.edge-line { fill: none; filter: none; stroke: #6366f1; stroke-width: 2; }
.edge-line.selected { stroke: #f59e0b; stroke-width: 3; }
.edge-hit { fill: none; stroke: transparent; stroke-width: 14; pointer-events: stroke; cursor: pointer; }
.edge-preview { fill: none; filter: none; stroke: #818cf8; stroke-width: 2; stroke-dasharray: 6 4; }

.connect-hint {
  position: absolute;
  bottom: 10px;
  left: 14px;
  font-size: 12px;
  color: var(--nr-text-tertiary);
  pointer-events: none;
  user-select: none;
}

/* 节点删除按钮 */
.node-delete {
  margin-left: auto;
  width: 16px; height: 16px;
  line-height: 14px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--nr-text-tertiary);
  font-size: 13px;
  cursor: pointer;
}
.node-delete:hover { background: rgba(239, 68, 68, 0.2); color: #ef4444; }

/* 缩放控制栏 */
.canvas-zoombar {
  position: absolute;
  right: 14px;
  bottom: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 8px;
  background: rgba(20, 25, 40, 0.85);
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.08));
  z-index: 5;
}
.zoom-btn {
  width: 24px; height: 24px;
  border: none; border-radius: 6px;
  background: transparent;
  color: var(--nr-text-primary);
  font-size: 14px;
  cursor: pointer;
}
.zoom-btn:hover { background: rgba(255, 255, 255, 0.1); }
.zoom-value {
  min-width: 44px;
  text-align: center;
  font-size: 12px;
  color: var(--nr-text-secondary);
  cursor: pointer;
}
.zoom-divider { width: 1px; height: 16px; background: var(--nr-border, rgba(255,255,255,0.12)); }

/* 右键菜单（Teleport 到 body，fixed 定位） */
.canvas-ctx-menu {
  position: fixed;
  z-index: 1100;
  min-width: 180px;
  padding: 4px;
  border-radius: 8px;
  background: rgba(20, 25, 40, 0.97);
  border: 1px solid var(--nr-border, rgba(255, 255, 255, 0.1));
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}
.ctx-item {
  display: block;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--nr-text-primary);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.ctx-item:hover { background: rgba(99, 102, 241, 0.18); }
.ctx-item.danger:hover { background: rgba(239, 68, 68, 0.18); }
.ctx-sep { height: 1px; margin: 4px 6px; background: var(--nr-border, rgba(255,255,255,0.1)); }

/* 属性面板 */
.props-empty { display: flex; align-items: center; justify-content: center; height: 100px; color: var(--nr-text-tertiary); font-size: 12px; }
.props-content { display: flex; flex-direction: column; gap: 12px; }
.prop-group { display: flex; flex-direction: column; gap: 4px; }
.prop-group label { color: var(--nr-text-tertiary); font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
</style>
