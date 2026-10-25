<template>
  <div class="graph-workbench-page">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ t('knowledge.workbenchTitle') }}</h2>
        <p class="page-subtitle">
          {{ currentAgent?.name || '' }}
          <a-tag v-if="studio?.tenant_scoped" color="blue" class="tenant-tag">
            {{ t('knowledge.workbenchTenantScoped') }}
          </a-tag>
        </p>
      </div>
      <div class="header-actions">
        <a-radio-group v-model:value="viewMode" size="sm" button-style="solid">
          <a-radio-button value="2d">{{ t('knowledge.workbenchView2d') }}</a-radio-button>
          <a-radio-button value="3d">{{ t('knowledge.workbenchView3d') }}</a-radio-button>
        </a-radio-group>
        <GlassButton variant="secondary" :loading="loading" @click="fetchStudio">
          {{ t('common.refresh') }}
        </GlassButton>
      </div>
    </div>

    <a-alert
      v-if="studio?.truncated"
      type="warning"
      show-icon
      class="truncated-hint"
      :message="t('knowledge.workbenchTruncatedHint', { total: studio?.total_nodes ?? 0 })"
    />

    <div class="workbench-layout">
      <GlassCard class="canvas-card">
        <a-spin :spinning="loading">
          <div class="canvas-toolbar">
            <div class="node-search">
              <a-input-search
                v-model:value="nodeFilter"
                size="sm"
                allow-clear
                :placeholder="t('knowledge.workbenchNodeSearch')"
                style="max-width: 220px"
                @search="searchNodes"
              />
              <div v-if="searchHits.length" class="search-hits">
                <div v-for="hit in searchHits" :key="hit.id" class="search-hit"
                     @click="pickHit(hit)">
                  <a-tag :color="kindColor(hit.type)" class="kind-tag">{{ hit.type }}</a-tag>
                  <span class="term-id">{{ hit.label }}</span>
                </div>
              </div>
            </div>
            <GlassButton
              size="sm"
              variant="secondary"
              :disabled="!filteredNodes.length"
              @click="focusFirstMatch"
            >
              {{ t('knowledge.workbenchFocusNode') }}
            </GlassButton>
            <GlassButton
              v-if="focusNodeId"
              size="sm"
              variant="secondary"
              @click="exitFocus"
            >
              {{ t('knowledge.workbenchFullGraph') }}
            </GlassButton>
            <a-checkbox v-model:checked="fullGraph" class="isolated-toggle">
              {{ t('knowledge.workbenchFullGraph') }}
            </a-checkbox>
            <a-checkbox v-model:checked="showIsolated" class="isolated-toggle">
              {{ t('knowledge.workbenchShowIsolated') }}
            </a-checkbox>
            <span class="canvas-count">{{ filteredNodes.length }}/{{ studio?.nodes?.length ?? 0 }}</span>
          </div>
          <div ref="canvasWrapRef" class="canvas-wrap">
            <GraphExplorer3D
              v-if="viewMode === '3d'"
              class="explorer3d-embed"
              :agent-id="agentId"
              :focus-id="selectedNodeId || undefined"
              @select="onNodeSelected"
              @clear="selectedNodeId = ''"
            />
            <VueFlow
              v-else-if="filteredNodes.length"
              :key="`${dataVersion}-${viewMode}`"
              :nodes="flowNodes"
              :edges="flowEdges"
              :fit-view-on-init="false"
              :default-viewport="initialViewport"
              :min-zoom="0.35"
              :max-zoom="2"
              class="workbench-flow"
              @node-click="onFlowNodeClick"
            >
              <Background />
              <MiniMap pannable zoomable />
              <Controls />
              <template #edge-flow="edgeProps">
                <FlowEdge v-bind="edgeProps" :label="String(edgeProps.label ?? '')" />
              </template>
            </VueFlow>
            <div v-else-if="!loading" class="canvas-empty">
              <a-empty :description="t('common.noData')" />
            </div>
          </div>
        </a-spin>
      </GlassCard>

      <GlassCard class="panel-card">
        <a-tabs v-model:active-key="activeTab">
          <a-tab-pane key="ontology" :tab="t('knowledge.workbenchOntology')">
            <div class="panel-toolbar">
              <a-input-search
                v-model:value="termFilter"
                :placeholder="t('knowledge.workbenchFilterTerms')"
                allow-clear
                size="sm"
                style="max-width: 200px"
              />
              <GlassButton
                v-if="isAdmin"
                size="sm"
                @click="termFormVisible = !termFormVisible"
              >
                {{ t('knowledge.workbenchNewTerm') }}
              </GlassButton>
            </div>

            <div v-if="isAdmin && termFormVisible" class="term-form">
              <a-input v-model:value="termForm.term_id" size="sm" :disabled="!!editingTermId"
                       :placeholder="t('knowledge.workbenchTermId')" />
              <a-select v-model:value="termForm.kind" size="sm"
                        :placeholder="t('knowledge.workbenchTermKind')">
                <a-select-option value="concept">concept</a-select-option>
                <a-select-option value="relation">relation</a-select-option>
                <a-select-option value="property">property</a-select-option>
              </a-select>
              <a-input v-model:value="termForm.label" size="sm"
                       :placeholder="t('knowledge.workbenchTermLabel')" />
              <a-input v-model:value="termForm.basis" size="sm"
                       :placeholder="t('knowledge.workbenchBasis')" />
              <div class="term-form-actions">
                <GlassButton size="sm" :loading="termSaving" @click="saveTerm">
                  {{ editingTermId ? t('knowledge.workbenchUpdate') : t('common.confirm') }}
                </GlassButton>
                <GlassButton v-if="editingTermId" size="sm" variant="secondary" @click="cancelEditTerm">
                  {{ t('common.cancel') }}
                </GlassButton>
              </div>
            </div>

            <div class="term-list">
              <div v-for="term in filteredTerms" :key="term.term_id" class="term-row">
                <a-tag :color="kindColor(term.kind)" class="kind-tag">{{ term.kind }}</a-tag>
                <span class="term-id" :title="term.label">{{ term.term_id }}</span>
                <span class="term-version">v·{{ term.version }}</span>
                <a-button v-if="isAdmin" type="text" size="sm" class="term-edit"
                          @click="startEditTerm(term)">
                  ✎
                </a-button>
                <a-popconfirm
                  v-if="isAdmin"
                  :title="t('knowledge.workbenchConfirmDeleteTerm')"
                  @confirm="deleteTerm(term)"
                >
                  <a-button type="text" size="sm" danger>✕</a-button>
                </a-popconfirm>
              </div>
              <a-empty v-if="!filteredTerms.length && !loading"
                       :description="t('knowledge.workbenchEmptyTerms')" />
            </div>

            <!-- S2 规则面：列表 + 新建/删除（与术语同一写面纪律） -->
            <div class="rules-section">
              <div class="panel-toolbar">
                <h4 class="rules-title">{{ t('knowledge.workbenchRules') }}</h4>
                <GlassButton v-if="isAdmin" size="sm" @click="ruleFormVisible = !ruleFormVisible">
                  {{ t('knowledge.workbenchNewRule') }}
                </GlassButton>
              </div>
              <div v-if="isAdmin && ruleFormVisible" class="term-form">
                <a-input v-model:value="ruleForm.rule_id" size="sm" :disabled="!!editingRuleId"
                         :placeholder="t('knowledge.workbenchRuleId')" />
                <a-input v-model:value="ruleForm.head_predicate" size="sm"
                         :placeholder="t('knowledge.workbenchHeadPredicate')" />
                <a-textarea v-model:value="ruleForm.body" :rows="3" size="sm"
                            :placeholder="t('knowledge.workbenchBodyJson')" />
                <a-input v-model:value="ruleForm.basis" size="sm"
                         :placeholder="t('knowledge.workbenchBasis')" />
                <div class="term-form-actions">
                  <GlassButton size="sm" :loading="ruleSaving" @click="saveRule">
                    {{ editingRuleId ? t('knowledge.workbenchUpdate') : t('common.confirm') }}
                  </GlassButton>
                  <GlassButton v-if="editingRuleId" size="sm" variant="secondary" @click="cancelEditRule">
                    {{ t('common.cancel') }}
                  </GlassButton>
                </div>
              </div>
              <div class="term-list">
                <div v-for="rule in schemaRules" :key="rule.rule_id" class="term-row">
                  <a-tag color="orange" class="kind-tag">rule</a-tag>
                  <span class="term-id" :title="rule.head_predicate">
                    {{ rule.rule_id }} → {{ rule.head_predicate }}
                  </span>
                  <span class="term-version">v·{{ rule.version }}</span>
                  <a-tag v-if="rule.enabled === false" color="default" class="kind-tag">off</a-tag>
                  <a-button v-if="isAdmin" type="text" size="sm" class="term-edit"
                            @click="startEditRule(rule)">
                    ✎
                  </a-button>
                  <a-popconfirm
                    v-if="isAdmin"
                    :title="t('knowledge.workbenchConfirmDeleteRule')"
                    @confirm="deleteRule(rule)"
                  >
                    <a-button type="text" size="sm" danger>✕</a-button>
                  </a-popconfirm>
                </div>
                <a-empty v-if="!schemaRules.length" :description="t('knowledge.workbenchEmptyRules')" />
              </div>
            </div>

            <div class="schema-footer">
              {{ t('knowledge.workbenchSchemaVersion', { version: studio?.schema?.schema_version ?? '-' }) }}
            </div>
          </a-tab-pane>

          <a-tab-pane key="instance" :tab="t('knowledge.workbenchInstanceEdit')">
            <div v-if="!isAdmin" class="admin-only-hint">
              {{ t('knowledge.workbenchAdminOnly') }}
            </div>
            <div v-else class="instance-form">
              <a-input v-model:value="instanceForm.subject_label" size="sm"
                       :placeholder="t('knowledge.workbenchSubject')" />
              <a-select v-model:value="instanceForm.predicate_term_id" size="sm"
                        :placeholder="t('knowledge.workbenchPredicate')">
                <a-select-option v-for="rel in relationTerms" :key="rel.term_id"
                                 :value="rel.term_id">
                  {{ rel.term_id }}
                </a-select-option>
              </a-select>
              <a-input v-model:value="instanceForm.object_term" size="sm"
                       :placeholder="t('knowledge.workbenchObject')" />
              <a-input v-model:value="instanceForm.entry_id" size="sm"
                       :placeholder="t('knowledge.workbenchEntryId')" />
              <a-textarea v-model:value="instanceForm.evidence_text" :rows="3" size="sm"
                         :placeholder="t('knowledge.workbenchEvidence')" />
              <a-input v-model:value="instanceForm.basis" size="sm"
                       :placeholder="t('knowledge.workbenchBasis')" />
              <GlassButton block :loading="edgeSaving" @click="createInstance">
                {{ t('knowledge.workbenchCreateEdge') }}
              </GlassButton>
              <p class="evidence-hint">{{ t('knowledge.workbenchEvidenceHint') }}</p>
            </div>
          </a-tab-pane>

          <a-tab-pane key="spatial" :tab="t('knowledge.workbenchSpatial')">
            <!-- antdv tabs 会挂载全部页签内容；地图/3D 只在首次激活时挂载，
                 jsdom/无 WebGL 环境不因未打开的页签崩 -->
            <GeoMapPanel v-if="activeTab === 'spatial'" />
          </a-tab-pane>
        </a-tabs>
      </GlassCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import { Controls } from '@vue-flow/controls'
// Vue Flow 的画布布局与默认主题样式——不 import 的话节点/边/连线手柄全部错位
// （运行时会有 "haven't loaded the necessary styles" 警告，画布实际不可用）。
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/minimap/dist/style.css'
import '@vue-flow/controls/dist/style.css'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useAuthStore } from '@/stores/auth'
import { request } from '@/api'
import { radialLayout } from '@/pages/graph-workbench/radial'
import FlowEdge from '@/pages/graph-workbench/FlowEdge.vue'

// 3D/地图都是重依赖（WebGL/three、maplibre），defineAsyncComponent 懒加载：
// 不切到对应视图就不下载，2D 主路径的包体不受影响。
const GraphExplorer3D = defineAsyncComponent(
  () => import('@/pages/graph-workbench/GraphExplorer3D.vue'))
const GeoMapPanel = defineAsyncComponent(
  () => import('@/pages/graph-workbench/GeoMapPanel.vue'))

const { t } = useI18n()
// onAgentChange：agent 切换后重拉工作台数据（与旧图谱页同款联动，切换族测试钉着）。
const { agentId, currentAgent } = useAgentPage({
  onAgentChange: () => fetchStudio(),
})
const authStore = useAuthStore()

interface StudioNode { id: string; label: string; type: string }
interface StudioEdge { source: string; target: string; relation: string }
interface OntologyTerm { term_id: string; kind: string; label: string; version: string }
interface OntologyRule {
  rule_id: string
  head_predicate: string
  head_subject_var?: string
  body?: Array<Record<string, unknown>>
  version: string
  enabled?: boolean
}
interface StudioData {
  nodes?: StudioNode[]
  edges?: StudioEdge[]
  total_nodes?: number
  truncated?: boolean
  tenant_scoped?: boolean
  schema?: { terms?: OntologyTerm[]; rules?: OntologyRule[]; schema_version?: number }
}

const loading = ref(false)
const canvasWrapRef = ref<HTMLElement | null>(null)
const studio = ref<StudioData | null>(null)
const activeTab = ref<'ontology' | 'instance' | 'spatial'>('ontology')
const viewMode = ref<'2d' | '3d'>('2d')
const selectedNodeId = ref('')
const termFilter = ref('')
const nodeFilter = ref('')
// 按图谱检索：输入走后端 search_nodes 全图索引（不是前端过滤当前渲染集——
// 邻域模式只加载了枢纽 2 跳，画布外的节点前端过滤永远搜不到）；
// 命中后以命中节点为焦点加载其邻域（radial 以其为根重铺）。
const focusNodeId = ref('')
const searchHits = ref<StudioNode[]>([])
const searchBusy = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null
const localRender = ref<StudioData | null>(null)
const displayData = computed(() => localRender.value ?? studio.value)
const termFormVisible = ref(false)
const termSaving = ref(false)
const edgeSaving = ref(false)
const ruleFormVisible = ref(false)
const ruleSaving = ref(false)
const editingTermId = ref('')
const editingRuleId = ref('')

const isAdmin = computed(() => authStore.currentUser?.role === 'admin')

const termForm = reactive({ term_id: '', kind: 'concept', label: '', basis: '' })
const ruleForm = reactive({ rule_id: '', head_predicate: '', body: '', basis: '' })
const instanceForm = reactive({
  subject_label: '', predicate_term_id: '', object_term: '',
  entry_id: '', evidence_text: '', basis: '',
})

const flowNodes = computed(() => {
  const nodes = filteredNodes.value
  // 放射布局：以选中节点为根（聚焦后以其为圆心重铺），无选中取度数枢纽——
  // 子树扇区不相交，树边互不交叉。
  const positions = radialLayout(
    nodes, (displayData.value?.edges ?? []) as never, selectedNodeId.value || focusNodeId.value || undefined)
  // 自算包围盒（视口居中的唯一依据，不依赖 vue-flow 的节点测量）。
  if (positions.size) {
    const xs = Array.from(positions.values()).map((p) => p.x)
    const ys = Array.from(positions.values()).map((p) => p.y)
    layoutBounds = {
      minX: Math.min(...xs), maxX: Math.max(...xs),
      minY: Math.min(...ys), maxY: Math.max(...ys),
    }
  }
  return nodes.map((n) => ({
    id: n.id,
    label: n.label,
    position: positions.get(n.id) ?? { x: 0, y: 0 },
    data: { label: n.label, type: n.type },
    type: 'default',
    class: n.id === selectedNodeId.value ? 'wb-node-selected' : '',
  }))
})

// fit-view-on-init 的实测缺陷：其包围盒测量与 zoom 夹取组合会把视口平移到
// 节点区之外（『看起来空』的真身——节点全渲染着，只是屏外）；命令式视口
// （useVueFlow / pane-ready 回调 / setViewport）要么静默中止渲染要么不生效。
// 最终方案纯声明式：布局包围盒自算，数据到位后算出 initialViewport，
// 数据版本号作 :key 重挂载画布时经 defaultViewport 应用——无实例 API。
const dataVersion = ref(0)
const initialViewport = ref({ x: 0, y: 0, zoom: 0.5 })
let layoutBounds = { minX: 0, maxX: 0, minY: 0, maxY: 0 }
const computeInitialViewport = () => {
  const el = canvasWrapRef.value
  const vw = el && el.clientWidth ? el.clientWidth : 572
  const vh = el && el.clientHeight ? el.clientHeight : 560
  const bw = layoutBounds.maxX - layoutBounds.minX + 160
  const bh = layoutBounds.maxY - layoutBounds.minY + 160
  const zoom = Math.max(0.35, Math.min(1.2, Math.min(vw / bw, vh / bh)))
  const cx = (layoutBounds.minX + layoutBounds.maxX) / 2
  const cy = (layoutBounds.minY + layoutBounds.maxY) / 2
  initialViewport.value = { x: vw / 2 - cx * zoom, y: vh / 2 - cy * zoom, zoom }
}
const flowEdges = computed(() =>
  (displayData.value?.edges ?? []).map((e, index) => ({
    id: `e-${index}`,
    source: e.source,
    target: e.target,
    label: e.relation,
    // 流光动效：自定义 flow 边（双层 path——底层实线 + 上层循环流光），
    // 默认边只有一条 path，animated 虚线会整体覆盖底色做不出双层。
    type: 'flow',
  })))

const relationTerms = computed(() =>
  (studio.value?.schema?.terms ?? []).filter((term) => term.kind === 'relation'))
const schemaRules = computed(() => studio.value?.schema?.rules ?? [])
const showIsolated = ref(false)
// 分级呈现：全图 145 节点 fit 到一屏时布局间距被缩到 42px，卡片压盖不可避
// 免（布局坐标级无重叠，视觉级叠）。默认只渲染枢纽 2 跳邻域（节点少、zoom
// 高、零压盖），『显示全图』显式切换后由用户缩放探索。
const fullGraph = ref(false)
const depthFromHub = computed(() => {
  const depth = new Map<string, number>()
  const adjacency = new Map<string, string[]>()
  for (const e of displayData.value?.edges ?? []) {
    if (e.source === e.target) continue
    if (!adjacency.has(e.source)) adjacency.set(e.source, [])
    if (!adjacency.has(e.target)) adjacency.set(e.target, [])
    adjacency.get(e.source)!.push(e.target)
    adjacency.get(e.target)!.push(e.source)
  }
  const roots: string[] = []
  let best = -1
  for (const [id, neighbours] of adjacency) {
    if (neighbours.length > best) {
      best = neighbours.length
      roots.length = 0
      roots.push(id)
    } else if (neighbours.length === best) {
      roots.push(id)
    }
  }
  for (const r of roots) {
    if (depth.has(r)) continue
    depth.set(r, 0)
    const queue = [r]
    while (queue.length) {
      const u = queue.shift()!
      for (const v of adjacency.get(u) ?? []) {
        if (depth.has(v)) continue
        depth.set(v, depth.get(u)! + 1)
        queue.push(v)
      }
    }
  }
  return depth
})
// 无边节点在关系图里没有布局意义：几十个孤立点会把放射图撑爆、fit 后
// 全部不可读（『看起来空』的最终根因之一）。默认隐藏，开关显式打开才显示。
const connectedIds = computed(() => {
  const ids = new Set<string>()
  for (const e of displayData.value?.edges ?? []) {
    if (e.source === e.target) continue
    ids.add(e.source)
    ids.add(e.target)
  }
  return ids
})
const filteredNodes = computed(() => {
  // nodeFilter 只作检索输入（后端全图索引 + 命中下拉），不参与画布过滤——
  // 它曾被命中回填的 label 污染，把焦点邻域掐得只剩一个节点。
  const all = displayData.value?.nodes ?? []
  const byRelation = showIsolated.value
    ? all
    : all.filter((n) => connectedIds.value.has(n.id))
  if (fullGraph.value) return byRelation
  return byRelation.filter((n) => (depthFromHub.value.get(n.id) ?? 99) <= 2)
})
const focusFirstMatch = () => {
  const hit = filteredNodes.value[0]
  if (hit) selectedNodeId.value = hit.id
}
const filteredTerms = computed(() => {
  const needle = termFilter.value.trim().toLowerCase()
  const terms = studio.value?.schema?.terms ?? []
  if (!needle) return terms
  return terms.filter((term) =>
    term.term_id.toLowerCase().includes(needle)
    || (term.label || '').toLowerCase().includes(needle))
})

const kindColor = (kind: string) =>
  kind === 'concept' ? 'blue' : kind === 'relation' ? 'purple' : 'green'

const fetchStudio = async () => {
  loading.value = true
  try {
    const res: any = await request.get(`/knowledge-graph/${agentId.value}/studio`)
    studio.value = res?.data ?? res
    // 强制求值 flowNodes：layoutBounds 在 computed 内更新，随后算初始视口。
    void flowNodes.value
    computeInitialViewport()
    dataVersion.value++
  } catch (e: any) {
    message.error(e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const createTerm = async () => {
  if (!termForm.term_id.trim()) {
    message.warning(t('knowledge.workbenchTermIdRequired'))
    return
  }
  termSaving.value = true
  try {
    await request.post('/knowledge/ontology/terms', { ...termForm })
    message.success(t('knowledge.workbenchTermCreated'))
    termForm.term_id = ''
    termForm.label = ''
    termForm.basis = ''
    termFormVisible.value = false
    await fetchStudio()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    termSaving.value = false
  }
}

const saveTerm = async () => {
  if (!termForm.term_id.trim()) {
    message.warning(t('knowledge.workbenchTermIdRequired'))
    return
  }
  termSaving.value = true
  try {
    if (editingTermId.value) {
      // PUT 部分更新：未填字段（label 空串、version 缺省）由后端保留现值。
      await request.put(
        `/knowledge/ontology/terms/${encodeURIComponent(editingTermId.value)}`,
        { kind: termForm.kind, label: termForm.label, basis: termForm.basis })
      message.success(t('knowledge.workbenchTermUpdated'))
    } else {
      await request.post('/knowledge/ontology/terms', { ...termForm })
      message.success(t('knowledge.workbenchTermCreated'))
    }
    termForm.term_id = ''
    termForm.label = ''
    termForm.basis = ''
    termFormVisible.value = false
    editingTermId.value = ''
    await fetchStudio()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    termSaving.value = false
  }
}

const startEditTerm = (term: OntologyTerm) => {
  editingTermId.value = term.term_id
  termForm.term_id = term.term_id
  termForm.kind = term.kind
  termForm.label = term.label || ''
  termForm.basis = ''
  termFormVisible.value = true
}

const cancelEditTerm = () => {
  editingTermId.value = ''
  termForm.term_id = ''
  termForm.label = ''
  termForm.basis = ''
  termFormVisible.value = false
}

const parseRuleBody = (): Array<Record<string, unknown>> | null => {
  try {
    const parsed = JSON.parse(ruleForm.body)
    if (!Array.isArray(parsed) || !parsed.length) return null
    return parsed
  } catch {
    return null
  }
}

const saveRule = async () => {
  const body = parseRuleBody()
  if (!editingRuleId.value && !ruleForm.rule_id.trim()) {
    message.warning(t('knowledge.workbenchRuleIdRequired'))
    return
  }
  if (!body) {
    message.warning(t('knowledge.workbenchBodyJsonInvalid'))
    return
  }
  ruleSaving.value = true
  try {
    const payload = {
      head_predicate: ruleForm.head_predicate,
      body,
      basis: ruleForm.basis,
    }
    if (editingRuleId.value) {
      await request.put(
        `/knowledge/ontology/rules/${encodeURIComponent(editingRuleId.value)}`, payload)
      message.success(t('knowledge.workbenchRuleUpdated'))
    } else {
      await request.post('/knowledge/ontology/rules', { rule_id: ruleForm.rule_id, ...payload })
      message.success(t('knowledge.workbenchRuleCreated'))
    }
    ruleForm.rule_id = ''
    ruleForm.head_predicate = ''
    ruleForm.body = ''
    ruleForm.basis = ''
    ruleFormVisible.value = false
    editingRuleId.value = ''
    await fetchStudio()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    ruleSaving.value = false
  }
}

const startEditRule = (rule: OntologyRule) => {
  editingRuleId.value = rule.rule_id
  ruleForm.rule_id = rule.rule_id
  ruleForm.head_predicate = rule.head_predicate
  ruleForm.body = JSON.stringify(rule.body ?? [], null, 0)
  ruleForm.basis = ''
  ruleFormVisible.value = true
}

const cancelEditRule = () => {
  editingRuleId.value = ''
  ruleForm.rule_id = ''
  ruleForm.head_predicate = ''
  ruleForm.body = ''
  ruleForm.basis = ''
  ruleFormVisible.value = false
}

const deleteRule = async (rule: OntologyRule) => {
  try {
    await request.delete(
      `/knowledge/ontology/rules/${encodeURIComponent(rule.rule_id)}`,
      { params: { basis: t('knowledge.workbenchDeleteRuleBasis') } })
    message.success(t('knowledge.workbenchRuleDeleted'))
    await fetchStudio()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  }
}

const deleteTerm = async (term: OntologyTerm) => {
  try {
    await request.delete(
      `/knowledge/ontology/terms/${encodeURIComponent(term.term_id)}`,
      { params: { basis: t('knowledge.workbenchDeleteBasis') } })
    message.success(t('knowledge.workbenchTermDeleted'))
    await fetchStudio()
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    message.warning(
      typeof detail === 'object' && detail?.impact
        ? `${t('knowledge.workbenchTermInUse')} (${detail.impact.fact_count}/${detail.impact.typed_subject_count}/${detail.impact.child_terms?.length ?? 0})`
        : detail || e?.message || t('common.error'))
  }
}

const createInstance = async () => {
  if (!instanceForm.subject_label.trim() || !instanceForm.object_term.trim()
    || !instanceForm.predicate_term_id || !instanceForm.evidence_text.trim()) {
    message.warning(t('knowledge.workbenchEvidenceRequired'))
    return
  }
  edgeSaving.value = true
  try {
    const res: any = await request.post('/knowledge/graph/instances', {
      agent_id: agentId.value,
      ...instanceForm,
    })
    message.success(t('knowledge.workbenchEdgeCreated', {
      fact: res?.data?.fact_id ?? res?.data?.data?.fact_id ?? '',
    }))
    instanceForm.subject_label = ''
    instanceForm.object_term = ''
    instanceForm.entry_id = ''
    instanceForm.evidence_text = ''
    instanceForm.basis = ''
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    edgeSaving.value = false
  }
}

// 按图谱检索：输入防抖后走后端 search_nodes 全图索引。
const searchNodes = async () => {
  const q = nodeFilter.value.trim()
  if (searchTimer) {
    clearTimeout(searchTimer)
    searchTimer = null
  }
  if (q.length < 2) {
    searchHits.value = []
    return
  }
  searchBusy.value = true
  try {
    const res: any = await request.get(
      `/knowledge-graph/${agentId.value}/knowledge-graph/search`,
      { params: { q, limit: 10 } })
    const data = res?.data ?? res
    searchHits.value = (data?.nodes ?? []) as StudioNode[]
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    searchBusy.value = false
  }
}

watch(nodeFilter, (next: string) => {
  if (searchTimer) clearTimeout(searchTimer)
  const q = next.trim()
  if (q.length < 2) {
    searchHits.value = []
    return
  }
  searchTimer = setTimeout(() => void searchNodes(), 350)
})

// 命中节点加载其邻域为渲染集（radial 以命中为根重铺，命中节点居中）。
const loadFocusNeighborhood = async (id: string) => {
  loading.value = true
  try {
    const res: any = await request.get(
      `/knowledge-graph/${agentId.value}/subgraph`,
      { params: { focus: id, hops: 2, limit: 200 } })
    const data = res?.data ?? res
    localRender.value = {
      nodes: data?.nodes ?? [],
      edges: data?.edges ?? [],
      total_nodes: data?.total_nodes,
      truncated: data?.truncated,
      schema: studio.value?.schema,
    }
    void flowNodes.value
    computeInitialViewport()
    dataVersion.value++
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const pickHit = (hit: StudioNode) => {
  focusNodeId.value = hit.id
  selectedNodeId.value = hit.id
  searchHits.value = []
  nodeFilter.value = hit.label
  void loadFocusNeighborhood(hit.id)
}

const exitFocus = () => {
  focusNodeId.value = ''
  localRender.value = null
  searchHits.value = []
  void flowNodes.value
  computeInitialViewport()
  dataVersion.value++
}

const onFlowNodeClick = (mouseEvent: { node: { id: string } }) => {
  selectedNodeId.value = mouseEvent.node.id
}

const onNodeSelected = (nodeId: string) => {
  selectedNodeId.value = nodeId
}

onMounted(() => {
  fetchStudio()
})
</script>

<style scoped>
.graph-workbench-page {
  display: flex;
  flex-direction: column;
  gap: var(--nr-space-md);
  height: 100%;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-title {
  margin: 0;
  font-size: 20px;
  color: var(--nr-text-primary, inherit);
}

.page-subtitle {
  margin: 0;
  color: var(--nr-text-secondary, inherit);
  opacity: 0.72;
}

.truncated-hint {
  flex: none;
}

.workbench-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: var(--nr-space-md);
  flex: 1;
  min-height: 0;
}

.canvas-card,
.panel-card {
  min-height: 420px;
  overflow: auto;
}

.canvas-wrap {
  height: 560px;
}

.canvas-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.workbench-flow :deep(.wb-node-selected) {
  box-shadow: 0 0 0 3px var(--nr-primary);
}

/* 节点卡片收窄到 96px：与布局 MIN_ARC=120 匹配（96+间距），
   密集层的弧长才有足够余量；label 超宽省略。 */
.workbench-flow :deep(.vue-flow__node-default) {
  width: 96px;
  font-size: 11px;
  padding: 6px 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 连接线双层：底层半透明实线表连接存在，流光层短划线循环流动
   （FlowEdge.vue 两条 path 叠加，默认边单条 path 做不出双层）。 */
.workbench-flow :deep(.vue-flow__edge .flow-base) {
  stroke: rgba(129, 140, 248, 0.4);
  stroke-width: 1.5;
}

.workbench-flow :deep(.vue-flow__edge .flow-stream) {
  stroke: #a5b4fc;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-dasharray: 3 15;
  stroke-dashoffset: 0;
  animation: wb-flow-line 1.1s linear infinite;
  filter: drop-shadow(0 0 3px rgba(129, 140, 248, 0.9));
}

/* 位移一个完整 dash 周期（3+15=18），循环无缝。 */
@keyframes wb-flow-line {
  to {
    stroke-dashoffset: -18;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workbench-flow :deep(.vue-flow__edge .flow-stream) {
    animation: none;
    stroke: rgba(165, 180, 252, 0.6);
  }
}

.explorer3d-embed {
  height: 100%;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm);
}

.workbench-flow {
  width: 100%;
  height: 100%;
  background: var(--nr-bg-inset);
  border-radius: var(--nr-radius-md, 12px);
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--nr-space-sm);
  margin-bottom: var(--nr-space-sm);
}

.term-form,
.instance-form {
  display: flex;
  flex-direction: column;
  gap: var(--nr-space-sm);
  padding: var(--nr-space-sm);
  margin-bottom: var(--nr-space-sm);
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-md, 12px);
  background: var(--nr-glass-bg);
}

.term-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 380px;
  overflow: auto;
}

.term-row {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm);
  padding: 4px 6px;
  border-radius: 8px;
}

.term-row:hover {
  background: var(--nr-glass-bg-hover);
}

.kind-tag {
  flex: none;
  min-width: 64px;
  text-align: center;
}

.term-id {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
}

.term-version {
  flex: none;
  opacity: 0.6;
  font-size: 12px;
}

.schema-footer {
  margin-top: var(--nr-space-sm);
  opacity: 0.6;
  font-size: 12px;
  text-align: right;
}

.evidence-hint {
  margin: 0;
  opacity: 0.6;
  font-size: 12px;
}

.admin-only-hint {
  opacity: 0.7;
  text-align: center;
  padding: var(--nr-space-xl) 0;
}

@media (max-width: 960px) {
  .workbench-layout {
    grid-template-columns: 1fr;
  }
}

.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm);
  margin-bottom: var(--nr-space-sm);
}

.node-search {
  position: relative;
}

.search-hits {
  position: absolute;
  z-index: 20;
  top: 100%;
  left: 0;
  right: 0;
  max-height: 260px;
  overflow: auto;
  margin-top: 4px;
  padding: 4px;
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-md, 12px);
  background: var(--nr-bg-overlay, rgba(10, 14, 26, 0.95));
  backdrop-filter: blur(8px);
}

.search-hit {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm, 8px);
  padding: 5px 6px;
  border-radius: 8px;
  cursor: pointer;
}

.search-hit:hover {
  background: var(--nr-glass-bg-hover);
}

.canvas-count {
  opacity: 0.6;
  font-size: 12px;
}

.term-form-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--nr-space-sm);
}

.term-edit {
  flex: none;
}

.rules-section {
  margin-top: var(--nr-space-md);
}

.rules-title {
  margin: 0;
  font-size: 14px;
  color: var(--nr-text-primary, inherit);
}
</style>
