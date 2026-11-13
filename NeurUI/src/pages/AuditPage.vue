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
import { listAuditRecords, exportAudit as exportAuditApi } from '@/api/modules/audit'
import { getDesktopAuditWaiting, getIngressBypassStats, getPendingApprovals } from '@/api/modules/governance'
import { mergeWaitingHuman } from '@/utils/waitingHuman'
import GlassCard from '@/components/GlassCard.vue'
import GlassStatCard from '@/components/GlassStatCard.vue'
import GlassButton from '@/components/GlassButton.vue'
import { message } from 'ant-design-vue'
import { formatTimestampText } from '@/utils/displayText'

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
.panel-head { display: flex; justify-content: space-between; align-items: center; }
.panel-title { font-weight: 600; font-size: 13px; color: var(--nr-text-primary); }
</style>
