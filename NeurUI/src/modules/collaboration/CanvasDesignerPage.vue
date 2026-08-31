<template>
  <!--
    CanvasDesignerPage.vue — 可视化画布设计器
    职责：可视化拖拽编排工作流节点 + 多 Agent 协作流程
    设计：三栏布局（左侧节点库 | 中间画布 | 右侧属性面板）

    当前为骨架版本，后续可集成 Vue Flow / reactflow 风格的节点画布。
    Infinite-Canvas 整合后可复用其画布组件。
  -->
  <div class="canvas-designer" ref="canvasRoot">
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
                  <span class="my-canvas-meta">{{ c.node_count }} {{ t('canvas.nodeCount') }} · {{ formatTime(c.updated_at) }}</span>
                </div>
              </a-menu-item>
              <a-menu-item v-if="savedCanvases.length === 0" disabled key="empty">
                {{ t('common.noData') }}
              </a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <GlassButton variant="ghost" size="sm" @click="storeDrawerOpen = true">
          <ShopOutlined /> {{ t('canvas.tabStores') }}
        </GlassButton>
        <GlassButton
          variant="ghost"
          size="sm"
          :disabled="!fullscreenSupported"
          :title="fullscreenSupported ? (isCanvasFullscreen ? t('canvas.fullscreenExit') : t('canvas.fullscreenEnter')) : t('canvas.fullscreenUnsupported')"
          @click="toggleFullscreen"
        >
          <FullscreenExitOutlined v-if="isCanvasFullscreen" />
          <FullscreenOutlined v-else />
        </GlassButton>
        <GlassButton variant="ghost" size="sm" @click="handleSave">{{ t('common.save') }}</GlassButton>
        <GlassButton variant="ghost" size="sm" :disabled="!canvasId" @click="versionsOpen = true">
          {{ t('workflowVersion.button') }}
        </GlassButton>
        <GlassButton variant="ghost" size="sm" :disabled="!canvasId" @click="triggersOpen = true">
          {{ t('trigger.button') }}
        </GlassButton>
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
                :title="t('canvas.deleteNode')"
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
                  :title="t('canvas.connectTip') + input.label"
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
                  :title="t('canvas.linkTip') + output.label"
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
            <button class="zoom-btn" :title="t('canvas.zoomOut')" @click="zoomOut">−</button>
            <span
              class="zoom-value"
              :title="t('canvas.resetView')"
              @click="resetView"
            >{{ Math.round(viewport.zoom * 100) }}%</span>
            <button class="zoom-btn" :title="t('canvas.zoomIn')" @click="zoomIn">＋</button>
            <span class="zoom-divider" />
            <button class="zoom-btn zoom-fit" :title="t('canvas.fitContent')" @click="fitView">⤢</button>
          </div>

          <p v-if="canvasNodes.length > 0" class="connect-hint">
            {{ t('canvas.canvasHint') }}
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

          <!-- 调试 Mock 编辑（P0 遗留⑤：节点级 mock_output，保存随画布快照） -->
          <div class="prop-group">
            <label>{{ t('debug.mocksTitle') }}</label>
            <MockEditor
              :node-id="selectedNodeId ?? ''"
              :model-value="selectedNode.config?.mock_output ?? null"
              @update:model-value="handleMockUpdate"
              @clear="handleMockClear"
            />
          </div>

          <!-- Agent 节点专用表单（蜂群编排：绑定真实子 Agent + 任务） -->
          <template v-if="selectedNode.type === 'builtin:agent'">
            <div class="prop-group">
              <label>{{ t('canvas.execAgent') }}</label>
              <a-select
                v-model:value="selectedNode.config.agent_id"
                :options="agentOptions"
                size="small"
                allow-clear
                show-search
                option-filter-prop="label"
                :placeholder="t('canvas.selectSubAgent')"
              />
            </div>
            <div class="prop-group">
              <label>{{ t('canvas.taskDesc') }}</label>
              <a-textarea
                v-model:value="selectedNode.config.task"
                :rows="4"
                size="small"
                :placeholder="t('canvas.subAgentTaskDesc')"
              />
            </div>
          </template>

          <!-- 通用配置表单：按节点定义 sub_blocks 渲染（textarea/select/model-selector/input） -->
          <!-- key 含索引：平台联动变体共享同一 config 键（如 products），纯键作 key 会冲突 -->
          <div class="prop-group" v-for="(field, idx) in configFields" :key="idx + ':' + field.key">
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
                :placeholder="t('canvas.selectModel')"
                @change="handleModelSelect"
              />
              <a-select
                v-model:value="selectedNode.config.model_provider"
                :options="providerOptions"
                size="small"
                style="margin-top: 6px"
                :placeholder="t('canvas.providerHint')"
              />
            </template>
            <a-select
              v-else-if="field.type === 'select'"
              v-model:value="selectedNode.config[field.key]"
              :options="field.options"
              size="small"
            />
            <template v-else-if="field.type === 'store-select'">
              <a-select
                v-model:value="selectedNode.config[field.key]"
                :options="storeOptions"
                size="small"
                allow-clear
                show-search
                option-filter-prop="label"
                :placeholder="t('canvas.storeSelectPh')"
                :loading="storeOptionsLoading"
                :disabled="storeServiceUnavailable"
              />
              <p v-if="storeServiceUnavailable" class="store-connect-hint">{{ t('canvas.storeServiceUnavailable') }}</p>
              <p v-else-if="!storeOptionsLoading && storeOptions.length === 0" class="store-connect-hint">
                {{ t('canvas.noStoresYet') }}<a class="store-connect-link" @click="storeDrawerOpen = true">{{ t('canvas.goConnectStores') }}</a>
              </p>
            </template>
            <a-slider
              v-else-if="field.type === 'slider'"
              v-model:value="selectedNode.config[field.key]"
              :min="field.min ?? 0"
              :max="field.max ?? 100"
              style="width: 100%"
            />
            <!-- R-6: toggle 布尔开关（如 ima allow_local / 节点开关） -->
            <a-switch
              v-else-if="field.type === 'toggle' || field.type === 'switch'"
              v-model:checked="selectedNode.config[field.key]"
              size="small"
            />
            <!-- 修复⑤ — json/code 控件：a-textarea + JSON 实时校验（adapters/comfyui
                 布尔参数被序列化为 switch，动态工具/技能布尔参数同享 toggle 分支） -->
            <template v-else-if="field.type === 'json' || field.type === 'code'">
              <a-textarea
                :value="jsonFieldText(selectedNode.config[field.key])"
                :rows="4"
                size="small"
                class="mono-input"
                @update:value="(v: string) => handleJsonFieldInput(field.key, v)"
              />
              <p v-if="jsonFieldError[field.key]" class="json-field-error">{{ jsonFieldError[field.key] }}</p>
            </template>
            <a-input v-else v-model:value="selectedNode.config[field.key]" size="small" />
          </div>

          <!-- 店铺授权节点（店铺为下属对象）：面板即店铺管理页入口 -->
          <template v-if="selectedNode.type === 'builtin:store-auth'">
            <div class="prop-group">
              <label>{{ t('canvas.storeTitle') }}</label>
              <p v-if="storeAuthInfo" class="store-auth-status">
                {{ storeAuthInfo.store_name }}（{{ platformDisplayName(storeAuthInfo.platform) }}）·
                <span class="store-badge" :class="`badge-${storeAuthInfo.status ?? 'pending'}`">{{ storeAuthInfo.status ?? 'pending' }}</span>
              </p>
              <p v-else class="store-connect-hint">{{ t('canvas.storeSelectPh') }}</p>
              <p v-if="storeAuthInfo?.last_error" class="store-auth-error" :title="storeAuthInfo.last_error">{{ t('canvas.storeErrorTag') }}: {{ storeAuthInfo.last_error }}</p>
            </div>
            <div class="prop-group store-auth-actions">
              <a-button size="small" :disabled="!selectedNode.config.store_id" :loading="storeAuthTesting" @click="runStoreAuthTest">
                {{ t('canvas.storeTest') }}
              </a-button>
              <a-button size="small" @click="storeDrawerOpen = true">{{ t('canvas.storeAuthOpen') }}</a-button>
            </div>
          </template>

          <!-- 执行结果查看 -->
          <div class="prop-group" v-if="runStatus[selectedNode.id]">
            <label>{{ t('canvas.execResult', { status: runStatus[selectedNode.id]?.status }) }}</label>
            <pre class="node-output-view">{{ formatNodeOutput(runStatus[selectedNode.id]) }}</pre>
          </div>
        </div>
      </aside>
    </div>

    <!-- R-8: 对话式画布设计（角落可收缩） -->
    <CanvasNLDesigner @apply="applyNlDesign" />

    <!-- 画布右键菜单 -->
    <Teleport to="body">
      <div
        v-if="ctxMenu.open"
        class="canvas-ctx-menu"
        :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      >
        <template v-if="ctxMenu.kind === 'node'">
          <button class="ctx-item danger" @click="ctxDeleteNode">{{ t('canvas.ctxDeleteNode') }}</button>
          <button class="ctx-item" @click="ctxDuplicateNode">{{ t('canvas.ctxDuplicateNode') }}</button>
          <button class="ctx-item" @click="ctxToggleBreakpoint">
            {{ debugController.breakpoints.value.has(ctxMenu.id ?? '') ? t('debug.removeBreakpoint') : t('debug.addBreakpoint') }}
          </button>
        </template>
        <template v-else-if="ctxMenu.kind === 'edge'">
          <button class="ctx-item danger" @click="ctxDeleteEdge">{{ t('canvas.ctxDeleteEdge') }}</button>
        </template>
        <template v-else>
          <button class="ctx-item" @click="ctxAddNode">{{ t('canvas.ctxAddNode') }}</button>
        </template>
        <div class="ctx-sep" />
        <button class="ctx-item" @click="ctxZoomIn">{{ t('canvas.ctxZoomIn') }}</button>
        <button class="ctx-item" @click="ctxZoomOut">{{ t('canvas.ctxZoomOut') }}</button>
        <button class="ctx-item" @click="ctxResetView">{{ t('canvas.ctxResetView') }}</button>
      </div>
    </Teleport>

    <!-- 店铺管理抽屉（§6.2） -->
    <CanvasStoreDrawer v-model:open="storeDrawerOpen" @changed="reloadStoresForNode" />

    <!-- 版本历史抽屉（P2-4.4 前端） -->
    <WorkflowVersionsDrawer
      v-model:open="versionsOpen"
      :workflow-id="canvasId"
      @refreshed="() => { if (canvasId) loadCanvas(canvasId) }"
 />

    <!-- 触发器管理抽屉（P1 前端） -->
    <TriggerManagerDrawer v-model:open="triggersOpen" :workflow-id="canvasId" />

    <!-- 调试面板浮窗（P0 遗留⑤：断点列表 + Mock 列表 + 单步控制） -->
    <DebugPanel
      v-if="showDebugPanel"
      :controller="debugController"
      :execution-id="lastRunId ?? ''"
      @toggle-breakpoint="() => {}"
      @clear-mock="(nodeId: string) => setNodeMock(nodeId, null).catch(() => {})"
      @resume="handleDebugResume"
    />
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
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeftOutlined, DownOutlined, BgColorsOutlined,
  ApartmentOutlined, RobotOutlined, BulbOutlined,
  ClockCircleOutlined, DatabaseOutlined, FileOutlined, ShoppingOutlined,
  FullscreenOutlined, FullscreenExitOutlined,
} from '@ant-design/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import { useCollaboration, CanvasVersionConflictError } from '@/composables/useCollaboration'
import { useSessionSync, type SessionSyncEvent } from '@/composables/useSessionSync'
import { useAgentStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'
import { uiMessage } from '@/utils/message'
import { getNodes, listStores, testStoreConnection, type ConnectedStore } from '@/api/modules/neurflow'
import { buildStoreSelectOptions, platformDisplayName, type StoreItem } from './canvasStores'
import CanvasNLDesigner from './CanvasNLDesigner.vue'
import {
  canFullscreen,
  exitFullscreenCompat,
  isFullscreen as docIsFullscreen,
  requestFullscreenCompat,
  type FullscreenDoc,
  type FullscreenEl,
} from './canvasFullscreen'
import CanvasStoreDrawer from './CanvasStoreDrawer.vue'
import WorkflowVersionsDrawer from './WorkflowVersionsDrawer.vue'
import TriggerManagerDrawer from './TriggerManagerDrawer.vue'
import DebugPanel from './DebugPanel.vue'
import MockEditor from './MockEditor.vue'
import { createDebugController, type DebugController } from './DebugPanel'
import { useReachableModels, buildModelOptions } from '@/composables/useReachableModels'
import {
  runCanvas as runCanvasApi,
  getCanvasRun,
  setNodeMock,
  type CanvasRunStatus,
} from '@/api/modules/collaboration'
import type { CanvasNodeSnapshot, CanvasEdgeSnapshot } from '@/api/modules/collaboration'
import {
  filterVisibleSubBlocks,
  type SubBlockCondition,
} from './canvasSubBlocks'

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
  min?: number
  max?: number
  /** 条件可见（联动下拉）：对齐后端 SubBlockConfig.condition {field, operator, value} */
  condition?: SubBlockCondition | null
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
/** 服务端画布版本号（乐观锁）：保存时作为 base_version 回传，
 *  收到 canvas_op 事件时同步推进；冲突说明被其他编辑者（agent）抢占 */
const canvasVersion = ref<number | null>(null)
const selectedNodeId = ref<string | null>(null)
const nodeSearch = ref('')
const canvasRef = ref<HTMLElement>()

// ── 蜂群/编排：Agent 选择 + 执行状态可视化 ──
const agentStore = useAgentStore()
const agentOptions = computed(() => agentStore.agentOptions)
/** 节点执行状态（nodeId → 状态+输出），来自画布运行轮询 */
const runStatus = ref<Record<string, { status: string; output?: unknown; error?: string | null }>>({})
const runState = ref<'idle' | 'running' | 'completed' | 'failed'>('idle')
/** 最近一次画布运行的 runId（调试 resume 用） */
const lastRunId = ref<string | null>(null)
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
// ── 调试集成（P0 遗留⑤）──
const debugController: DebugController = createDebugController('')
const showDebugPanel = ref(false)
const selectedMockDraft = ref<unknown>(null)
const versionsOpen = ref(false)
const triggersOpen = ref(false)

function ctxToggleBreakpoint() {
  const nodeId = ctxMenu.id
  if (!nodeId) return
  debugController.toggleBreakpoint(nodeId)
  if (debugController.breakpoints.value.size > 0) showDebugPanel.value = true
  closeCtxMenu()
}

async function handleMockUpdate(value: unknown) {
  const nodeId = selectedNodeId.value
  if (!nodeId) return
  debugController.setMockOutput(nodeId, value)
  // 修复② — mock 随画布快照持久化（execute() 引擎读 config.mock_output 短路）
  const node = canvasNodes.value.find(n => n.id === nodeId)
  if (node) node.config = { ...node.config, mock_output: value }
  try {
    await setNodeMock(nodeId, value)
    uiMessage.success(t('common.save'))
  } catch {
    uiMessage.error(t('debug.mockSaveFailed'))
  }
}

async function handleMockClear() {
  const nodeId = selectedNodeId.value
  if (!nodeId) return
  debugController.clearMock(nodeId)
  // 修复② — 同步清除画布快照内的 mock（引擎判定 is not None）
  const node = canvasNodes.value.find(n => n.id === nodeId)
  if (node) {
    const { mock_output: _removed, ...rest } = node.config
    node.config = rest
  }
  try {
    await setNodeMock(nodeId, null)
  } catch {
    /* 后端清理失败不阻塞本地状态 */
  }
}

function handleDebugResume(payload: Record<string, unknown>) {
  const executionId = lastRunId.value
  if (!executionId) {
    uiMessage.info(t('debug.needRunningExecution'))
    return
  }
  import('@/api/modules/collaboration')
    .then(m => m.resumeExecution(executionId, (payload.step as 'in' | 'over' | 'out') ?? undefined))
    .catch(() => uiMessage.error(t('debug.resumeFailed')))
}

// ── 修复⑤ — json/code 字段编辑（对象↔文本双向 + 校验）──
const jsonFieldError = reactive<Record<string, string>>({})

function jsonFieldText(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function handleJsonFieldInput(key: string, text: string) {
  const trimmed = text.trim()
  if (!trimmed) {
    delete jsonFieldError[key]
    selectedNode.value!.config[key] = ''
    return
  }
  try {
    selectedNode.value!.config[key] = JSON.parse(text)
    delete jsonFieldError[key]
  } catch (e) {
    // 输入中途（半成品 JSON）保留原值不覆盖，仅提示；回显用原文
    jsonFieldError[key] = (e as Error).message
    selectedNode.value!.config[key] = text
  }
}

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
/** 电商平台选项（与后端 commerce_nodes._COMMERCE_PLATFORM_OPTIONS 对齐） */
const COMMERCE_PLATFORM_OPTIONS: SubBlockOption[] = [
  { value: 'amazon', label: t('canvas.c0015') },
  { value: 'taobao', label: t('canvas.c0016') },
  { value: 'jd', label: t('canvas.c0017') },
  { value: 'douyin-ecom', label: t('canvas.c0018') },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'pdd', label: t('canvas.c0019') },
  { value: 'ali1688', label: '1688' },
  { value: 'xiaohongshu', label: t('canvas.c0020') },
  { value: 'xianyu', label: t('canvas.c0021') },
  { value: 'shein', label: t('canvas.c0022') },
]

/** 亚马逊 SP-API 选项（依据官方开发文档 developer-docs.amazon.com/sp-api，与后端 commerce_nodes 对齐） */
const AMAZON_MARKETPLACE_OPTIONS: SubBlockOption[] = [
  { value: 'ATVPDKIKX0DER', label: t('canvas.c0023') },
  { value: 'A2EUQ1WTGCTBG2', label: t('canvas.c0024') },
  { value: 'A1AM78C64UM0Y8', label: t('canvas.c0025') },
  { value: 'A2Q3Y263D00KWC', label: t('canvas.c0026') },
  { value: 'A1F83G8C2ARO7P', label: t('canvas.c0027') },
  { value: 'A1PA6795UKMFR9', label: t('canvas.c0028') },
  { value: 'A13V1IB3VIYZZH', label: t('canvas.c0029') },
  { value: 'APJ6JRA9NG5V4', label: t('canvas.c0030') },
  { value: 'A1RKKUPIHCS9HS', label: t('canvas.c0031') },
  { value: 'A1VC38T7YXB528', label: t('canvas.c0032') },
  { value: 'A19VAU5U5O7RUS', label: t('canvas.c0033') },
  { value: 'A39IBJ37TRP1C6', label: t('canvas.c0034') },
]

/** SP-API / Amazon Ads 区域端点（NA / EU / FE） */
const AMAZON_REGION_OPTIONS: SubBlockOption[] = [
  { value: 'na', label: t('canvas.c0035') },
  { value: 'eu', label: t('canvas.c0036') },
  { value: 'fe', label: t('canvas.c0037') },
]

/** SP-API Reports API v2021-06-30 常用报表类型 */
const AMAZON_REPORT_TYPE_OPTIONS: SubBlockOption[] = [
  { value: 'GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL', label: t('canvas.c0038') },
  { value: 'GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL', label: t('canvas.c0039') },
  { value: 'GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL', label: t('canvas.c0040') },
  { value: 'GET_FBA_INVENTORY_RECEIPT_SUMMARY', label: t('canvas.c0041') },
  { value: 'GET_MERCHANT_LISTINGS_ALL_DATA', label: t('canvas.c0042') },
  { value: 'GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT', label: t('canvas.c0043') },
]

/** Listings Items API putListingsItem requirements 参数 */
const AMAZON_LISTING_REQUIREMENTS_OPTIONS: SubBlockOption[] = [
  { value: 'LISTING', label: t('canvas.c0044') },
  { value: 'LISTING_PRODUCT_ONLY', label: t('canvas.c0045') },
  { value: 'LISTING_OFFER_ONLY', label: t('canvas.c0046') },
]

/** 字符串数组 → SubBlockOption[] 转换 */
const strOpts = (list: string[]): SubBlockOption[] => list.map(v => ({ label: v, value: v }))

/** 带 i18n 的选项转换：value 保留原值，label 用 t() 翻译 */
const i18nOpts = (pairs: [value: string, key: string][]): SubBlockOption[] =>
  pairs.map(([value, key]) => ({ label: t(key), value }))

/** 条件可见：仅选择亚马逊时显示（SP-API / Amazon Ads 专属参数） */
const WHEN_AMAZON: SubBlockCondition = { field: 'platform', operator: 'eq', value: 'amazon' }

/**
 * 生成同一 config 键的分平台变体块（联动下拉）：
 * 选择某平台后仅显示该平台的参数块（标题体现平台 API 的 ID 命名），
 * 各变体绑定同一 config 键且默认值一致，仅 title/condition 不同。
 *
 * @param fallbackTitle 提供时为未覆盖的其余平台生成一个通用兜底变体
 */
function platformScopedIdBlocks(
  key: string,
  type: 'input' | 'textarea',
  defaultValue: string,
  labels: Record<string, string>,
  fallbackTitle?: string,
): SubBlockDef[] {
  const blocks: SubBlockDef[] = Object.entries(labels).map(([platform, title]) => ({
    id: key,
    title,
    type,
    default_value: defaultValue,
    condition: { field: 'platform', operator: 'eq', value: platform },
  }))
  if (fallbackTitle) {
    const rest = COMMERCE_PLATFORM_OPTIONS.map(o => o.value).filter(v => !(v in labels))
    if (rest.length > 0) {
      blocks.push({
        id: key,
        title: fallbackTitle,
        type,
        default_value: defaultValue,
        condition: { field: 'platform', operator: 'in', value: rest },
      })
    }
  }
  return blocks
}

const paletteCategories = [
  {
    name: 'builtin',
    labelKey: 'collab.catBuiltin',
    icon: BulbOutlined,
    nodes: [
      { type: 'builtin:start', label: t('canvas.c0047'), icon: '▶', category: 'builtin', inputs: [], outputs: [{ id: 'out', label: t('canvas.c0048') }], defaultConfig: {} },
      { type: 'builtin:end', label: t('canvas.c0049'), icon: '⏹', category: 'builtin', inputs: [{ id: 'in', label: t('canvas.c0050') }], outputs: [], defaultConfig: {} },
      { type: 'builtin:llm', label: t('canvas.c0051'), icon: '🤖', category: 'builtin', inputs: [{ id: 'input', label: t('canvas.c0052') }], outputs: [{ id: 'output', label: t('canvas.c0053') }, { id: 'usage', label: t('canvas.c0054') }], defaultConfig: { prompt: '', model_provider: 'auto', model_name: '', temperature: 0.7, max_tokens: 4096, system_prompt: '' }, subBlocks: [
        { id: 'prompt', title: t('canvas.c0055'), type: 'textarea' },
        { id: 'model_provider', title: t('canvas.c0056'), type: 'select', default_value: 'auto', options: [{ label: t('canvas.c0057'), value: 'auto' }] },
        { id: 'model_name', title: t('canvas.c0058'), type: 'model-selector' },
        { id: 'temperature', title: t('canvas.c0059'), type: 'slider', default_value: 0.7, min: 0, max: 2 },
        { id: 'max_tokens', title: t('canvas.c0060'), type: 'slider', default_value: 4096, min: 100, max: 128000 },
        { id: 'system_prompt', title: t('canvas.c0061'), type: 'textarea' },
      ] },
      { type: 'builtin:agent', label: t('canvas.c0062'), icon: '🧠', category: 'builtin', inputs: [{ id: 'task', label: t('canvas.c0063') }], outputs: [{ id: 'result', label: t('canvas.c0064') }], defaultConfig: {} },
      { type: 'builtin:condition', label: t('canvas.c0065'), icon: '❓', category: 'builtin', inputs: [{ id: 'in', label: t('canvas.c0066') }], outputs: [{ id: 'true', label: t('canvas.c0067') }, { id: 'false', label: t('canvas.c0068') }], defaultConfig: {} },
      { type: 'builtin:subflow', label: t('canvas.subflowNode'), icon: '🧩', category: 'builtin', inputs: [{ id: 'in', label: t('canvas.c0066') }], outputs: [{ id: 'output', label: t('canvas.c0053') }], defaultConfig: { workflow_id: '', input_mapping: '{}' }, subBlocks: [
        { id: 'workflow_id', title: '目标工作流 ID', type: 'input' },
        { id: 'input_mapping', title: '入参映射（JSON）', type: 'json' },
      ] as SubBlockDef[] },
    ] as PaletteNode[],
  },
  {
    name: 'comfyui',
    labelKey: 'collab.catComfyui',
    icon: BgColorsOutlined,
    nodes: [
      { type: 'comfyui:KSampler', label: 'KSampler', icon: '🎨', category: 'comfyui', inputs: [{ id: 'model', label: t('canvas.c0069') }, { id: 'positive', label: t('canvas.c0070') }, { id: 'negative', label: t('canvas.c0071') }], outputs: [{ id: 'latent', label: t('canvas.c0072') }], defaultConfig: { seed: 42, steps: 20 } },
      { type: 'comfyui:VAEDecode', label: t('canvas.c0073'), icon: '🖼', category: 'comfyui', inputs: [{ id: 'samples', label: t('canvas.c0074') }, { id: 'vae', label: 'VAE' }], outputs: [{ id: 'image', label: t('canvas.c0075') }], defaultConfig: {} },
      { type: 'comfyui:CheckpointLoaderSimple', label: t('canvas.c0076'), icon: '📦', category: 'comfyui', inputs: [], outputs: [{ id: 'model', label: t('canvas.c0077') }, { id: 'clip', label: 'CLIP' }, { id: 'vae', label: 'VAE' }], defaultConfig: { ckpt_name: 'model.safetensors' } },
    ] as PaletteNode[],
  },
  {
    name: 'data',
    labelKey: 'collab.catData',
    icon: DatabaseOutlined,
    nodes: [
      { type: 'builtin:memory-load', label: t('canvas.c0078'), icon: '💾', category: 'data', inputs: [], outputs: [{ id: 'memory', label: t('canvas.c0079') }], defaultConfig: {} },
      { type: 'builtin:memory-save', label: t('canvas.c0080'), icon: '📝', category: 'data', inputs: [{ id: 'data', label: t('canvas.c0081') }], outputs: [], defaultConfig: {} },
    ] as PaletteNode[],
  },
  {
    name: 'input',
    labelKey: 'collab.catInput',
    icon: FileOutlined,
    nodes: [
      {
        type: 'builtin:text_input',
        label: t('canvas.c0001'),
        icon: '📝',
        category: 'input',
        inputs: [],
        outputs: [{ id: 'text', label: t('canvas.c0082') }],
        defaultConfig: { value: '' },
        subBlocks: [
          { id: 'value', title: t('canvas.c0083'), type: 'textarea' },
        ],
      },
      {
        type: 'builtin:media_input',
        label: t('canvas.c0002'),
        icon: '🖼️',
        category: 'input',
        inputs: [],
        outputs: [{ id: 'media', label: t('canvas.c0084') }],
        defaultConfig: { media_type: 'file', source: 'url', value: '' },
        subBlocks: [
          { id: 'media_type', title: t('canvas.c0085'), type: 'select', default_value: 'file', options: [
            { label: t('canvas.c0086'), value: 'image' },
            { label: t('canvas.c0087'), value: 'audio' },
            { label: t('canvas.c0088'), value: 'video' },
            { label: t('canvas.c0089'), value: 'file' },
          ] },
          { id: 'source', title: t('canvas.c0090'), type: 'select', default_value: 'url', options: [
            { label: 'URL', value: 'url' },
            { label: 'Data URL', value: 'data-url' },
            { label: 'Base64', value: 'base64' },
          ] },
          { id: 'value', title: t('canvas.c0091'), type: 'textarea' },
        ],
      },
    ] as PaletteNode[],
  },
  // 电商运营节点（与后端 commerce_nodes.COMMERCE_NODES 对齐，作为静态兜底；
  // 后端启动后动态节点中重复 type 会被 staticNodeTypes 过滤，配置以静态为准）
  {
    key: 'commerce',
    name: 'commerce',
    icon: ShoppingOutlined,
    labelKey: 'collab.catCommerce',
    nodes: [
      {
        type: 'builtin:price-monitor',
        label: t('canvas.c0003'),
        icon: '💰',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0092') }],
        outputs: [
          { id: 'output', label: t('canvas.c0093') },
          { id: 'alerts', label: t('canvas.c0094') },
        ],
        defaultConfig: { platform: 'amazon', products: 'B0XXXXXX', marketplace_id: 'ATVPDKIKX0DER', region: 'na', alert_threshold: '50', check_interval: 6 },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0095'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          ...platformScopedIdBlocks('products', 'textarea', 'B0XXXXXX', {
            amazon: t('canvas.phAmazon'),
            taobao: t('canvas.phTaobao'),
            jd: t('canvas.phJd'),
            pdd: t('canvas.phPdd'),
            'douyin-ecom': t('canvas.phDouyin'),
            tiktok: t('canvas.phTiktok'),
          }, t('canvas.phFallback')),
          { id: 'marketplace_id', title: t('canvas.c0096'), type: 'select', default_value: 'ATVPDKIKX0DER', options: AMAZON_MARKETPLACE_OPTIONS, condition: WHEN_AMAZON },
          { id: 'region', title: t('canvas.c0097'), type: 'select', default_value: 'na', options: AMAZON_REGION_OPTIONS, condition: WHEN_AMAZON },
          { id: 'alert_threshold', title: t('canvas.c0098'), type: 'input', default_value: '50' },
          { id: 'check_interval', title: t('canvas.c0099'), type: 'slider', default_value: 6, min: 1, max: 168 },
        ],
      },
      {
        type: 'builtin:ad-copy',
        label: t('canvas.c0004'),
        icon: '📢',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0100') }],
        outputs: [{ id: 'output', label: t('canvas.c0101') }],
        defaultConfig: { platform: 'amazon', product: '', style: 'promotion', language: 'zh' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0102'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          { id: 'product', title: t('canvas.c0103'), type: 'input', default_value: '' },
          { id: 'style', title: t('canvas.c0104'), type: 'select', default_value: 'promotion', options: i18nOpts([
            ['promotion', 'canvas.optStylePromotion'],
            ['seed', 'canvas.optStyleSeed'],
            ['brand', 'canvas.optStyleBrand'],
            ['pain', 'canvas.optStylePain'],
            ['festival', 'canvas.optStyleFestival'],
          ]) },
          { id: 'language', title: t('canvas.c0105'), type: 'input', default_value: 'zh' },
        ],
      },
      {
        type: 'builtin:review-respond',
        label: t('canvas.c0005'),
        icon: '💬',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0106') }],
        outputs: [
          { id: 'output', label: t('canvas.c0107') },
          { id: 'sentiment', label: t('canvas.c0108') },
        ],
        defaultConfig: { platform: 'taobao', asin: '', marketplace_id: 'ATVPDKIKX0DER', reviews: '', tone: 'friendly' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0109'), type: 'select', default_value: 'taobao', options: COMMERCE_PLATFORM_OPTIONS },
          ...platformScopedIdBlocks('asin', 'input', '', {
            amazon: t('canvas.phAmazonReview'),
            taobao: t('canvas.phTaobaoReview'),
          }),
          { id: 'marketplace_id', title: t('canvas.c0110'), type: 'select', default_value: 'ATVPDKIKX0DER', options: AMAZON_MARKETPLACE_OPTIONS, condition: WHEN_AMAZON },
          { id: 'reviews', title: t('canvas.c0111'), type: 'textarea', default_value: '' },
          { id: 'tone', title: t('canvas.c0112'), type: 'select', default_value: 'friendly', options: i18nOpts([
            ['friendly', 'canvas.optToneFriendly'],
            ['casual', 'canvas.optToneCasual'],
            ['official', 'canvas.optToneOfficial'],
            ['caring', 'canvas.optToneCaring'],
          ]) },
        ],
      },
      {
        type: 'builtin:product-listing',
        label: t('canvas.c0006'),
        icon: '📦',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0113') }],
        outputs: [
          { id: 'output', label: t('canvas.c0114') },
          { id: 'title', label: t('canvas.c0115') },
        ],
        defaultConfig: { platform: 'amazon', product_name: '', features: '', keywords: '', sku: '', seller_id: '', product_type: 'PRODUCT', requirements: 'LISTING', marketplace_id: 'ATVPDKIKX0DER' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0116'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          { id: 'product_name', title: t('canvas.c0117'), type: 'input', default_value: '' },
          { id: 'features', title: t('canvas.c0118'), type: 'textarea', default_value: '' },
          { id: 'keywords', title: t('canvas.c0119'), type: 'input', default_value: '' },
          { id: 'sku', title: t('canvas.c0120'), type: 'input', default_value: '', condition: WHEN_AMAZON },
          { id: 'seller_id', title: t('canvas.c0121'), type: 'input', default_value: '', condition: WHEN_AMAZON },
          { id: 'product_type', title: t('canvas.c0122'), type: 'input', default_value: 'PRODUCT', condition: WHEN_AMAZON },
          { id: 'requirements', title: t('canvas.c0123'), type: 'select', default_value: 'LISTING', options: AMAZON_LISTING_REQUIREMENTS_OPTIONS, condition: WHEN_AMAZON },
          { id: 'marketplace_id', title: t('canvas.c0124'), type: 'select', default_value: 'ATVPDKIKX0DER', options: AMAZON_MARKETPLACE_OPTIONS, condition: WHEN_AMAZON },
        ],
      },
      {
        type: 'builtin:inventory-sync',
        label: t('canvas.c0007'),
        icon: '📊',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0125') }],
        outputs: [
          { id: 'output', label: t('canvas.c0126') },
          { id: 'alerts', label: t('canvas.c0127') },
        ],
        defaultConfig: { platform: 'amazon', skus: '', marketplace_id: 'ATVPDKIKX0DER', region: 'na', seller_id: '', low_stock_threshold: '10' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0128'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          ...platformScopedIdBlocks('skus', 'textarea', '', {
            amazon: t('canvas.phAmazonInv'),
            taobao: t('canvas.phTaobaoInv'),
            jd: t('canvas.phJdInv'),
            pdd: t('canvas.phPddInv'),
            'douyin-ecom': t('canvas.phDouyinInv'),
            tiktok: t('canvas.phTiktokInv'),
          }, t('canvas.phInvFallback')),
          { id: 'marketplace_id', title: t('canvas.c0129'), type: 'select', default_value: 'ATVPDKIKX0DER', options: AMAZON_MARKETPLACE_OPTIONS, condition: WHEN_AMAZON },
          { id: 'region', title: t('canvas.c0130'), type: 'select', default_value: 'na', options: AMAZON_REGION_OPTIONS, condition: WHEN_AMAZON },
          { id: 'seller_id', title: t('canvas.c0131'), type: 'input', default_value: '', condition: WHEN_AMAZON },
          { id: 'low_stock_threshold', title: t('canvas.c0132'), type: 'input', default_value: '10' },
        ],
      },
      {
        type: 'builtin:competitor-analysis',
        label: t('canvas.c0008'),
        icon: '🔍',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0133') }],
        outputs: [{ id: 'output', label: t('canvas.c0134') }],
        defaultConfig: { platform: 'amazon', competitors: '', marketplace_id: 'ATVPDKIKX0DER', region: 'na' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0135'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          ...platformScopedIdBlocks('competitors', 'textarea', '', {
            amazon: t('canvas.phAmazonComp'),
            taobao: t('canvas.phTaobaoComp'),
            jd: t('canvas.phJdComp'),
            pdd: t('canvas.phPddComp'),
            'douyin-ecom': t('canvas.phDouyinComp'),
            tiktok: t('canvas.phTiktokComp'),
          }, t('canvas.phCompFallback')),
          { id: 'marketplace_id', title: t('canvas.c0136'), type: 'select', default_value: 'ATVPDKIKX0DER', options: AMAZON_MARKETPLACE_OPTIONS, condition: WHEN_AMAZON },
          { id: 'region', title: t('canvas.c0137'), type: 'select', default_value: 'na', options: AMAZON_REGION_OPTIONS, condition: WHEN_AMAZON },
        ],
      },
      {
        type: 'builtin:keyword-research',
        label: t('canvas.c0009'),
        icon: '🏷️',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0138') }],
        outputs: [
          { id: 'output', label: t('canvas.c0139') },
          { id: 'keywords', label: t('canvas.c0140') },
        ],
        defaultConfig: { platform: 'taobao', seed_keywords: '', language: 'zh' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0141'), type: 'select', default_value: 'taobao', options: COMMERCE_PLATFORM_OPTIONS },
          { id: 'seed_keywords', title: t('canvas.c0142'), type: 'input', default_value: '' },
          { id: 'language', title: t('canvas.c0143'), type: 'input', default_value: 'zh' },
        ],
      },
      {
        type: 'builtin:sales-report',
        label: t('canvas.c0010'),
        icon: '📈',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0144') }],
        outputs: [{ id: 'output', label: t('canvas.c0145') }],
        defaultConfig: { platform: 'amazon', report_type: 'GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL', period: '2025-01', marketplace_id: 'ATVPDKIKX0DER', region: 'na', metrics: 'sales,orders' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0146'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          { id: 'report_type', title: t('canvas.c0147'), type: 'select', default_value: 'GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL', options: AMAZON_REPORT_TYPE_OPTIONS, condition: WHEN_AMAZON },
          { id: 'period', title: t('canvas.c0148'), type: 'input', default_value: '2025-01' },
          { id: 'marketplace_id', title: t('canvas.c0149'), type: 'select', default_value: 'ATVPDKIKX0DER', options: AMAZON_MARKETPLACE_OPTIONS, condition: WHEN_AMAZON },
          { id: 'region', title: t('canvas.c0150'), type: 'select', default_value: 'na', options: AMAZON_REGION_OPTIONS, condition: WHEN_AMAZON },
          { id: 'metrics', title: t('canvas.c0151'), type: 'input', default_value: 'sales,orders' },
        ],
      },
      {
        type: 'builtin:ad-streaming',
        label: t('canvas.c0011'),
        icon: '📡',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0152') }],
        outputs: [
          { id: 'output', label: t('canvas.c0153') },
          { id: 'campaign', label: t('canvas.c0154') },
        ],
        defaultConfig: { platform: 'amazon', budget: '1000', targeting: '自动定向', objective: '转化', profile_id: '', region: 'na' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0155'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          { id: 'budget', title: t('canvas.c0156'), type: 'input', default_value: '1000' },
          { id: 'targeting', title: t('canvas.c0157'), type: 'select', default_value: '自动定向', options: i18nOpts([
            ['自动定向', 'canvas.optTargetAuto'],
            ['手动定向', 'canvas.optTargetManual'],
            ['人群定向', 'canvas.optTargetAudience'],
            ['关键词定向', 'canvas.optTargetKeyword'],
          ]) },
          { id: 'objective', title: t('canvas.c0158'), type: 'select', default_value: '转化', options: i18nOpts([
            ['转化', 'canvas.optObjectiveConversion'],
            ['点击', 'canvas.optObjectiveClick'],
            ['曝光', 'canvas.optObjectiveImpression'],
            ['加购', 'canvas.optObjectiveAddCart'],
          ]) },
          { id: 'profile_id', title: 'Amazon Ads profileId', type: 'input', default_value: '', condition: WHEN_AMAZON },
          { id: 'region', title: t('canvas.c0159'), type: 'select', default_value: 'na', options: AMAZON_REGION_OPTIONS, condition: WHEN_AMAZON },
        ],
      },
      {
        type: 'builtin:ad-monitor',
        label: t('canvas.c0012'),
        icon: '👁️',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0160') }],
        outputs: [
          { id: 'output', label: t('canvas.c0161') },
          { id: 'alerts', label: t('canvas.c0162') },
        ],
        defaultConfig: { platform: 'amazon', ad_ids: 'camp_001, camp_002', metrics: 'impressions,clicks,conversions,spend', alert_threshold: '500', profile_id: '', region: 'na' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0163'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          { id: 'ad_ids', title: t('canvas.c0164'), type: 'textarea', default_value: 'camp_001, camp_002' },
          { id: 'metrics', title: t('canvas.c0165'), type: 'input', default_value: 'impressions,clicks,conversions,spend' },
          { id: 'alert_threshold', title: t('canvas.c0166'), type: 'input', default_value: '500' },
          { id: 'profile_id', title: 'Amazon Ads profileId', type: 'input', default_value: '', condition: WHEN_AMAZON },
          { id: 'region', title: t('canvas.c0167'), type: 'select', default_value: 'na', options: AMAZON_REGION_OPTIONS, condition: WHEN_AMAZON },
        ],
      },
      {
        type: 'builtin:ad-strategy',
        label: t('canvas.c0013'),
        icon: '🧠',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0168') }],
        outputs: [
          { id: 'output', label: t('canvas.c0169') },
          { id: 'strategy', label: t('canvas.c0170') },
        ],
        defaultConfig: { platform: 'amazon', goal: 'increase_sales', budget: '5000', product: '' },
        subBlocks: [
          { id: 'platform', title: t('canvas.c0171'), type: 'select', default_value: 'amazon', options: COMMERCE_PLATFORM_OPTIONS },
          { id: 'goal', title: t('canvas.c0172'), type: 'select', default_value: 'increase_sales', options: strOpts(['increase_sales', 'increase_orders', 'reduce_cpa', 'brand_awareness', 'clearance']) },
          { id: 'budget', title: t('canvas.c0173'), type: 'input', default_value: '5000' },
          { id: 'product', title: t('canvas.c0174'), type: 'input', default_value: '' },
        ],
      },
      {
        type: 'builtin:ad-cross',
        label: t('canvas.c0014'),
        icon: '🔗',
        category: 'commerce',
        inputs: [{ id: 'input', label: t('canvas.c0175') }],
        outputs: [
          { id: 'output', label: t('canvas.c0176') },
          { id: 'channels', label: t('canvas.c0177') },
        ],
        defaultConfig: { platforms: 'amazon, taobao', total_budget: '10000', product: '', objective: '转化' },
        subBlocks: [
          { id: 'platforms', title: t('canvas.c0178'), type: 'textarea', default_value: 'amazon, taobao' },
          { id: 'total_budget', title: t('canvas.c0179'), type: 'input', default_value: '10000' },
          { id: 'product', title: t('canvas.c0180'), type: 'input', default_value: '' },
          { id: 'objective', title: t('canvas.c0181'), type: 'select', default_value: '转化', options: i18nOpts([
            ['转化', 'canvas.optObjectiveConversion'],
            ['点击', 'canvas.optObjectiveClick'],
            ['曝光', 'canvas.optObjectiveImpression'],
            ['加购', 'canvas.optObjectiveAddCart'],
          ]) },
        ],
      },
    ] as PaletteNode[],
  },
]

/**
 * 静态分类已定义的节点 type 集合。
 * 动态节点库（/neurflow/nodes）中与静态节点重复的类型会被过滤；
 * 注意：不能按 builtin: 前缀过滤，drama/commerce/comfyui 等适配器节点的
 * type 也是 builtin:xxx，但 category 为 media/commerce 等独立分类。
 */
const staticNodeTypes = new Set(paletteCategories.flatMap(c => c.nodes.map(n => n.type)))

/** 动态分类中文名映射（i18n key，category → collab.catXxx） */
const DYNAMIC_CATEGORY_LABELS: Record<string, string> = {
  flow: 'collab.catFlow',
  ai: 'collab.catAI',
  memory: 'collab.catMemory',
  output: 'collab.catOutput',
  commerce: 'collab.catCommerce',
  media: 'collab.catMedia',
  skills: 'collab.catSkills',
  tools: 'collab.catTools',
  mcp: 'collab.catMCP',
}

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
  // 1. 深拷贝静态分类，避免重复分类（comfyui/data/input 等已有静态分类）
  type DynamicCat = { name: string; icon: object; labelKey: string; nodes: PaletteNode[] }
  const catMap = new Map<string, DynamicCat>()
  for (const cat of paletteCategories) {
    catMap.set(cat.name, { name: cat.name, icon: cat.icon, labelKey: cat.labelKey, nodes: [...cat.nodes] })
  }
  // 2. 按 category 分组动态节点
  for (const dn of dynamicNodes.value) {
    if (staticNodeTypes.has(dn.type)) continue
    const existing = catMap.get(dn.category)
    if (existing) {
      existing.nodes.push(dn) // 合并到现有静态分类
    } else {
      catMap.set(dn.category, {
        name: dn.category,
        icon: ApartmentOutlined,
        labelKey: DYNAMIC_CATEGORY_LABELS[dn.category] ?? dn.category,
        nodes: [dn],
      })
    }
  }
  const allCategories = [...catMap.values()]

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
    // 注意：axios 拦截器已 return response.data 解包，/neurflow/nodes 返回 { total, nodes }
    //（无外层 data 包装），取 res.nodes；兼容旧包装结构 res.data.nodes
    const items = ((res as any)?.nodes ?? (res as any)?.data?.nodes ?? []) as Array<{
      type: string
      label: string
      icon?: string
      category?: string
      inputs?: { id: string; label: string }[]
      outputs?: { id: string; label: string }[]
      sub_blocks?: Record<string, any>[]
    }>
    // 后端 sub_blocks 字段（label/name/default/options/min/max）→ 前端 SubBlockDef（title/default_value/options/min/max）
    // options 兼容对象数组 {value,label} 与纯字符串数组（电商/广告节点常见）
    const mapSubBlock = (b: Record<string, any>): SubBlockDef => {
      const raw = Array.isArray(b.options) ? b.options : []
      const options = raw.map((o: any) =>
        typeof o === 'string' ? { label: o, value: o } : { label: o.label ?? o.value, value: o.value ?? o.label },
      )
      const sb: SubBlockDef = {
        id: String(b.id),
        // 修复③ — 后端 _sub_block_to_dict 序列化键是 title（无 label/name），
        // title 必须在读链最前，否则动态节点面板标题退化为字段 id
        title: (b.title as string) ?? (b.label as string) ?? (b.name as string) ?? String(b.id),
        type: (b.type as string) || 'input',
        options,
        default_value: b.default ?? b.default_value,
      }
      if (typeof b.min === 'number') sb.min = b.min
      if (typeof b.max === 'number') sb.max = b.max
      if (b.condition && typeof b.condition === 'object' && (b.condition as Record<string, any>).field) {
        sb.condition = b.condition as SubBlockCondition
      }
      return sb
    }
    dynamicNodes.value = items
      .filter(n => !staticNodeTypes.has(n.type))
      .map(n => {
        const subBlocks = (n.sub_blocks ?? []).map(mapSubBlock)
        return {
          type: n.type,
          label: n.label,
          icon: n.icon || '🧩',
          category: n.category || 'extensions',
          inputs: n.inputs ?? [],
          outputs: n.outputs ?? [],
          defaultConfig: Object.fromEntries(subBlocks.map(b => [b.id, b.default_value ?? ''])),
          subBlocks,
        }
      })
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

/** R-8: 应用 AI 生成的画布快照（替换现有画布，供用户细化/保存/执行） */
function applyNlDesign(payload: { nodes: CanvasNodeSnapshot[]; edges: CanvasEdgeSnapshot[]; name: string; description: string }) {
  canvasNodes.value = payload.nodes.map((n, i) => ({
    ...n,
    // 重命名 id 避免冲突（AI 生成 n1/n2… 可能与已有节点冲突）
    id: `nl-${Date.now()}-${i}`,
    config: n.config || {},
  }))
  const idMap = new Map<string, string>()
  payload.nodes.forEach((n, i) => idMap.set(n.id, `nl-${Date.now()}-${i}`))
  canvasEdges.value = (payload.edges || []).map((e, i) => ({
    ...e,
    id: `nle-${Date.now()}-${i}`,
    source: e.source?.nodeId ? { nodeId: idMap.get(e.source.nodeId) || e.source.nodeId, portId: e.source.portId } : e.source,
    target: e.target?.nodeId ? { nodeId: idMap.get(e.target.nodeId) || e.target.nodeId, portId: e.target.portId } : e.target,
  }))
  if (payload.name) workflowName.value = payload.name
  selectedNodeId.value = null
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
  return [{ label: t('canvas.c0182'), value: 'auto' }, ...[...providers].map(p => ({ label: p, value: p }))]
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
    // 联动下拉：按当前 config（如 platform）过滤条件可见的字段；隐藏字段的值保留在 config 中不清除
    return filterVisibleSubBlocks(blocks, node.config).map(b => ({
      key: b.id,
      title: b.title || b.id,
      type: b.type || 'input',
      options: (b.options ?? []).map(o => ({ label: o.label, value: o.value })),
      min: b.min,
      max: b.max,
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
  if (status.error) return t('canvas.errorPrefix') + ': ' + status.error
  const out = status.output
  if (out === null || out === undefined) return t('canvas.noOutput')
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
  try {
    const saved = await saveCanvas(
      {
        id: canvasId.value ?? undefined,
        name,
        nodes: canvasNodes.value,
        edges: canvasEdges.value,
      },
      // 乐观锁：已有画布携带本地版本号；期间被其他编辑者（如 agent）
      // 修改过后端返回 409，composable 抛 CanvasVersionConflictError
      canvasId.value ? canvasVersion.value ?? undefined : undefined,
    )
    if (saved?.id) {
      const isNew = !canvasId.value
      canvasId.value = saved.id
      workflowName.value = saved.name
      canvasVersion.value = saved.version ?? null
      // 新画布首次保存后把 id 写进 URL：刷新/重开不丢（路由 :id 分支负责恢复）
      if (isNew && route.params.id !== saved.id) {
        router.replace(`/collaboration/canvas/${saved.id}`)
      }
    }
  } catch (e) {
    if (e instanceof CanvasVersionConflictError) {
      // 被抢占：重载最新版本，用户在最新版本上继续编辑
      uiMessage.warning(t('canvas.canvasReloadedByOther'))
      await loadFromRoute(canvasId.value ?? undefined)
      return
    }
    throw e
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
    const res = await runCanvasApi(canvasId.value, {
      debug: debugController.breakpoints.value.size > 0,
      breakpoints: Array.from(debugController.breakpoints.value),
    })
    const runId = res?.data?.runId
    if (!runId) {
      runState.value = 'failed'
      return
    }
    lastRunId.value = runId
    if (debugController.breakpoints.value.size > 0) showDebugPanel.value = true
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
    canvasVersion.value = null
    workflowName.value = ''
    canvasNodes.value = []
    canvasEdges.value = []
    runStatus.value = {}
    return
  }
  const snapshot = await loadCanvas(workflowId)
  if (snapshot) {
    canvasId.value = snapshot.id ?? workflowId
    canvasVersion.value = snapshot.version ?? null
    workflowName.value = snapshot.name
    canvasNodes.value = snapshot.nodes ?? []
    canvasEdges.value = snapshot.edges ?? []
    runStatus.value = {}
  } else {
    workflowName.value = t('canvas.workflowNamePrefix') + ' ' + workflowId
  }
}

// ── Agent 实时画布操作（canvas_op 事件流） ─────────────────────
// agent 经 Canvas Op 层修改画布，后端通过会话 WebSocket 广播事件；
// 此处按 op 增量应用，用户可实时观看 agent 搭建工作流。
// 实时抢占：用户本地编辑不受阻；保存走 base_version 乐观锁，冲突时
// 重载最新版本并提示（见 handleSave）。
const chatStore = useChatStore()

interface CanvasOpPayload {
  canvas_id: string
  op: string
  version?: number
  actor?: string
  data?: Record<string, any>
}

useSessionSync(
  () => chatStore.currentSessionId,
  (event: SessionSyncEvent) => {
    if (event.event_type !== 'canvas_op') return
    const p = event.payload as unknown as CanvasOpPayload
    if (!p || !p.canvas_id || p.canvas_id !== canvasId.value) return
    applyRemoteCanvasOp(p)
  },
)

function applyRemoteCanvasOp(p: CanvasOpPayload) {
  // 版本跳跃（断线重连丢事件）→ 直接重载整份快照保证一致
  if (
    typeof p.version === 'number' &&
    canvasVersion.value != null &&
    p.version > canvasVersion.value + 1
  ) {
    void loadFromRoute(canvasId.value ?? undefined)
    return
  }
  const data = (p.data ?? {}) as Record<string, any>
  switch (p.op) {
    case 'add_node': {
      const node = data.node as CanvasNodeSnapshot | undefined
      if (node?.id) {
        const idx = canvasNodes.value.findIndex(n => n.id === node.id)
        if (idx >= 0) canvasNodes.value[idx] = node
        else canvasNodes.value.push(node)
      }
      break
    }
    case 'connect': {
      const edge = data.edge as CanvasEdgeSnapshot | undefined
      if (edge?.id && !canvasEdges.value.some(e => e.id === edge.id)) {
        // 远端边只有语义端点引用，渲染坐标待 DOM 就绪后补齐
        canvasEdges.value.push({
          ...edge,
          x1: typeof edge.x1 === 'number' ? edge.x1 : 0,
          y1: typeof edge.y1 === 'number' ? edge.y1 : 0,
          x2: typeof edge.x2 === 'number' ? edge.x2 : 0,
          y2: typeof edge.y2 === 'number' ? edge.y2 : 0,
        })
        void attachEdgeEndpoints(edge.id)
      }
      break
    }
    case 'set_config': {
      const node = canvasNodes.value.find(n => n.id === data.node_id)
      if (node) node.config = { ...(node.config ?? {}), ...(data.config ?? {}) }
      break
    }
    case 'move_node': {
      const node = canvasNodes.value.find(n => n.id === data.node_id)
      if (node && data.position) {
        node.position = { x: data.position.x, y: data.position.y }
        void refreshEdgesForNode(node.id)
      }
      break
    }
    case 'remove_node': {
      canvasNodes.value = canvasNodes.value.filter(n => n.id !== data.node_id)
      canvasEdges.value = canvasEdges.value.filter(
        e => e.source?.nodeId !== data.node_id && e.target?.nodeId !== data.node_id,
      )
      break
    }
    case 'remove_edge': {
      canvasEdges.value = canvasEdges.value.filter(e => e.id !== data.edge_id)
      break
    }
    case 'layout': {
      const positions = (data.positions ?? {}) as Record<string, { x: number; y: number }>
      for (const n of canvasNodes.value) {
        const pos = positions[n.id]
        if (pos) n.position = { x: pos.x, y: pos.y }
      }
      void refreshAllEdges()
      break
    }
  }
  if (typeof p.version === 'number') canvasVersion.value = p.version
}

/** 远端边落画布后按真实端口 DOM 坐标补齐端点（找不到时按节点位置兜底） */
async function attachEdgeEndpoints(edgeId: string) {
  await nextTick()
  const edge = canvasEdges.value.find(e => e.id === edgeId)
  if (!edge) return
  const src = edge.source ? getPortCenter(edge.source.nodeId, edge.source.portId) : null
  const tgt = edge.target ? getPortCenter(edge.target.nodeId, edge.target.portId) : null
  const srcNode = canvasNodes.value.find(n => n.id === edge.source?.nodeId)
  const tgtNode = canvasNodes.value.find(n => n.id === edge.target?.nodeId)
  edge.x1 = src?.x ?? (srcNode ? srcNode.position.x + 140 : 0)
  edge.y1 = src?.y ?? (srcNode ? srcNode.position.y + 30 : 0)
  edge.x2 = tgt?.x ?? (tgtNode ? tgtNode.position.x : 0)
  edge.y2 = tgt?.y ?? (tgtNode ? tgtNode.position.y + 30 : 0)
}

/** 节点位置变化后重算其相连边的端点坐标 */
async function refreshEdgesForNode(nodeId: string) {
  await nextTick()
  for (const edge of canvasEdges.value) {
    if (edge.source?.nodeId === nodeId && edge.source.portId) {
      const p = getPortCenter(nodeId, edge.source.portId)
      if (p) { edge.x1 = p.x; edge.y1 = p.y }
    }
    if (edge.target?.nodeId === nodeId && edge.target.portId) {
      const p = getPortCenter(nodeId, edge.target.portId)
      if (p) { edge.x2 = p.x; edge.y2 = p.y }
    }
  }
}

async function refreshAllEdges() {
  await nextTick()
  for (const edge of canvasEdges.value) {
    if (edge.source?.portId) {
      const p = getPortCenter(edge.source.nodeId, edge.source.portId)
      if (p) { edge.x1 = p.x; edge.y1 = p.y }
    }
    if (edge.target?.portId) {
      const p = getPortCenter(edge.target.nodeId, edge.target.portId)
      if (p) { edge.x2 = p.x; edge.y2 = p.y }
    }
  }
}

// ── 店铺联动（store-select，§6.1）：按当前平台拉取已连接店铺 ──
const canvasRoot = ref<HTMLElement | null>(null)
const storeList = ref<ConnectedStore[]>([])
const storeOptionsLoading = ref(false)
const storeServiceUnavailable = ref(false)
const storeDrawerOpen = ref(false)

const currentPlatform = computed(() => String(selectedNode.value?.config?.platform ?? ''))
const storeOptions = computed(() => buildStoreSelectOptions(storeList.value as StoreItem[], currentPlatform.value))

async function reloadStoresForNode(): Promise<void> {
  const node = selectedNode.value
  const isStoreAuthNode = node?.type === 'builtin:store-auth'
  const platform = currentPlatform.value
  if (!platform && !isStoreAuthNode) {
    storeList.value = []
    storeServiceUnavailable.value = false
    return
  }
  storeOptionsLoading.value = true
  try {
    // 店铺授权节点以店铺为下属对象，无平台上下文时展示全部店铺
    storeList.value = await listStores(platform || undefined)
    storeServiceUnavailable.value = false
  } catch {
    // 后端未部署 /stores 时降级：隐藏选项并提示，节点执行走原有降级路径（工作流不中断）
    storeServiceUnavailable.value = true
    storeList.value = []
  } finally {
    storeOptionsLoading.value = false
  }
  // 平台变化后失效的 store_id 显式清空（引用不存在店铺会在执行时报错）
  if (node) {
    const sid = String(node.config.store_id ?? '')
    if (sid && !storeList.value.some(s => s.store_id === sid)) {
      node.config.store_id = ''
    }
  }
}

// ── 店铺授权节点（builtin:store-auth）：店铺为下属对象，面板即管理页入口 ──
const storeAuthTesting = ref(false)
const storeAuthInfo = computed(() => {
  const node = selectedNode.value
  if (node?.type !== 'builtin:store-auth') return null
  const sid = String(node.config.store_id ?? '')
  return storeList.value.find(s => s.store_id === sid) ?? null
})

async function runStoreAuthTest(): Promise<void> {
  const sid = String(selectedNode.value?.config?.store_id ?? '')
  if (!sid) return
  storeAuthTesting.value = true
  try {
    const result = await testStoreConnection(sid)
    const status = (result as { status?: string }).status
    if (status === 'active') uiMessage.success(t('canvas.msgTestPassed'))
    else uiMessage.warning(t('canvas.msgTestFailed', { reason: (result as { detail?: string }).detail ?? '' }))
    await reloadStoresForNode()
  } catch (err) {
    uiMessage.error(String(err))
  } finally {
    storeAuthTesting.value = false
  }
}

watch(
  [selectedNodeId, () => selectedNode.value?.config?.platform],
  () => {
    void reloadStoresForNode()
  },
  { immediate: false },
)

// ── 画布全屏（§6.4）：浏览器 Fullscreen API + webkit 前缀兼容 ──
const isCanvasFullscreen = ref(false)
const fullscreenSupported = computed(() =>
  Boolean(canvasRoot.value && canFullscreen(document as unknown as FullscreenDoc, canvasRoot.value as unknown as FullscreenEl)),
)

function onFullscreenChange(): void {
  isCanvasFullscreen.value = docIsFullscreen(document as unknown as FullscreenDoc)
}

function toggleFullscreen(): void {
  const el = canvasRoot.value
  if (!el || !canFullscreen(document as unknown as FullscreenDoc, el as unknown as FullscreenEl)) return
  if (docIsFullscreen(document as unknown as FullscreenDoc)) {
    exitFullscreenCompat(document as unknown as FullscreenDoc)
  } else {
    requestFullscreenCompat(el as unknown as FullscreenEl, document as unknown as FullscreenDoc)
    // 画布比例变化后聚焦内容
    nextTick(() => fitView())
  }
}

onMounted(async () => {
  document.addEventListener('keydown', onKeyDown)
  document.addEventListener('mousedown', onDocMousedownClose)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('webkitfullscreenchange', onFullscreenChange)
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
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
  // 组件卸载时若仍处全屏则主动退出
  if (docIsFullscreen(document as unknown as FullscreenDoc)) {
    exitFullscreenCompat(document as unknown as FullscreenDoc)
  }
})
</script>

<style scoped>
.canvas-designer { display: flex; flex-direction: column; height: calc(100vh - 64px); background: var(--nr-bg-primary, #0a0e1a); }
.canvas-designer:fullscreen { height: 100vh; width: 100vw; }

/* 店铺下拉空态/降级提示（§6.1） */
.store-connect-hint { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-secondary, rgba(255,255,255,0.55)); }
.json-field-error { margin: 4px 0 0; font-size: 11px; color: var(--nr-error, #ef4444); word-break: break-all; }
.mono-input :deep(textarea) { font-family: monospace; }
.store-connect-link { color: var(--nr-accent, #7c9eff); cursor: pointer; }

/* 店铺授权节点面板（§6.2/节点管理页入口） */
.store-auth-status { margin: 4px 0 0; font-size: 12px; color: var(--nr-text-secondary, rgba(255,255,255,0.7)); }
.store-auth-error { margin: 4px 0 0; font-size: 12px; color: #ff4d4f; word-break: break-all; }
.store-auth-actions { display: flex; gap: 8px; }
.store-badge { font-size: 12px; padding: 0 6px; border-radius: 8px; }
.badge-active { background: rgba(82, 196, 26, 0.15); color: #52c41a; }
.badge-error { background: rgba(255, 77, 79, 0.15); color: #ff4d4f; }
.badge-expired, .badge-pending { background: rgba(250, 173, 20, 0.15); color: #faad14; }

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
