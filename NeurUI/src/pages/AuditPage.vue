<template>
  <div class="audit-page">
    <div class="page-header">
      <h2 class="page-title">{{ t('system.audit') }}</h2>
      <GlassButton variant="secondary" size="sm" :loading="exporting" @click="exportAudit">{{ t('common.export') }}</GlassButton>
    </div>

    <!-- W12 追责查询面板 -->
    <GlassPanel class="panel" data-testid="accountability-panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="accountability-title">{{ t('ontology.accountabilityTitle') }}</span>
      </div>
      <div class="acc-filters">
        <a-input v-model:value="accSubject" size="small" :placeholder="t('ontology.accSubject')" style="width: 160px" data-testid="acc-subject" />
        <a-input v-model:value="accActor" size="small" :placeholder="t('ontology.accActor')" style="width: 160px" data-testid="acc-actor" />
        <GlassButton size="sm" :loading="accLoading" data-testid="acc-search" @click="runAccountability">
          {{ t('common.search') }}
        </GlassButton>
      </div>
      <div v-if="accError" class="acc-error" data-testid="acc-error">{{ accError }}</div>
      <div v-if="accResult" class="acc-result" data-testid="acc-result">
        <p class="acc-total">{{ t('ontology.accTotal', { count: accResult.total }) }}</p>
        <table class="acc-table">
          <thead><tr>
            <th>{{ t('ontology.accLedger') }}</th><th>{{ t('ontology.accWho') }}</th>
            <th>{{ t('ontology.accWhen') }}</th><th>{{ t('ontology.accAction') }}</th>
            <th>{{ t('ontology.accOutcome') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="(e, i) in accResult.events.slice(0, 20)" :key="i">
              <td class="acc-ledger">{{ e.ledger }}</td>
              <td>{{ e.who }}</td>
              <td class="acc-when">{{ e.when }}</td>
              <td>{{ e.action }}</td>
              <td>{{ e.outcome }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </GlassPanel>

    <!-- W12 防篡改验证 -->
    <GlassPanel class="panel" data-testid="digest-verify-panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="digest-title">{{ t('ontology.digestVerifyTitle') }}</span>
        <GlassButton size="sm" :loading="verifyLoading" data-testid="digest-run" @click="runVerify">
          {{ t('ontology.digestVerifyBtn') }}
        </GlassButton>
      </div>
      <div v-if="verifyResult" class="verify-result" data-testid="digest-result">
        <span :class="verifyResult.ok ? 'verify-pass' : 'verify-fail'" data-testid="digest-status">
          {{ verifyResult.ok ? t('ontology.digestPass') : t('ontology.digestBroken') }}
        </span>
        <span class="mono">chains={{ verifyResult.chains }} rows={{ verifyResult.rows }}</span>
      </div>
    </GlassPanel>

    <!-- U7：待审批行——展开动作语义引用（W4 联动；读数面不裁决） -->
    <GlassPanel class="panel" data-testid="pending-approvals-panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="pending-approvals-title">{{ t('ontology.approvalsPanelTitle') }}</span>
        <GlassButton size="sm" :loading="approvalsLoading" data-testid="approvals-refresh" @click="fetchPendingApprovals">
          {{ t('common.refresh') }}
        </GlassButton>
      </div>
      <a-empty v-if="!pendingApprovals.length" :description="t('ontology.approvalsEmpty')" />
      <a-table v-else size="small" row-key="request_id" :data-source="pendingApprovals"
               :pagination="false" data-testid="approvals-table">
        <a-table-column key="command" :title="t('ontology.approvalCommand')" data-index="command" />
        <a-table-column key="user_id" :title="t('ontology.approvalUser')" data-index="user_id" />
        <a-table-column key="created_at" :title="t('ontology.approvalCreatedAt')" data-index="created_at" />
        <template #expandedRowRender="{ record }">
          <div class="approval-expand" data-testid="approval-expand">
            <p v-if="record.danger_reason" class="approval-reason">
              {{ t('ontology.approvalReason') }}: {{ record.danger_reason }}
            </p>
            <template v-if="actionOfRequest(record)">
              <p class="mono">
                {{ t('ontology.approvalActionPrecondition') }}:
                <code>{{ JSON.stringify(actionOfRequest(record)?.precondition ?? {}) }}</code>
              </p>
              <p class="mono">
                {{ t('ontology.approvalActionImpact') }}:
                <code>{{ (actionOfRequest(record)?.impact ?? []).join('; ') || '-' }}</code>
              </p>
            </template>
            <p v-else class="approval-no-action">{{ t('ontology.approvalNoAction') }}</p>
          </div>
        </template>
      </a-table>
    </GlassPanel>

    <!-- S8 审批审计轨迹：按 runId 成对拉取请求+决定（后端 admin 门，级别/时间窗为前端过滤） -->
    <GlassPanel class="panel" data-testid="approval-audit-panel">
      <div class="panel-head">
        <span class="panel-title" data-testid="approval-audit-title">{{ t('audit.approvalTrajectoryTitle') }}</span>
        <GlassButton size="sm" :loading="approvalAuditLoading" data-testid="approval-audit-search" @click="runApprovalAudit">
          {{ t('common.search') }}
        </GlassButton>
      </div>
      <div class="acc-filters">
        <a-input v-model:value="approvalAuditRunId" size="small" :placeholder="t('audit.approvalRunId')" style="width: 220px" data-testid="approval-audit-runid" allow-clear />
        <a-select v-model:value="approvalAuditLevel" size="small" :placeholder="t('audit.approvalAuditLevel')" style="width: 110px" allow-clear data-testid="approval-audit-level">
          <a-select-option value="L0">L0</a-select-option>
          <a-select-option value="L1">L1</a-select-option>
          <a-select-option value="L2">L2</a-select-option>
        </a-select>
        <a-range-picker v-model:value="approvalAuditRange" size="small" show-time style="width: 320px" data-testid="approval-audit-range" />
      </div>
      <a-empty v-if="!approvalAuditItems.length" :description="t('audit.approvalAuditEmpty')" />
      <a-table v-else :columns="approvalAuditColumns" :data-source="approvalAuditItems" row-key="request_id" :pagination="false" size="small" data-testid="approval-audit-table">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'decided' ? 'green' : 'orange'">
              {{ record.status === 'decided' ? t('audit.approvalAuditDecided') : t('audit.approvalAuditPending') }}
            </a-tag>
          </template>
          <template v-if="column.key === 'requested_at'">
            <span class="acc-when">{{ record.requested_at ? formatTimestampText(record.requested_at) : '—' }}</span>
          </template>
          <template v-if="column.key === 'decided_at'">
            <span class="acc-when">{{ record.decided_at ? formatTimestampText(record.decided_at) : '—' }}</span>
          </template>
          <template v-if="column.key === 'latency_ms'">
            <span class="mono">{{ record.latency_ms == null ? '—' : `${record.latency_ms} ms` }}</span>
          </template>
          <!-- D1 记忆式放行徽标：decision_source/decided_by 标记命中时提示该决定来自授权单 -->
          <template v-if="column.key === 'decided_by'">
            <span class="acc-decider">
              <a-tooltip v-if="memoryGrantOf(record)" :title="memoryGrantTitleOf(record, t)">
                <a-tag class="memory-grant-chip" data-testid="approval-memory-grant">{{ t('audit.memoryGrantBadge') }}</a-tag>
              </a-tooltip>
              <span>{{ record.decided_by || '—' }}</span>
            </span>
          </template>
        </template>
        <template #expandedRowRender="{ record }">
          <div class="approval-expand" data-testid="approval-audit-expand">
            <p class="mono">request_id: <code>{{ record.request_id }}</code></p>
            <p v-if="record.reason" class="mono">{{ t('audit.approvalAuditReason') }}: {{ record.reason }}</p>
            <p v-if="record.effective_level" class="mono">{{ t('audit.approvalAuditEffectiveLevel') }}: {{ record.effective_level }}</p>
            <p v-if="record.request_event" class="mono">{{ t('audit.approvalAuditRequestEvent') }}: <code>{{ JSON.stringify(record.request_event) }}</code></p>
            <p v-else class="approval-no-action">{{ t('audit.approvalAuditNoRequestEvent') }}</p>
            <p v-if="record.decision_event" class="mono">{{ t('audit.approvalAuditDecisionEvent') }}: <code>{{ JSON.stringify(record.decision_event) }}</code></p>
          </div>
        </template>
      </a-table>
    </GlassPanel>

    <!-- Filters -->
    <GlassCard>
      <div class="filters-row">
        <a-input v-model:value="filters.user" :placeholder="t('nav.users')" style="width: 150px" allow-clear />
        <a-select v-model:value="filters.action" :placeholder="t('common.actions')" style="width: 150px" allow-clear>
          <a-select-option value="create">{{ t('system.create') }}</a-select-option>
          <a-select-option value="update">{{ t('system.update') }}</a-select-option>
          <a-select-option value="delete">{{ t('system.delete') }}</a-select-option>
          <a-select-option value="login">{{ t('system.login') }}</a-select-option>
          <a-select-option value="logout">{{ t('system.logout') }}</a-select-option>
        </a-select>
        <a-range-picker v-model:value="filters.dateRange" show-time style="width: 360px" />
        <GlassButton variant="primary" size="sm" :loading="loading" @click="fetchAudit">{{ t('common.search') }}</GlassButton>
      </div>
    </GlassCard>

    <!-- Audit statistics -->
    <div class="stats-grid" style="margin-top: 16px">
      <GlassStatCard :label="t('common.total')" :value="stats.total ?? 0" emoji="📋" />
      <GlassStatCard :label="t('system.today')" :value="stats.today ?? 0" emoji="📅" />
      <GlassStatCard :label="t('system.warnings')" :value="stats.warnings ?? 0" emoji="⚠️" />
      <GlassStatCard :label="t('system.waitingHuman')" :value="waitingHuman" emoji="⏳" />
      <GlassStatCard :label="t('system.longestWaitMinutes')" :value="longestWaitMinutes" emoji="⌛" />
      <GlassStatCard :label="t('system.ingressBypass')" :value="ingressBypass" emoji="↩️" />
    </div>

    <!-- Audit table -->
    <GlassCard v-if="records.length > 0 || loading" style="margin-top: 16px">
      <a-table
        :columns="columns"
        :data-source="records"
        :loading="loading"
        :locale="{ emptyText: '' }"
        row-key="id"
        :pagination="{ current: page, pageSize: pageSize, total, showSizeChanger: true, onChange: onPageChange }"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'timestamp'">
            <span class="audit-time">{{ formatTimestampText(record.timestamp) }}</span>
          </template>
          <template v-if="column.key === 'action'">
            <a-tag :color="actionColor(record.action)">{{ record.action }}</a-tag>
          </template>
          <template v-if="column.key === 'user'">
            <span class="audit-user">{{ record.user }}</span>
          </template>
          <template v-if="column.key === 'resource'">
            <span class="audit-resource">{{ record.resource }}</span>
          </template>
          <template v-if="column.key === 'details'">
            <a-tooltip v-if="record.details" :title="JSON.stringify(record.details)">
              <span class="audit-details">{{ t('system.view') }}</span>
            </a-tooltip>
            <span v-else class="text-muted">-</span>
          </template>
        </template>
      </a-table>
    </GlassCard>
    <GlassCard v-else style="margin-top: 16px">
      <a-empty :description="t('common.noData')" />
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { queryOntologyAccountability, verifyDigestChain, listOntologyActions } from '@/api/modules/ontology'
import type { OntologyActionRow } from '@/types/ontology'
import { useI18n } from 'vue-i18n'
import { listAuditRecords, exportAudit as exportAuditApi, getApprovalTrajectory } from '@/api/modules/audit'
import type { ApprovalTrajectoryItem } from '@/api/modules/audit'
import { getDesktopAuditWaiting, getIngressBypassStats, getPendingApprovals } from '@/api/modules/governance'
import { mergeWaitingHuman } from '@/utils/waitingHuman'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import { formatTimestampText } from '@/utils/displayText'
import { memoryGrantOf, memoryGrantTitleOf } from '@/utils/approvalGrant'

const { t } = useI18n()

const loading = ref(false)
const exporting = ref(false)
const records = ref<any[]>([])
const stats = ref<Record<string, any>>({})
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
/** 待人队列读数（N-3）：几条、最久等多久；取不到时留痕，卡片保持 0。 */
const waitingHuman = ref(0)
const longestWaitMinutes = ref(0)
/** 入站旁路直发读数（批 D）：队列可用性的事实判据；独立卡片，不混入"待人"。 */
const ingressBypass = ref(0)

const filters = ref<{ user: string; action: string | undefined; dateRange: any }>({
  user: '',
  action: undefined,
  dateRange: null,
})

const columns = computed(() => [
  { title: t('common.createdAt'), key: 'timestamp', width: 180 },
  { title: t('nav.users'), key: 'user', width: 120 },
  { title: t('common.actions'), key: 'action', width: 100 },
  { title: t('system.resource'), key: 'resource', width: 140 },
  { title: t('system.details'), key: 'details', width: 80 },
])

const actionColor = (action: string) => {
  const map: Record<string, string> = { create: 'green', update: 'blue', delete: 'red', login: 'cyan', logout: 'default' }
  return map[action] || 'default'
}


const accSubject = ref('')
const accActor = ref('')
const accLoading = ref(false)
const accError = ref('')
const accResult = ref<{ events: Array<Record<string, unknown>>; total: number } | null>(null)
const verifyLoading = ref(false)
const verifyResult = ref<{ ok: boolean; chains: number; rows: number } | null>(null)

// U7：待审批行展开——动作语义（precondition/impact）引用（W4 联动；读数面不裁决）
const pendingApprovals = ref<Array<Record<string, any>>>([])
const ontologyActions = ref<OntologyActionRow[]>([])
const approvalsLoading = ref(false)

async function fetchPendingApprovals() {
  approvalsLoading.value = true
  try {
    const res: any = await getPendingApprovals()
    pendingApprovals.value = res?.data?.requests ?? []
  } catch {
    pendingApprovals.value = []
  } finally {
    approvalsLoading.value = false
  }
}

async function fetchOntologyActions() {
  try {
    const res: any = await listOntologyActions()
    ontologyActions.value = res?.data ?? []
  } catch {
    ontologyActions.value = []
  }
}

/** 审批请求 → 关联动作（metadata.action_id；无关联如实回落） */
function actionOfRequest(req: Record<string, any>): OntologyActionRow | undefined {
  const actionId = String(req?.metadata?.action_id ?? '')
  return ontologyActions.value.find((a) => a.action_id === actionId)
}

// ── S8 审批审计轨迹：runId 必填（审计按 run 成对拉取，无 run 即无轨迹），
// 级别/时间窗是前端过滤——后端只按 run_id 索引查询，不伪造服务端筛选。
const approvalAuditRunId = ref('')
const approvalAuditLevel = ref<string | undefined>(undefined)
const approvalAuditRange = ref<any>(null)
const approvalAuditLoading = ref(false)
const approvalAuditRaw = ref<ApprovalTrajectoryItem[]>([])

async function runApprovalAudit() {
  const runId = approvalAuditRunId.value.trim()
  if (!runId) {
    message.warning(t('audit.approvalRunIdRequired'))
    return
  }
  approvalAuditLoading.value = true
  try {
    const res: any = await getApprovalTrajectory(runId)
    approvalAuditRaw.value = res?.data?.requests ?? []
  } catch {
    // 403（非 admin）等故障如实置空并报错，不拿空列表冒充"无审批"
    approvalAuditRaw.value = []
    message.error(t('common.error'))
  } finally {
    approvalAuditLoading.value = false
  }
}

const approvalAuditItems = computed(() => approvalAuditRaw.value.filter((row) => {
  if (approvalAuditLevel.value && String(row.level ?? '') !== approvalAuditLevel.value) return false
  if (approvalAuditRange.value?.length === 2) {
    const start = approvalAuditRange.value[0].valueOf()
    const end = approvalAuditRange.value[1].valueOf()
    const ts = row.requested_at ? new Date(row.requested_at).valueOf() : Number.NaN
    if (Number.isNaN(ts) || ts < start || ts > end) return false
  }
  return true
}))

const approvalAuditColumns = computed(() => [
  { title: t('audit.approvalAuditLevel'), dataIndex: 'level', key: 'level', width: 70 },
  { title: t('audit.approvalAuditStatus'), key: 'status', width: 90 },
  { title: t('common.actions'), dataIndex: 'operation', key: 'operation' },
  { title: t('audit.approvalAuditRequested'), key: 'requested_at', width: 150 },
  { title: t('audit.approvalAuditDecidedAt'), key: 'decided_at', width: 150 },
  { title: t('audit.approvalAuditDecision'), dataIndex: 'decision', key: 'decision', width: 90 },
  { title: t('audit.approvalAuditDecidedBy'), dataIndex: 'decided_by', key: 'decided_by', width: 120 },
  { title: t('audit.approvalAuditLatency'), key: 'latency_ms', width: 100 },
])

async function runAccountability() {
  accError.value = ''
  accResult.value = null
  accLoading.value = true
  try {
    const res = await queryOntologyAccountability({
      subject: accSubject.value || undefined,
      actor: accActor.value || undefined,
    })
    accResult.value = res.data ?? null
  } catch {
    accError.value = t('ontology.accLoadError')
  } finally {
    accLoading.value = false
  }
}

async function runVerify() {
  verifyLoading.value = true
  verifyResult.value = null
  try {
    const res = await verifyDigestChain()
    verifyResult.value = res.data as unknown as typeof verifyResult.value
  } catch {
    verifyResult.value = { ok: false, chains: 0, rows: 0 }
  } finally {
    verifyLoading.value = false
  }
}

const fetchAudit = async () => {
  loading.value = true
  try {
    const params: any = { page: page.value, page_size: pageSize.value }
    if (filters.value.user) params.user = filters.value.user
    if (filters.value.action) params.action = filters.value.action
    if (filters.value.dateRange?.length === 2) {
      params.start = filters.value.dateRange[0].toISOString()
      params.end = filters.value.dateRange[1].toISOString()
    }

    const res = await listAuditRecords(params)
    const data = res?.data
    records.value = data?.items ?? (Array.isArray(data) ? data : [])
    total.value = data?.total ?? records.value.length
    stats.value = data?.stats ?? { total: total.value, today: 0, warnings: 0 }
  } catch {
    message.error(t('common.error'))
  } finally {
    loading.value = false
  }
}

const exportAudit = async () => {
  exporting.value = true
  try {
    const res: any = await exportAuditApi()
    const blob = new Blob([res], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'audit-export.json'
    a.click()
    URL.revokeObjectURL(url)
    message.success(t('common.success'))
  } catch {
    message.error(t('common.error'))
  } finally {
    exporting.value = false
  }
}

const onPageChange = (p: number, ps: number) => { page.value = p; pageSize.value = ps; fetchAudit() }

const fetchWaitingHuman = async () => {
  // 两个待人来源并行取；任一失败保留另一来源并留痕，不把"取不到"静默读成 0。
  const [auditRes, approvalsRes, bypassRes] = await Promise.allSettled([
    getDesktopAuditWaiting(),
    getPendingApprovals(),
    getIngressBypassStats(),
  ])
  if (auditRes.status === 'rejected') {
    console.error(
      `[waitingHuman] 桌面审计读数失败 HTTP ${auditRes.reason?.response?.status ?? '网络异常'}`,
      auditRes.reason,
    )
  }
  if (approvalsRes.status === 'rejected') {
    console.error(
      `[waitingHuman] 审批待办读数失败 HTTP ${approvalsRes.reason?.response?.status ?? '网络异常'}`,
      approvalsRes.reason,
    )
  }

  const waiting = auditRes.status === 'fulfilled' ? auditRes.value?.data?.waiting_human : null
  const auditSource = waiting
    ? {
        count: Number(waiting.count ?? 0),
        oldestWaitSeconds: Number(waiting.oldest_wait_seconds ?? 0),
      }
    : null
  const requests = approvalsRes.status === 'fulfilled'
    ? (approvalsRes.value?.data?.requests ?? [])
    : null

  if (bypassRes.status === 'rejected') {
    console.error(
      `[waitingHuman] 旁路直发读数失败 HTTP ${bypassRes.reason?.response?.status ?? '网络异常'}`,
      bypassRes.reason,
    )
  }
  const summary = mergeWaitingHuman(
    auditSource,
    requests ? requests.map((req: any) => req.created_at) : null,
  )
  waitingHuman.value = summary.count
  longestWaitMinutes.value = Math.floor(summary.oldestWaitSeconds / 60)
  // 旁路计数独立呈现：机器事件不冒充"人在等"（口径修正，随格入档 §6-488）
  if (bypassRes.status === 'fulfilled') {
    ingressBypass.value = Number(bypassRes.value?.data?.total ?? 0)
  }
}

onMounted(() => {
  void fetchAudit()
  void fetchWaitingHuman()
  void fetchPendingApprovals()
  void fetchOntologyActions()
})
</script>

<style scoped>
.audit-page { display: flex; flex-direction: column; gap: 16px; }
.page-title { font-family: var(--nr-font-display); font-size: 22px; font-weight: 700; color: var(--nr-text-primary); margin: 0; }
.page-header { display: flex; justify-content: space-between; align-items: center; }
.filters-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }
.audit-time { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-tertiary); }
.audit-user { font-weight: 500; color: var(--nr-text-primary); }
.audit-resource { font-family: var(--nr-font-mono); font-size: 12px; color: var(--nr-text-secondary); }
.audit-details { color: var(--nr-primary-light, #6366f1); cursor: pointer; font-size: 12px; }
.text-muted { color: var(--nr-text-muted); }
.acc-filters {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.acc-error {
  color: var(--nr-error, #ef4444);
  font-size: 12px;
}
.acc-total {
  font-size: 12px;
  margin: 4px 0;
}
.acc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.acc-table th, .acc-table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid var(--nr-border, rgba(128, 128, 128, 0.2));
}
.acc-ledger { font-family: var(--nr-font-mono, monospace); font-size: 11px; }
.acc-when { font-size: 11px; color: var(--nr-text-secondary, rgba(128,128,128,0.7)); }
.verify-result { font-size: 12px; display: flex; gap: 12px; align-items: center; }
.verify-pass { color: var(--nr-success, #52c41a); font-weight: 600; }
.verify-fail { color: var(--nr-error, #ef4444); font-weight: 600; }
.mono { font-family: var(--nr-font-mono, monospace); font-size: 11px; }
.approval-expand { font-size: 12px; }
.approval-reason { color: var(--nr-warning); margin: 4px 0; }
.approval-no-action { color: var(--nr-text-tertiary); margin: 4px 0; }
/* D1 记忆式放行徽标：主色软底小签，颜色全部走既有令牌 */
.acc-decider { display: inline-flex; align-items: center; gap: 4px; }
.memory-grant-chip {
  margin: 0;
  font-size: 11px;
  line-height: 18px;
  color: var(--nr-primary-light, #818cf8);
  background: var(--nr-primary-soft, rgba(99, 102, 241, 0.12));
  border-color: var(--nr-primary-soft-border, rgba(99, 102, 241, 0.2));
}
.panel-head { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-weight: 600; font-size: 13px; color: var(--nr-text-primary); }
</style>
