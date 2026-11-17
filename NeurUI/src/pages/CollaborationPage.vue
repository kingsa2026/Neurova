<template>
  <div class="collab-page">
    <div class="page-header">
      <div>
        <h2>{{ t('collab.sessionsTitle') }}</h2>
        <p class="page-subtitle">{{ t('collab.sessionsSubtitle') }}</p>
      </div>
      <GlassButton variant="primary" size="md" @click="showInitiate = true">{{ t('collab.initiate') }}</GlassButton>
    </div>

    <!-- 概览统计（图标卡，与 hub 观感一致；口径统一取自归一后的 sessions） -->
    <div class="stats-row">
      <GlassCard
        v-for="s in stats"
        :key="s.key"
        :title="s.label"
        variant="subtle"
        padding="16px 20px"
      >
        <div class="stat-content">
          <span class="stat-value">{{ s.value }}</span>
          <component :is="s.icon" class="stat-icon" />
        </div>
      </GlassCard>
    </div>

    <!-- 会话列表：活跃/历史/全部 由 a-segmented 切换（history 并入本页） -->
    <GlassPanel variant="default" padding="20px 24px">
      <div class="list-header">
        <h3 class="section-title">{{ t('collab.sessions') }}</h3>
        <a-segmented v-model:value="view" :options="viewOptions" @change="onViewChange" />
      </div>
      <a-spin :spinning="loading">
        <GlassTable :columns="columns" :data-source="filteredSessions">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
            </template>
            <template v-if="column.key === 'actions'">
              <GlassButton variant="ghost" size="sm" @click="handleViewSession(record)">{{ t('common.open') }}</GlassButton>
              <GlassButton variant="ghost" size="sm" @click="openEdit(record)">{{ t('collab.edit') }}</GlassButton>
            </template>
          </template>
        </GlassTable>
      </a-spin>
    </GlassPanel>

    <!-- S12 项目协作档案：按项目聚合五类记录（消息/run/事件/候选/审批）+ 封卷总结 -->
    <GlassPanel variant="default" padding="20px 24px">
      <div class="list-header">
        <h3 class="section-title">{{ t('collab.dossierTitle') }}</h3>
        <a-select
          v-model:value="dossierProjectId"
          :options="dossierProjectOptions"
          :placeholder="t('collab.dossierSelectProject')"
          style="min-width: 220px"
          allow-clear
          @change="loadDossier"
        />
      </div>
      <a-spin :spinning="dossierLoading">
        <a-empty v-if="!dossier" :description="t('collab.dossierEmpty')" />
        <template v-else>
          <div class="dossier-counts">
            <a-tag color="blue">{{ t('collab.dossierRuns') }}: {{ dossier.counts.runs }}</a-tag>
            <a-tag color="purple">{{ t('collab.dossierEvents') }}: {{ dossier.counts.events }}</a-tag>
            <a-tag color="cyan">{{ t('collab.dossierCandidates') }}: {{ dossier.counts.candidates }}</a-tag>
            <a-tag color="orange">{{ t('collab.dossierApprovals') }}: {{ dossier.counts.approvals }}</a-tag>
            <a-tag color="green">{{ t('collab.dossierMessages') }}: {{ dossier.counts.room_messages }}</a-tag>
          </div>

          <!-- 封卷总结（项目归档时自动生成并留底） -->
          <div v-if="dossier.summary" class="dossier-summary">
            <div class="dossier-sub-title">{{ t('collab.dossierSummary') }}</div>
            <div class="dossier-counts">
              <a-tag color="blue">{{ t('collab.dossierRunsCount') }}: {{ dossier.summary.runs_count }}</a-tag>
              <a-tag color="cyan">{{ t('collab.dossierCandidatesAccepted') }}: {{ dossier.summary.candidates_accepted }}</a-tag>
              <a-tag color="red">{{ t('collab.dossierCandidatesRejected') }}: {{ dossier.summary.candidates_rejected }}</a-tag>
              <a-tag color="orange">{{ t('collab.dossierApprovalsDecided') }}: {{ dossier.summary.approvals_decided }}</a-tag>
            </div>
            <template v-if="dossier.summary.key_events.length">
              <div class="dossier-dim">{{ t('collab.dossierKeyEvents') }}</div>
              <a-timeline class="dossier-timeline">
                <a-timeline-item v-for="(ev, idx) in dossier.summary.key_events" :key="idx">
                  <span class="dossier-mono">{{ ev.type }}</span>
                  <span class="dossier-dim"> · {{ ev.subagent_id }}</span>
                </a-timeline-item>
              </a-timeline>
            </template>
          </div>
          <div v-else class="dossier-dim">{{ t('collab.dossierSummaryPending') }}</div>

          <!-- 协作 Run 台账 -->
          <div class="dossier-sub-title">{{ t('collab.dossierRuns') }}</div>
          <GlassTable
            :columns="dossierRunColumns"
            :data-source="dossier.runs"
            :pagination="false"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'status'">
                <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
              </template>
              <template v-if="column.key === 'task_summary'">
                <span class="dossier-dim">{{ record.task_summary || '—' }}</span>
              </template>
            </template>
          </GlassTable>

          <!-- 事件时间线（最近 20 条，新→旧） -->
          <div class="dossier-sub-title">{{ t('collab.dossierEvents') }}</div>
          <a-timeline v-if="dossierRecentEvents.length" class="dossier-timeline">
            <a-timeline-item v-for="ev in dossierRecentEvents" :key="ev.event_id">
              <span class="dossier-mono">{{ ev.type }}</span>
              <span class="dossier-dim"> · {{ ev.subagent_id }}<template v-if="ev.occurred_at"> · {{ ev.occurred_at }}</template></span>
            </a-timeline-item>
          </a-timeline>
          <a-empty v-else :description="t('collab.dossierEmpty')" />

          <!-- 结果候选 -->
          <div class="dossier-sub-title">{{ t('collab.dossierCandidates') }}</div>
          <div v-if="dossier.candidates.length" class="dossier-list">
            <div v-for="c in dossier.candidates" :key="c.candidate_id" class="dossier-item">
              <a-tag :color="candidateColor(c.status)">{{ c.status }}</a-tag>
              <span class="dossier-mono">{{ c.candidate_id }}</span>
              <span class="dossier-dim"> · {{ c.content_summary || c.note }}</span>
            </div>
          </div>
          <a-empty v-else :description="t('collab.dossierEmpty')" />

          <!-- 审批审计（请求+决定成对） -->
          <div class="dossier-sub-title">{{ t('collab.dossierApprovals') }}</div>
          <div v-if="dossier.approvals.length" class="dossier-list">
            <div v-for="a in dossier.approvals" :key="a.request_id" class="dossier-item">
              <a-tag :color="a.status === 'decided' ? 'green' : 'orange'">
                {{ a.status === 'decided' ? `${a.decision ?? ''}` : t('collab.dossierStatusPending') }}
              </a-tag>
              <span class="dossier-mono">{{ a.operation || a.request_id }}</span>
              <span class="dossier-dim"> · {{ a.run_id }}<template v-if="a.decided_by"> · {{ a.decided_by }}</template></span>
            </div>
          </div>
          <a-empty v-else :description="t('collab.dossierEmpty')" />

          <!-- 房间消息（摘要） -->
          <div class="dossier-sub-title">{{ t('collab.dossierMessages') }}</div>
          <div v-if="dossier.room_messages.length" class="dossier-list">
            <div v-for="(m, idx) in dossier.room_messages" :key="idx" class="dossier-item">
              <a-tag>{{ m.sender_type }}: {{ m.sender_id || '—' }}</a-tag>
              <span class="dossier-dim">{{ m.content_summary }}</span>
            </div>
          </div>
          <a-empty v-else :description="t('collab.dossierEmpty')" />
        </template>
      </a-spin>
    </GlassPanel>

    <!-- Initiate collaboration drawer -->
    <a-drawer v-model:open="showInitiate" :title="t('collab.initiate')" placement="right" width="520" :keyboard="!membersOpen" :body-style="{ padding: '20px 24px' }">
      <a-steps :current="initStep" size="small" style="margin-bottom: 24px">
        <a-step :title="t('collab.templates')" />
        <a-step :title="t('collab.members')" />
        <a-step :title="t('collab.basicInfo')" />
        <a-step :title="t('common.confirm')" />
      </a-steps>

      <!-- Step 1: Select template -->
      <div v-if="initStep === 0">
        <a-spin :spinning="loading">
          <a-empty v-if="!loading && templates.length === 0" :description="t('common.noData')" />
          <div v-else class="tpl-list">
            <div
              v-for="tpl in templates"
              :key="tpl.id"
              class="tpl-option"
              :class="{ selected: initForm.templateId === tpl.id }"
              @click="initForm.templateId = tpl.id"
            >
              <strong>{{ tpl.name }}</strong>
              <span class="tpl-desc">{{ tpl.description }}</span>
              <a-tag v-if="tpl.type" color="blue">{{ tpl.type }}</a-tag>
            </div>
          </div>
        </a-spin>
        <p v-if="!initForm.templateId" class="wizard-hint">{{ t('collab.wizardNeedTemplate') }}</p>
      </div>

      <!-- Step 2: Configure participants -->
      <div v-if="initStep === 1">
        <a-form layout="vertical">
          <a-form-item :label="t('collab.members')">
            <!-- 成员下拉展开时，抽屉 :keyboard 临时置 false（见上）：Esc 只收起下拉、不关抽屉；
                 下拉收起后恢复 Esc 关抽屉能力。 -->
            <a-select
              v-model:value="initForm.participants"
              mode="multiple"
              :options="agentStore.agentOptions"
              option-filter-prop="label"
              :placeholder="t('collab.membersPlaceholder')"
              style="width: 100%"
              @dropdown-visible-change="onMembersDropdownChange"
            />
          </a-form-item>
        </a-form>
      </div>

      <!-- Step 3: Parameters -->
      <div v-if="initStep === 2">
        <a-form layout="vertical">
          <a-form-item :label="t('common.name')">
            <a-input v-model:value="initForm.name" :placeholder="t('common.name')" />
          </a-form-item>
          <a-form-item :label="t('common.description')">
            <a-input v-model:value="initForm.description" type="textarea" :rows="3" :placeholder="t('common.description')" />
          </a-form-item>
        </a-form>
      </div>

      <!-- Step 4: Review -->
      <div v-if="initStep === 3">
        <p><strong>{{ t('common.name') }}:</strong> {{ initForm.name }}</p>
        <p><strong>{{ t('common.description') }}:</strong> {{ initForm.description }}</p>
        <p><strong>{{ t('collab.templates') }}:</strong> {{ selectedTemplateName }}</p>
        <p><strong>{{ t('collab.members') }}:</strong> {{ initForm.participants.join(', ') }}</p>
      </div>

      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <GlassButton v-if="initStep > 0" variant="secondary" size="sm" @click="initStep--">{{ t('common.prev') }}</GlassButton>
          <GlassButton v-if="initStep < 3" variant="primary" size="sm" :disabled="!canProceed" @click="initStep++">{{ t('common.next') }}</GlassButton>
          <GlassButton v-if="initStep === 3" variant="primary" size="sm" :loading="starting" @click="handleStart">{{ t('common.submit') }}</GlassButton>
        </div>
      </template>
    </a-drawer>

    <!-- 编辑已发起的协作：名称/描述/成员/默认应答者 -->
    <a-drawer v-model:open="showEdit" :title="t('collab.editTitle')" placement="right" width="480" :body-style="{ padding: '20px 24px' }">
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="editForm.name" :placeholder="t('common.name')" />
        </a-form-item>
        <a-form-item :label="t('common.description')">
          <a-textarea v-model:value="editForm.description" :rows="2" :placeholder="t('common.description')" />
        </a-form-item>
        <a-form-item :label="t('collab.members')">
          <a-select v-model:value="editForm.members" mode="multiple" :options="agentStore.agentOptions" option-filter-prop="label" :placeholder="t('collab.membersPlaceholder')" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="t('collab.roomResponder')">
          <a-select v-model:value="editForm.responder" :options="agentStore.agentOptions" option-filter-prop="label" allow-clear :placeholder="t('collab.roomResponderPlaceholder')" style="width: 100%" />
        </a-form-item>
      </a-form>
      <template #footer>
        <div style="display: flex; gap: 8px; justify-content: flex-end">
          <GlassButton variant="secondary" size="sm" @click="showEdit = false">{{ t('common.cancel') }}</GlassButton>
          <GlassButton variant="primary" size="sm" :loading="editSaving" @click="saveEdit">{{ t('common.save') }}</GlassButton>
        </div>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { TeamOutlined, ThunderboltOutlined, HistoryOutlined } from '@ant-design/icons-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassCard from '@/components/GlassCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import GlassTable from '@/components/GlassTable.vue'
import { useCollaboration } from '@/composables/useCollaboration'
import { useAgentStore } from '@/stores/agents'
import { getRoom, updateRoom } from '@/api/modules/collaborationRoom'
import { getProjectCollaboration, type ProjectCollaboration } from '@/api/modules/collaboration'
import { listProjects } from '@/api/modules/projects'
import type { CollabSession, CollabTemplate } from '@/api/modules/collaboration'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const { sessions, templates, loading, loadSessions, loadTemplates, startSession } = useCollaboration()
// 成员候选 = 全站 agent 列表（App.vue 启动已 loadAgents；此处幂等兼底，TTL 缓存不重复拉）
const agentStore = useAgentStore()

// ── 视图过滤（history 并入本页：active/history/all）──
type ViewKey = 'active' | 'history' | 'all'
const validView = (v: unknown): ViewKey => (v === 'history' || v === 'all' ? v : 'active')
const view = ref<ViewKey>(validView(route.query.view))
const viewOptions = computed(() => [
  { label: t('collab.viewActive'), value: 'active' },
  { label: t('collab.viewHistory'), value: 'history' },
  { label: t('collab.viewAll'), value: 'all' },
])
function onViewChange(v: ViewKey) {
  router.replace({ query: { ...route.query, view: v } })
}
watch(
  () => route.query.view,
  (v) => {
    view.value = validView(v)
  },
)

const filteredSessions = computed(() => {
  const all = sessions.value as CollabSession[]
  if (view.value === 'all') return all
  if (view.value === 'history') return all.filter((s) => s.status !== 'active')
  return all.filter((s) => s.status === 'active')
})

// ── 状态 i18n 化 ──
const STATUS_LABEL_KEYS: Record<string, string> = {
  active: 'collab.statusActive',
  completed: 'collab.statusCompleted',
  failed: 'collab.statusFailed',
  paused: 'collab.statusPaused',
  archived: 'collab.statusArchived',
}
const STATUS_COLORS: Record<string, string> = {
  active: 'processing',
  completed: 'success',
  failed: 'error',
  paused: 'warning',
  archived: 'default',
}
function statusLabel(s: string): string {
  const key = STATUS_LABEL_KEYS[s]
  return key ? t(key) : s
}
function statusColor(s: string): string {
  return STATUS_COLORS[s] ?? 'default'
}

// ── 概览统计 ──
const stats = computed(() => {
  const all = sessions.value as CollabSession[]
  return [
    { key: 'total', label: t('common.total'), value: all.length, icon: TeamOutlined },
    { key: 'active', label: t('common.active'), value: all.filter((s) => s.status === 'active').length, icon: ThunderboltOutlined },
    { key: 'history', label: t('collab.history'), value: all.filter((s) => s.status !== 'active').length, icon: HistoryOutlined },
  ]
})

const columns = computed(() => [
  { title: t('common.name'), dataIndex: 'name', key: 'name' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
  { title: t('common.createdAt'), dataIndex: 'createdAt', key: 'createdAt' },
  { title: t('common.actions'), key: 'actions', width: 120 },
])

// ── 打开会话：进入群聊房间 ──
function handleViewSession(record: CollabSession) {
  router.push(`/collaboration/sessions/${record.id}`)
}

// ── 编辑已发起的协作 ──
const showEdit = ref(false)
const editRoomId = ref('')
const editSaving = ref(false)
const editForm = reactive({ name: '', description: '', members: [] as string[], responder: '' })

async function openEdit(record: CollabSession) {
  editRoomId.value = record.id
  editForm.name = record.name || ''
  editForm.description = record.description || ''
  editForm.members = [...(record.participants || [])]
  editForm.responder = ''
  showEdit.value = true
  try {
    const info = await getRoom(record.id)
    editForm.members = info.members.map((m) => m.id)
    editForm.responder = info.responder_agent_id || ''
  } catch {
    /* 拉取失败则保留列表预填 */
  }
}

async function saveEdit() {
  if (editSaving.value) return
  editSaving.value = true
  try {
    await updateRoom(editRoomId.value, {
      name: editForm.name,
      description: editForm.description,
      members: editForm.members,
      responder_agent_id: editForm.responder,
    })
    showEdit.value = false
    await loadSessions()
  } finally {
    editSaving.value = false
  }
}

// ── 发起协作向导 ──
const showInitiate = ref(false)
// 成员下拉是否展开：展开时临时禁用抽屉的 Esc 关闭，让 Esc 只收起下拉。
const membersOpen = ref(false)
function onMembersDropdownChange(open: boolean) {
  membersOpen.value = open
}
const initStep = ref(0)
const starting = ref(false)
const initForm = reactive({ templateId: '', participants: [] as string[], name: '', description: '' })
// 向导校验：第 0 步（协作模板）必须选中模板才能前进（否则后端只会建通用 "New Collaboration"）。
const canProceed = computed(() => initStep.value !== 0 || !!initForm.templateId)
const selectedTemplateName = computed(
  () => (templates.value as CollabTemplate[]).find((tpl) => tpl.id === initForm.templateId)?.name ?? '-',
)

async function handleStart() {
  if (!initForm.templateId) return // 防御：无模板不放行提交
  starting.value = true
  try {
    const ok = await startSession({
      templateId: initForm.templateId,
      participants: initForm.participants,
      name: initForm.name,
      description: initForm.description,
    })
    if (ok) {
      showInitiate.value = false
      initStep.value = 0
      initForm.templateId = ''
      initForm.participants = []
      initForm.name = ''
      initForm.description = ''
    }
  } finally {
    starting.value = false
  }
}

onMounted(() => {
  loadSessions()
  loadTemplates()
  agentStore.loadAgents()
  loadDossierProjectOptions()
})

// ── S12 项目协作档案：按项目聚合五类记录（消息/run/事件/候选/审批）──
const dossierProjectId = ref<string>()
const dossierProjectOptions = ref<Array<{ label: string; value: string }>>([])
const dossier = ref<ProjectCollaboration | null>(null)
const dossierLoading = ref(false)

const dossierRecentEvents = computed(() => (dossier.value?.events ?? []).slice(-20).reverse())

const dossierRunColumns = computed(() => [
  { title: 'subagent_id', dataIndex: 'subagent_id', key: 'subagent_id' },
  { title: t('collab.members'), dataIndex: 'agent_id', key: 'agent_id' },
  { title: t('common.status'), dataIndex: 'status', key: 'status' },
  { title: t('collab.dossierTeam'), dataIndex: 'team_id', key: 'team_id' },
  { title: t('common.description'), dataIndex: 'task_summary', key: 'task_summary' },
])

function candidateColor(status: string): string {
  if (status === 'accepted') return 'success'
  if (status === 'rejected') return 'error'
  if (status === 'reviseRequired') return 'warning'
  return 'processing'
}

async function loadDossierProjectOptions() {
  try {
    const res: any = await listProjects()
    const items = Array.isArray(res?.data) ? res.data : []
    dossierProjectOptions.value = items.map((p: any) => ({
      label: p.name || p.project_id,
      value: p.project_id,
    }))
  } catch {
    /* 项目列表失败不阻断页面，选择器留空 */
  }
}

async function loadDossier() {
  if (!dossierProjectId.value) {
    dossier.value = null
    return
  }
  dossierLoading.value = true
  try {
    const res: any = await getProjectCollaboration(dossierProjectId.value)
    dossier.value = res?.data ?? null
  } catch {
    dossier.value = null
  } finally {
    dossierLoading.value = false
  }
}
</script>

<style scoped>
.collab-page { display: flex; flex-direction: column; gap: 24px; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; }
.page-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.page-subtitle { color: var(--nr-text-secondary); font-size: 14px; margin: 4px 0 0; }
.stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.stat-content { display: flex; justify-content: space-between; align-items: center; }
.stat-value { font-family: var(--nr-font-display); font-size: 24px; font-weight: 700; color: var(--nr-text-primary); }
.stat-icon { font-size: 20px; color: var(--nr-text-tertiary); }
.list-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; gap: 12px; }
.list-header .section-title { margin: 0; }
.section-title { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 600; font-size: 16px; }
.session-detail { display: flex; flex-direction: column; gap: 10px; }
.session-detail p { color: var(--nr-text-secondary); font-size: 14px; margin: 0; }
.tpl-list { display: flex; flex-direction: column; gap: 8px; }
.tpl-option { padding: 12px 16px; border: 1px solid var(--nr-glass-border); border-radius: 10px; cursor: pointer; transition: all 0.2s; display: flex; flex-direction: column; gap: 4px; }
.tpl-option:hover { border-color: var(--nr-primary-light); background: rgba(99,102,241,0.05); }
.tpl-option.selected { border-color: var(--nr-primary); background: rgba(99,102,241,0.1); }
.tpl-desc { font-size: 13px; color: var(--nr-text-tertiary); }
.wizard-hint { margin: 12px 0 0; font-size: 12px; color: var(--nr-text-secondary); }
/* ── S12 项目协作档案 ── */
.dossier-counts { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.dossier-summary { padding: 12px 16px; border: 1px solid var(--nr-glass-border); border-radius: 10px; margin-bottom: 16px; }
.dossier-sub-title { color: var(--nr-text-primary); font-weight: 600; font-size: 14px; margin: 16px 0 8px; }
.dossier-dim { color: var(--nr-text-tertiary); font-size: 13px; }
.dossier-mono { font-family: var(--nr-font-mono, monospace); font-size: 13px; color: var(--nr-text-primary); }
.dossier-timeline { margin-top: 8px; }
.dossier-list { display: flex; flex-direction: column; gap: 6px; }
.dossier-item { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
