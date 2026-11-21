<script setup lang="ts">
/**
 * RSI 进化审批面（工单 011）
 *
 * 这页存在的理由：自动调整失效时 RSI 会升级到人工提案，但提案此前只有 PENDING
 * 可见、且批准动作作用在"最后构造的那个 agent"上 —— 人工通道等于不存在。
 * 所以本页把三件事摆明：选哪个 agent、提案现在什么状态、批准之后是否真的生效。
 *
 * 部署阶段（rsi_phase）的写入口（R7）收敛到本页"运行参数"区——
 * 此前写归 SettingPage 治理卡片、读归本页，两处可改迟早漂移。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import GlassCard from '@/components/GlassCard.vue'
import { useAuthStore } from '@/stores/auth'
import {
  approveRsiProposal,
  getRsiStatus,
  listRsiProposals,
  rejectRsiProposal,
  listRsiGenerations,
  getCurrentBaselineGeneration,
  getRsiGeneration,
  getRsiGenerationLineage,
  type ProposalStateFilter,
  type RsiApproveEvidence,
  type RsiGeneration,
  type RsiGenerationSummary,
  type RsiProposal,
  type RsiStatus,
  approveImproverUpgrade,
} from '@/api/modules/rsiGovernance'
import { getGovernanceSettings, updateGovernanceSettings } from '@/api/modules/settings'
import { getEvolutionSettings, updateEvolutionSettings } from '@/api/modules/text-evolution'

const { t } = useI18n()
const auth = useAuthStore()

const FILTERS: ProposalStateFilter[] = ['all', 'pending', 'applied', 'rejected', 'rolled_back']

const agentId = ref('')
const stateFilter = ref<ProposalStateFilter>('all')
const status = ref<RsiStatus | null>(null)
const proposals = ref<RsiProposal[]>([])
const loading = ref(false)
/** 后端 503 的原因原文；不咽成"没有提案" */
const notReady = ref('')
/** 批准后的生效证据：proposal_id → { 装进去的技能 id, 注册表是否命中 } */
const evidence = ref<Record<string, { skillId: string; hit: boolean }>>({})
/** manifest 缺 tool_sequence 时由批准人补交（逗号分隔） */
const sequenceDraft = ref<Record<string, string>>({})

const approver = computed(() => auth.user?.username || 'admin')

/** 状态筛选的显示名 —— 键保持 `section.key` 两层结构（语言包一致性守卫的约定） */
const STATE_KEYS: Record<ProposalStateFilter, string> = {
  all: 'stateAll',
  pending: 'statePending',
  applied: 'stateApplied',
  rejected: 'stateRejected',
  rolled_back: 'stateRolledBack',
}

function stateLabel(item: ProposalStateFilter): string {
  return t(`rsiGovernance.${STATE_KEYS[item]}`)
}

/**
 * 参数活性读数（Issue #289 · 004 M3）的取值文案映射。
 *
 * `no_data` / `sparse` / `never_proposed` 必须各有一条独立文案 —— 折叠成
 * 同一个"未知"就把"判不了"和"从未提名"混成一件事，正是本仓在 success 三态上
 * 修过的同一病灶。
 */
const ACTIVITY_KEYS: Record<string, string> = {
  moving: 'paramActivityMoving',
  sparse: 'paramActivitySparse',
  never_proposed: 'paramActivityNeverProposed',
  no_data: 'paramActivityNoData',
}

function activityLabel(value: string | undefined): string {
  if (!value) return t('rsiGovernance.paramActivityNoData')
  return t(`rsiGovernance.${ACTIVITY_KEYS[value] || 'paramActivityNoData'}`)
}

/**
 * 响应拆包。
 *
 * `api` 的响应拦截器返回 `response.data`（即 `{code, data}` 这个 body），
 * 而声明处仍按 `ApiResponse<T>` 泛型写 —— 两者对不上，于是本仓库既有页面
 * 一律做"两层或一层都试"的拆包（见 SettingPage 的 `?.data?.data ?? ?.data`）。
 * 这里跟随同一口径，不再自造第三种解释。
 */
function unwrap<T>(res: unknown): T {
  const box = res as { data?: { data?: T } | T } | undefined
  const nested = (box?.data as { data?: T } | undefined)?.data
  return (nested ?? box?.data) as T
}

function errorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || (err as Error)?.message || String(err)
}

function hasExecutableSequence(proposal: RsiProposal): boolean {
  return /tool_sequence\s*:/.test(String(proposal.content || ''))
}

async function load() {
  loading.value = true
  notReady.value = ''
  const scoped = agentId.value || undefined
  try {
    const [statusResp, listResp] = await Promise.all([
      getRsiStatus(scoped),
      listRsiProposals({ state: stateFilter.value, agentId: scoped }),
    ])
    status.value = unwrap<RsiStatus>(statusResp)
    proposals.value = unwrap<{ proposals: RsiProposal[] }>(listResp).proposals
    // 覆写写口的目标回填：查看某 agent 状态后即可对其覆写（agent id 留空 = 默认 agent，
    // 回填状态面报告的实际 agent_id——覆写键不许空串，后端 422 拒）。
    if (!agentId.value && status.value?.agent_id) {
      agentId.value = status.value.agent_id
    }
  } catch (err) {
    status.value = null
    proposals.value = []
    notReady.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function approve(proposal: RsiProposal) {
  const sequence = (sequenceDraft.value[proposal.proposal_id] || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  try {
    const resp = await approveRsiProposal(proposal.proposal_id, {
      approvedBy: approver.value,
      toolSequence: sequence.length ? sequence : undefined,
      agentId: agentId.value || undefined,
    })
    const data = unwrap<RsiApproveEvidence>(resp)
    evidence.value = {
      ...evidence.value,
      [proposal.proposal_id]: { skillId: data.applied_skill_id || '', hit: !!data.registry_hit },
    }
    message.success(t('rsiGovernance.approveOk'))
    await load()
  } catch (err) {
    // 后端拒绝（not_supported / 回灌未成功）必须原样出声，不得记成已批准
    message.error(`${t('rsiGovernance.approveFailed')}：${errorText(err)}`)
  }
}

async function reject(proposal: RsiProposal) {
  try {
    await rejectRsiProposal(proposal.proposal_id, {
      reason: t('rsiGovernance.rejectReason'),
      agentId: agentId.value || undefined,
    })
    message.success(t('rsiGovernance.rejectOk'))
    await load()
  } catch (err) {
    message.error(`${t('rsiGovernance.rejectFailed')}：${errorText(err)}`)
  }
}

/** 三态读数的 tag 颜色与文案键（缺席必须说出原因——与后端三态纪律同形）。 */
function stateTagColor(state: string | undefined): string {
  if (state === 'measured') return 'success'
  if (state === 'insufficient_data') return 'warning'
  return 'default'
}

function stateText(state: string | undefined): string {
  if (state === 'measured') return t('rsiGovernance.stateMeasured')
  if (state === 'insufficient_data') return t('rsiGovernance.stateInsufficient')
  return t('rsiGovernance.stateUnevidenced')
}

/** 证据机器读数行（survey §10.2 批次的状态面八格＋升级可用性）。 */
interface EvidenceRow {
  key: string
  state?: string
  value: string
  reason?: string
}

const evidenceRows = computed<EvidenceRow[]>(() => {
  if (!status.value) return []
  const s = status.value
  const rows: EvidenceRow[] = []
  const push = (key: string, state: string | undefined, value: string, reason?: string) =>
    rows.push({ key, state, value, reason })

  const eo = s.eval_outcome
  push('evalOutcome', eo?.state,
    eo?.state === 'measured' ? String(eo.score ?? '—') : (eo?.reason || eo?.detail || '—'),
    eo?.state !== 'measured' ? (eo?.reason || eo?.detail) : undefined)

  const se = s.sealed_evidence
  push('sealed', se?.state,
    se?.state === 'measured'
      ? `${se.score}·${(se.covered_families ?? []).length}`
      : (se?.reason || '—'),
    se?.state !== 'measured' ? se?.reason : undefined)

  const pp = s.improver_paired_probe
  push('probe', pp?.state,
    pp?.state === 'measured'
      ? `Γ=${pp.score}·${t('rsiGovernance.pairsLabel')}=${pp.evidenced_pairs ?? 0}`
      : (pp?.reason || pp?.detail || '—'))

  const qc = s.quality_curves
  push('curves', qc?.state,
    qc?.state === 'measured'
      ? `${t('rsiGovernance.archiveBestLabel')}=${qc.archive_best}·${qc.curve.length}`
      : (qc?.state || '—'))

  const cv = s.cost_vector?.totals
  push('cost', undefined,
    cv ? `turns=${cv.turns ?? 0} / tokens=${cv.tokens ?? 0} / wall=${cv.wall_ms ?? 0}ms` : '—')

  const fc = s.pruner_failed_cost
  push('failedCost', undefined,
    fc ? `${fc.eliminated} / ${fc.total_realized_cost}` : '—')

  const cov = s.coverage
  push('coverage', undefined,
    cov ? `${cov.covered.length}/${cov.expected.length}${cov.alert ? ` · ${t('rsiGovernance.uncoveredLabel')}: ${cov.uncovered.join(', ')}` : ''}` : '—')

  const pr = s.proxy_reference_correlation
  push('correlation', pr?.state,
    pr?.state === 'measured' ? String(pr.score) : (pr?.detail || pr?.reason || '—'))

  const tr = s.transfer
  push('transfer', tr?.state,
    tr?.state === 'measured' ? `τ=${tr.score}` : (tr?.detail || tr?.reason || '—'))

  const cc = s.checkpoint_columns
  push('checkpoint', undefined,
    cc && cc.acceptance_rate != null
      ? `${t('rsiGovernance.acceptanceLabel')}=${cc.acceptance_rate}`
      : (Array.isArray(cc?.missing) && cc.missing.length ? `missing: ${cc.missing.join(', ')}` : '—'))

  return rows
})

const upgrade = computed(() => status.value?.improver_upgrade)
const approvingUpgrade = ref(false)


async function approveUpgrade() {
  approvingUpgrade.value = true
  try {
    await approveImproverUpgrade({ agentId: agentId.value || undefined, approvedBy: approver.value })
    message.success(t('rsiGovernance.upgradeApproveOk'))
    await load()
  } catch (err) {
    message.error(`${t('rsiGovernance.upgradeApproveFailed')}：${errorText(err)}`)
  } finally {
    approvingUpgrade.value = false
  }
}

// ── 运行参数（R7）─────────────────────────────────────────────
// 演化运行参数单点写入口：治理键走 /governance/settings，回滚持久化开关
// 走 /evolution/settings（EvolutionSettings 族）。面板可调的是参数值；
// 判据结构与禁改清单不进面板（裁判件边界不变，详案 §6-R7）。

/** 后端键缺省时的前端兜底只用于首帧渲染；未加载成功时提交被拦，不会覆盖线上配置。 */
const params = ref({
  rsi_phase: 0,
  metacog_gate_enabled: false,
  rsi_rollback_persistence_enabled: true,
  rsi_phase_min_applied: {} as Record<string, number>,
  rsi_canary_window_seconds: 300,
  max_error_rate: 0.2,
  min_success_rate_drop: 0.1,
})
/** agent 级相位覆写只读展示——覆写的写入口仍在治理设置面，不在此重复。 */
const overridesReadonly = ref<Record<string, number>>({})
const paramsLoaded = ref(false)
const savingParams = ref(false)

const minAppliedKeys = computed(() =>
  Object.keys(params.value.rsi_phase_min_applied).sort())

const overridesReadonlyText = computed(() => {
  const entries = Object.entries(overridesReadonly.value)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([agent, phase]) => `${agent}=${phase}`)
  return entries.length ? entries.join(', ') : t('rsiGovernance.overridesNone')
})

async function loadParams() {
  paramsLoaded.value = false
  try {
    const [govResp, evoResp] = await Promise.all([
      getGovernanceSettings(),
      getEvolutionSettings(),
    ])
    const gov = unwrap<Record<string, unknown>>(govResp) || {}
    const evo = unwrap<Record<string, unknown>>(evoResp) || {}
    const thresholds = (gov.rsi_canary_rollback_thresholds || {}) as Record<string, unknown>
    params.value.rsi_phase = Number(gov.rsi_phase ?? 0)
    params.value.metacog_gate_enabled = gov.metacog_gate_enabled === true
    params.value.rsi_phase_min_applied = {
      ...(gov.rsi_phase_min_applied as Record<string, number> || {}),
    }
    params.value.rsi_canary_window_seconds = Number(gov.rsi_canary_window_seconds ?? 300)
    params.value.max_error_rate = Number(thresholds.max_error_rate ?? 0.2)
    params.value.min_success_rate_drop = Number(thresholds.min_success_rate_drop ?? 0.1)
    overridesReadonly.value = {
      ...(gov.rsi_phase_overrides as Record<string, number> || {}),
    }
    params.value.rsi_rollback_persistence_enabled =
      evo.rsi_rollback_persistence_enabled !== false
    paramsLoaded.value = true
  } catch (err) {
    // 读数失败不冒充加载成功：提示行给出原因，提交被 saveParams 拦下
    // （与 SettingPage 的 F-12 同一纪律——拿前端默认值覆盖线上配置比失败更坏）。
    paramsLoaded.value = false
    console.error('[RsiGovernance] 运行参数读取失败:', err)
  }
}

/** 提交前前端校验：越界/非法值直接点名，不等后端 422。 */
function validateParams(): string {
  const p = params.value
  if (!Number.isInteger(p.rsi_phase) || p.rsi_phase < 0 || p.rsi_phase > 4) {
    return t('rsiGovernance.phaseInvalid')
  }
  if (!(p.rsi_canary_window_seconds >= 1)) {
    return t('rsiGovernance.canaryWindowInvalid')
  }
  for (const value of [p.max_error_rate, p.min_success_rate_drop]) {
    if (!(value >= 0 && value <= 1)) return t('rsiGovernance.canaryThresholdInvalid')
  }
  for (const count of Object.values(p.rsi_phase_min_applied)) {
    if (!Number.isInteger(count) || count < 0) return t('rsiGovernance.minAppliedInvalid')
  }
  return ''
}

async function saveParams() {
  if (!paramsLoaded.value) {
    message.warning(t('rsiGovernance.paramsNotLoaded'))
    return
  }
  const invalid = validateParams()
  if (invalid) {
    message.error(invalid)
    return
  }
  savingParams.value = true
  try {
    await updateGovernanceSettings({
      rsi_phase: params.value.rsi_phase,
      metacog_gate_enabled: params.value.metacog_gate_enabled,
      rsi_phase_min_applied: { ...params.value.rsi_phase_min_applied },
      rsi_canary_window_seconds: params.value.rsi_canary_window_seconds,
      rsi_canary_rollback_thresholds: {
        max_error_rate: params.value.max_error_rate,
        min_success_rate_drop: params.value.min_success_rate_drop,
      },
    })
    await updateEvolutionSettings({
      rsi_rollback_persistence_enabled: params.value.rsi_rollback_persistence_enabled,
    })
    message.success(t('rsiGovernance.paramsSaveOk'))
    await loadParams()
  } catch (err) {
    message.error(`${t('rsiGovernance.paramsSaveFailed')}：${errorText(err)}`)
  } finally {
    savingParams.value = false
  }
}

// ── 世代谱系（P1-8，接 P1-5 四条只读端点）────────────────────
// 只读呈现：列表（limit/status 过滤）/单代详情/谱系链/当前基线代。
// 写面（审批、参数修改）归提案队列与 R5/R7 参数区，不在此重复建设。
// 诚实纪律：503 未装配与"账本空"分开呈现；基线代 404 如实说"尚无"，
// 不拿最大序号充数；门禁三态（passed/failed/unevidenced）不折叠。

const GEN_STATUSES = [
  'proposed',
  'shadowTesting',
  'gated',
  'canary',
  'deployed',
  'rejected',
  'rolledBack',
] as const
type GenStatusFilter = (typeof GEN_STATUSES)[number] | 'all'

const GEN_STATUS_KEYS: Record<(typeof GEN_STATUSES)[number], string> = {
  proposed: 'genStatusProposed',
  shadowTesting: 'genStatusShadowTesting',
  gated: 'genStatusGated',
  canary: 'genStatusCanary',
  deployed: 'genStatusDeployed',
  rejected: 'genStatusRejected',
  rolledBack: 'genStatusRolledBack',
}

const genStatusFilter = ref<GenStatusFilter>('all')
const genLimit = ref(20)
const generations = ref<RsiGenerationSummary[]>([])
const genLoading = ref(false)
/** 世代读面不可用的原因原文（503 未装配等）；不咽成"没有世代" */
const genNotReady = ref('')
/** 当前生产基线代；404 → genBaselineMissing（诚实呈现"尚无已部署代"） */
const currentBaseline = ref<RsiGeneration | null>(null)
const genBaselineMissing = ref(false)
/** 展开中的世代：详情 + 谱系链（点开才拉，列表不拖全量档案） */
const expandedGenNo = ref<number | null>(null)
const genDetail = ref<RsiGeneration | null>(null)
const genLineage = ref<RsiGeneration[]>([])
const genDetailError = ref('')
const genDetailLoading = ref(false)

const verdictKeys = computed(() => Object.keys(genDetail.value?.verdicts || {}).sort())

function genStatusLabel(status: string): string {
  const key = GEN_STATUS_KEYS[status as (typeof GEN_STATUSES)[number]]
  return key ? t(`rsiGovernance.${key}`) : status
}

function genStatusColor(status: string): string {
  if (status === 'deployed') return 'success'
  if (status === 'canary' || status === 'shadowTesting') return 'processing'
  if (status === 'rejected' || status === 'rolledBack') return 'error'
  return 'default'
}

function genDecisionText(gen: RsiGenerationSummary | RsiGeneration): string {
  const d = gen.decision
  if (!d) return t('rsiGovernance.genDecisionNone')
  if (d.kind === 'approval') {
    return `${t('rsiGovernance.genDecisionApproval')}·${d.approver || '—'}`
  }
  if (d.kind === 'rejected') {
    return `${t('rsiGovernance.genDecisionRejected')}·${d.reason || '—'}`
  }
  return t('rsiGovernance.genDecisionAuto')
}

/** 门禁三态徽标：缺席/无证据必须与"未过"分色分文（与后端三态纪律同形） */
function verdictColor(state: string | undefined): string {
  if (state === 'passed') return 'success'
  if (state === 'failed') return 'error'
  return 'warning'
}

function verdictText(state: string | undefined): string {
  if (state === 'passed') return t('rsiGovernance.verdictPassed')
  if (state === 'failed') return t('rsiGovernance.verdictFailed')
  return t('rsiGovernance.verdictUnevidenced')
}

async function loadGenerations() {
  genLoading.value = true
  genNotReady.value = ''
  try {
    const resp = await listRsiGenerations({
      limit: genLimit.value,
      status: genStatusFilter.value === 'all' ? undefined : genStatusFilter.value,
      agentId: agentId.value || undefined,
    })
    generations.value = unwrap<{ generations: RsiGenerationSummary[]; count: number }>(resp).generations
  } catch (err) {
    generations.value = []
    genNotReady.value = errorText(err)
  }
  // 当前基线代单独取：404 是诚实事实（尚无 deployed 代），不当错误横幅
  currentBaseline.value = null
  genBaselineMissing.value = false
  try {
    const resp = await getCurrentBaselineGeneration(agentId.value || undefined)
    currentBaseline.value = unwrap<RsiGeneration>(resp)
  } catch {
    genBaselineMissing.value = true
  }
  genLoading.value = false
}

async function toggleGenDetail(gen: RsiGenerationSummary) {
  if (expandedGenNo.value === gen.generationNo) {
    expandedGenNo.value = null
    return
  }
  expandedGenNo.value = gen.generationNo
  genDetailLoading.value = true
  genDetailError.value = ''
  genDetail.value = null
  genLineage.value = []
  try {
    const [detailResp, lineageResp] = await Promise.all([
      getRsiGeneration(gen.generationNo, agentId.value || undefined),
      getRsiGenerationLineage(gen.generationNo, agentId.value || undefined),
    ])
    genDetail.value = unwrap<RsiGeneration>(detailResp)
    genLineage.value = unwrap<{ lineage: RsiGeneration[] }>(lineageResp).lineage
  } catch (err) {
    genDetailError.value = errorText(err)
  }
  genDetailLoading.value = false
}

onMounted(() => {
  load()
  loadParams()
  loadGenerations()
})
</script>

<template>
  <div class="rsi-governance-page">
    <GlassCard :title="t('rsiGovernance.title')">
      <p class="rsi-hint">{{ t('rsiGovernance.hint') }}</p>

      <div class="rsi-toolbar">
        <label>
          {{ t('rsiGovernance.agentLabel') }}
          <a-input
            v-model:value="agentId"
            data-testid="rsi-agent"
            :placeholder="t('rsiGovernance.agentPlaceholder')"
            class="rsi-agent-input"
          />
        </label>
        <label>
          {{ t('rsiGovernance.stateLabel') }}
          <a-select v-model:value="stateFilter" data-testid="rsi-state" class="rsi-state-select">
            <a-select-option v-for="item in FILTERS" :key="item" :value="item">
              {{ stateLabel(item) }}
            </a-select-option>
          </a-select>
        </label>
        <a-button data-testid="rsi-reload" :loading="loading" @click="load">
          {{ t('rsiGovernance.reload') }}
        </a-button>
      </div>

      <p v-if="notReady" class="rsi-not-ready" data-testid="rsi-not-ready">
        {{ t('rsiGovernance.notReady') }}：{{ notReady }}
      </p>

      <div v-if="status" class="rsi-status" data-testid="rsi-status">
        <span>{{ t('rsiGovernance.phaseLabel') }}:&nbsp;<a-tag data-testid="rsi-phase">{{ status.deployment_phase }}</a-tag>
          <a-tag v-if="status.phase_source" data-testid="rsi-phase-source" :color="status.phase_source === 'override' ? 'orange' : 'default'">
            {{ status.phase_source === 'override' ? t('rsiGovernance.phaseSourceOverride') : t('rsiGovernance.phaseSourceGlobal') }}
          </a-tag>
        </span>
        <span>
          {{ t('rsiGovernance.verdictLabel') }}:
          <a-tag>{{ status.phase_verdict?.state || '—' }}</a-tag>
          <em>{{ status.phase_verdict?.reason }}</em>
        </span>
        <!-- 落盘失败不得被读成"已晋升"（工单 005 的两态） -->
        <span v-if="status.phase_advanced" data-testid="rsi-persisted">
          {{ status.phase_persisted ? t('rsiGovernance.persistedYes') : t('rsiGovernance.persistedNo') }}
        </span>
        <span data-testid="rsi-pass-rate">
          {{ t('rsiGovernance.passRateLabel') }}: {{ (status.candidates?.pass_rate ?? 0).toFixed(2) }}
        </span>
        <span v-if="status.escalation?.verdict" data-testid="rsi-escalation">
          {{ t('rsiGovernance.escalationLabel') }}: {{ status.escalation.verdict.state }}
          <em>{{ status.escalation.verdict.reason }}</em>
        </span>
        <!-- 回执负债读数（Issue #289 · 003）：账本新增两列而界面看不到，
             就是"只写不读的字段"（AGENTS.md §2 功能与升级改造红线）。 -->
        <span v-if="status.debt" data-testid="rsi-debt">
          {{ t('rsiGovernance.debtLabel') }}:
          <a-tag data-testid="rsi-debt-outstanding">
            {{ status.debt.available === false
              ? t('rsiGovernance.paramActivityNoData')
              : ((status.debt.outstanding ?? 0) > 0 ? status.debt.outstanding : t('rsiGovernance.debtNone')) }}
          </a-tag>
          <em data-testid="rsi-debt-gate">
            {{ status.debt.next_step?.allow
              ? t('rsiGovernance.debtGateAllow')
              : `${t('rsiGovernance.debtGateBlock')}·${status.debt.next_step?.reason || '—'}` }}
          </em>
          <em v-if="status.debt.unknown_rows" data-testid="rsi-debt-legacy">
            {{ t('rsiGovernance.debtUnknownRows') }}: {{ status.debt.unknown_rows }}
          </em>
          <em v-if="status.debt.last_write_failure" data-testid="rsi-debt-write-failure">
            {{ t('rsiGovernance.debtWriteFailure') }}: {{ status.debt.last_write_failure }}
          </em>
        </span>
        <!-- 参数活性读数（Issue #289 · 004 M3）：三态不折叠，缺一态即看不到
             "从未提名"与"判不了"的区别。 -->
        <span v-if="status.parameter_activity" data-testid="rsi-param-activity">
          {{ t('rsiGovernance.paramActivityLabel') }}:
          <a-tag data-testid="rsi-param-activity-overall">
            {{ activityLabel(status.parameter_activity.overall) }}
          </a-tag>
        </span>
      </div>
    </GlassCard>

    <!-- 世代谱系（P1-8）：跨臂代际因果只读面（接 P1-5 四条端点）。
         列表只出摘要字段（序号/父代/状态/裁决/晋升时间），全量档案
         （信号/变更/门禁三态/部署）点开才拉；503 未装配与空账本分开
         呈现，基线代 404 如实说"尚无"（教义第 2 条：诚实形态）。 -->
    <GlassCard :title="t('rsiGovernance.genTitle')" data-testid="rsi-generations">
      <p class="rsi-hint">{{ t('rsiGovernance.genHint') }}</p>

      <div class="rsi-toolbar">
        <label>
          {{ t('rsiGovernance.genStatusLabel') }}
          <a-select v-model:value="genStatusFilter" data-testid="rsi-gen-status" class="rsi-state-select">
            <a-select-option value="all">{{ t('rsiGovernance.genStatusAll') }}</a-select-option>
            <a-select-option v-for="s in GEN_STATUSES" :key="s" :value="s">
              {{ genStatusLabel(s) }}
            </a-select-option>
          </a-select>
        </label>
        <label>
          {{ t('rsiGovernance.genLimitLabel') }}
          <a-input-number
            v-model:value="genLimit"
            :min="1"
            :max="500"
            :precision="0"
            data-testid="rsi-gen-limit"
            class="rsi-limit-input"
          />
        </label>
        <a-button data-testid="rsi-gen-reload" :loading="genLoading" @click="loadGenerations">
          {{ t('rsiGovernance.reload') }}
        </a-button>
      </div>

      <p v-if="genNotReady" class="rsi-not-ready" data-testid="rsi-gen-not-ready">
        {{ t('rsiGovernance.genNotReady') }}：{{ genNotReady }}
      </p>

      <template v-else>
        <div v-if="currentBaseline" class="rsi-baseline" data-testid="rsi-gen-baseline">
          <span>
            {{ t('rsiGovernance.genBaselineLabel') }}:
            <a-tag data-testid="rsi-gen-baseline-no">#{{ currentBaseline.generationNo }}</a-tag>
          </span>
          <span>
            <a-tag :color="genStatusColor(currentBaseline.status)">
              {{ genStatusLabel(currentBaseline.status) }}
            </a-tag>
          </span>
          <span v-if="currentBaseline.basisCommit">
            {{ t('rsiGovernance.genBasisCommit') }}: {{ currentBaseline.basisCommit }}
          </span>
          <span v-if="currentBaseline.deployment?.promotedAt">
            {{ t('rsiGovernance.genPromotedAt') }}: {{ currentBaseline.deployment.promotedAt }}
          </span>
        </div>
        <p v-else-if="genBaselineMissing" class="rsi-hint" data-testid="rsi-gen-baseline-none">
          {{ t('rsiGovernance.genBaselineNone') }}
        </p>

        <p v-if="!generations.length" class="rsi-hint" data-testid="rsi-gen-empty">
          {{ t('rsiGovernance.genEmpty') }}
        </p>
        <table v-if="generations.length" class="rsi-table" data-testid="rsi-gen-table">
          <thead>
            <tr>
              <th>{{ t('rsiGovernance.genColNo') }}</th>
              <th>{{ t('rsiGovernance.genColParent') }}</th>
              <th>{{ t('rsiGovernance.genColStatus') }}</th>
              <th>{{ t('rsiGovernance.genColDecision') }}</th>
              <th>{{ t('rsiGovernance.genColPromotedAt') }}</th>
              <th>{{ t('rsiGovernance.genColAction') }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="g in generations" :key="g.generationNo">
              <tr :data-testid="`rsi-gen-row-${g.generationNo}`" class="rsi-row">
                <td>#{{ g.generationNo }}</td>
                <td>{{ g.parentNo == null ? '—' : `#${g.parentNo}` }}</td>
                <td>
                  <a-tag
                    :color="genStatusColor(g.status)"
                    :data-testid="`rsi-gen-status-badge-${g.generationNo}`"
                  >
                    {{ genStatusLabel(g.status) }}
                  </a-tag>
                </td>
                <td>{{ genDecisionText(g) }}</td>
                <td>{{ g.promotedAt || '—' }}</td>
                <td>
                  <a-button
                    size="small"
                    :data-testid="`rsi-gen-detail-${g.generationNo}`"
                    @click="toggleGenDetail(g)"
                  >
                    {{ expandedGenNo === g.generationNo
                      ? t('rsiGovernance.genHideDetail')
                      : t('rsiGovernance.genDetail') }}
                  </a-button>
                </td>
              </tr>
              <tr v-if="expandedGenNo === g.generationNo">
                <td colspan="6">
                  <p v-if="genDetailLoading" class="rsi-hint">
                    {{ t('rsiGovernance.genDetailLoading') }}
                  </p>
                  <p v-else-if="genDetailError" class="rsi-not-ready" data-testid="rsi-gen-detail-error">
                    {{ genDetailError }}
                  </p>
                  <div v-else-if="genDetail" class="rsi-gen-detail" data-testid="rsi-gen-detail">
                    <div class="rsi-gen-meta">
                      <span v-if="genDetail.basisCommit">
                        {{ t('rsiGovernance.genBasisCommit') }}: {{ genDetail.basisCommit }}
                      </span>
                      <span v-if="genDetail.createdAt">
                        {{ t('rsiGovernance.genCreatedAt') }}: {{ genDetail.createdAt }}
                      </span>
                    </div>

                    <div class="rsi-gen-section" data-testid="rsi-gen-signals">
                      <strong>{{ t('rsiGovernance.genSignalsLabel') }}</strong>
                      <div v-for="(s, i) in genDetail.signals" :key="i" class="rsi-gen-line">
                        <a-tag>{{ s.kind }}</a-tag>
                        <span>{{ s.summary || s.ref || '—' }}</span>
                      </div>
                      <span v-if="!genDetail.signals?.length" class="rsi-hint">
                        {{ t('rsiGovernance.genNone') }}
                      </span>
                    </div>

                    <div class="rsi-gen-section" data-testid="rsi-gen-changes">
                      <strong>{{ t('rsiGovernance.genChangesLabel') }}</strong>
                      <div v-for="(c, i) in genDetail.changes" :key="i" class="rsi-gen-line">
                        <span class="rsi-gen-target">{{ c.targetId }}</span>
                        <a-tag v-if="c.kind">{{ c.kind }}</a-tag>
                        <em v-if="c.rationale">{{ c.rationale }}</em>
                      </div>
                      <span v-if="!genDetail.changes?.length" class="rsi-hint">
                        {{ t('rsiGovernance.genNone') }}
                      </span>
                    </div>

                    <div class="rsi-gen-section" data-testid="rsi-gen-verdicts">
                      <strong>{{ t('rsiGovernance.genVerdictsLabel') }}</strong>
                      <span v-for="k in verdictKeys" :key="k" class="rsi-gen-verdict">
                        <em>{{ k }}</em>
                        <a-tag
                          :color="verdictColor(genDetail.verdicts[k]?.state)"
                          :data-testid="`rsi-gen-verdict-${k}`"
                        >
                          {{ verdictText(genDetail.verdicts[k]?.state) }}
                        </a-tag>
                        <em v-if="genDetail.verdicts[k]?.reason">{{ genDetail.verdicts[k]?.reason }}</em>
                      </span>
                      <span v-if="!verdictKeys.length" class="rsi-hint">
                        {{ t('rsiGovernance.genNone') }}
                      </span>
                    </div>

                    <div class="rsi-gen-section" data-testid="rsi-gen-decision">
                      <strong>{{ t('rsiGovernance.genDecisionLabel') }}</strong>
                      <span>{{ genDecisionText(genDetail) }}</span>
                    </div>

                    <div class="rsi-gen-section" data-testid="rsi-gen-deployment">
                      <strong>{{ t('rsiGovernance.genDeploymentLabel') }}</strong>
                      <span v-if="genDetail.deployment?.canaryStartedAt">
                        {{ t('rsiGovernance.genCanaryStartedAt') }}: {{ genDetail.deployment.canaryStartedAt }}
                      </span>
                      <span v-if="genDetail.deployment?.canaryConclusion">
                        {{ t('rsiGovernance.genCanaryConclusion') }}: {{ genDetail.deployment.canaryConclusion }}
                      </span>
                      <span v-if="genDetail.deployment?.promotedAt">
                        {{ t('rsiGovernance.genPromotedAt') }}: {{ genDetail.deployment.promotedAt }}
                      </span>
                      <span v-if="genDetail.deployment?.rolledBackTo != null">
                        {{ t('rsiGovernance.genRolledBackTo') }}: #{{ genDetail.deployment.rolledBackTo }}
                      </span>
                      <span v-if="!genDetail.deployment" class="rsi-hint">
                        {{ t('rsiGovernance.genNone') }}
                      </span>
                    </div>

                    <div class="rsi-gen-section" data-testid="rsi-gen-lineage">
                      <strong>{{ t('rsiGovernance.genLineageLabel') }}</strong>
                      <span
                        v-for="(l, i) in genLineage"
                        :key="l.generationNo"
                        class="rsi-gen-lineage-item"
                      >
                        <span v-if="i > 0" class="rsi-gen-lineage-arrow">←</span>
                        <a-tag :color="genStatusColor(l.status)">
                          #{{ l.generationNo }} {{ genStatusLabel(l.status) }}
                        </a-tag>
                      </span>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </template>
    </GlassCard>

    <!-- 运行参数（R7）：演化运行参数的单点写入口。rsi_phase 写控件自
         SettingPage 治理卡片收敛到此，消除"两处可改迟早漂移"；覆写条目
         在此只读（写入仍归治理设置面），判据结构与禁改清单不进面板。 -->
    <GlassCard :title="t('rsiGovernance.paramsTitle')" data-testid="rsi-params">
      <p class="rsi-hint">{{ t('rsiGovernance.paramsHint') }}</p>
      <p v-if="!paramsLoaded" class="rsi-not-ready" data-testid="rsi-params-not-loaded">
        {{ t('rsiGovernance.paramsNotLoaded') }}
      </p>
      <a-form layout="vertical">
        <a-form-item :label="t('rsiGovernance.phaseInputLabel')">
          <a-input-number
            v-model:value="params.rsi_phase"
            :min="0"
            :max="4"
            :precision="0"
            data-testid="rsi-param-phase"
          />
        </a-form-item>
        <a-form-item :label="t('rsiGovernance.metacogGateLabel')">
          <p class="rsi-hint">{{ t('rsiGovernance.metacogGateHint') }}</p>
          <a-switch
            v-model:checked="params.metacog_gate_enabled"
            data-testid="rsi-param-metacog"
          />
        </a-form-item>
        <a-form-item :label="t('rsiGovernance.rollbackPersistenceLabel')">
          <p class="rsi-hint">{{ t('rsiGovernance.rollbackPersistenceHint') }}</p>
          <a-switch
            v-model:checked="params.rsi_rollback_persistence_enabled"
            data-testid="rsi-param-rollback-persistence"
          />
        </a-form-item>
        <a-form-item :label="t('rsiGovernance.phaseMinAppliedLabel')">
          <p class="rsi-hint">{{ t('rsiGovernance.phaseMinAppliedHint') }}</p>
          <div v-for="pk in minAppliedKeys" :key="pk" class="rsi-param-row">
            <span class="rsi-param-name">{{ t('rsiGovernance.phaseNLabel', { phase: pk }) }}</span>
            <a-input-number
              v-model:value="params.rsi_phase_min_applied[pk]"
              :min="0"
              :precision="0"
              :data-testid="`rsi-param-min-applied-${pk}`"
            />
          </div>
        </a-form-item>
        <a-form-item :label="t('rsiGovernance.canaryWindowLabel')">
          <a-input-number
            v-model:value="params.rsi_canary_window_seconds"
            :min="1"
            :max="86400"
            :precision="0"
            data-testid="rsi-param-canary-window"
          />
        </a-form-item>
        <a-form-item :label="t('rsiGovernance.canaryThresholdsLabel')">
          <div class="rsi-param-row">
            <span class="rsi-param-name">{{ t('rsiGovernance.maxErrorRateLabel') }}</span>
            <a-input-number
              v-model:value="params.max_error_rate"
              :min="0"
              :max="1"
              :step="0.01"
              data-testid="rsi-param-max-error-rate"
            />
          </div>
          <div class="rsi-param-row">
            <span class="rsi-param-name">{{ t('rsiGovernance.minSuccessDropLabel') }}</span>
            <a-input-number
              v-model:value="params.min_success_rate_drop"
              :min="0"
              :max="1"
              :step="0.01"
              data-testid="rsi-param-min-success-drop"
            />
          </div>
        </a-form-item>
        <a-form-item :label="t('rsiGovernance.overridesReadonlyLabel')">
          <p class="rsi-hint">{{ t('rsiGovernance.overridesReadonlyHint') }}</p>
          <span class="rsi-overrides-readonly" data-testid="rsi-overrides-readonly">
            {{ overridesReadonlyText }}
          </span>
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button
          type="primary"
          :loading="savingParams"
          data-testid="rsi-params-save"
          @click="saveParams"
        >
          {{ t('common.save') }}
        </a-button>
      </template>
    </GlassCard>

    <GlassCard v-if="status" :title="t('rsiGovernance.evidenceTitle')" data-testid="rsi-evidence-machine">
      <p class="rsi-hint">{{ t('rsiGovernance.evidenceHint') }}</p>
      <table class="rsi-table" data-testid="rsi-evidence-rows">
        <tbody>
          <tr v-for="row in evidenceRows" :key="row.key" class="rsi-row">
            <td>{{ t(`rsiGovernance.${row.key === 'sealed' ? 'sealedEvidenceLabel' : row.key === 'probe' ? 'pairedProbeLabel' : row.key === 'curves' ? 'qualityCurvesLabel' : row.key === 'cost' ? 'costVectorLabel' : row.key === 'failedCost' ? 'failedCostLabel' : row.key === 'coverage' ? 'coverageLabel' : row.key === 'correlation' ? 'correlationLabel' : row.key === 'transfer' ? 'transferLabel' : row.key === 'checkpoint' ? 'checkpointLabel' : 'evalOutcomeLabel'}`) }}</td>
            <td>
              <a-tag v-if="row.state" :color="stateTagColor(row.state)" :data-testid="`rsi-ev-${row.key}-state`">
                {{ stateText(row.state) }}
              </a-tag>
              <span :data-testid="`rsi-ev-${row.key}`">{{ row.value }}</span>
              <em v-if="row.reason">{{ row.reason }}</em>
            </td>
          </tr>
        </tbody>
      </table>
      <!-- 质量三曲线明细（C2）：archive-best / deployed / final 逐 checkpoint 分列 -->
      <table
        v-if="status.quality_curves?.curve?.length"
        class="rsi-table"
        data-testid="rsi-curves"
      >
        <thead>
          <tr>
            <th>#</th>
            <th>deployed</th>
            <th>final</th>
            <th>{{ t('rsiGovernance.archiveBestLabel') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pt in status.quality_curves.curve" :key="pt.checkpoint" class="rsi-row">
            <td>{{ pt.checkpoint }}</td>
            <td>{{ pt.deployed }}</td>
            <td>{{ pt.final }}</td>
            <td>{{ pt.archive_best }}</td>
          </tr>
        </tbody>
      </table>
      <!-- A5 升级批准（人工 gate 的人工半）：available 才出按钮，理由随行 -->
      <div v-if="upgrade" class="rsi-upgrade" data-testid="rsi-upgrade">
        <a-tag :color="upgrade.available ? 'processing' : 'default'" data-testid="rsi-upgrade-state">
          {{ upgrade.available ? t('rsiGovernance.upgradeAvailable') : t('rsiGovernance.upgradeNone') }}
        </a-tag>
        <em v-if="!upgrade.available">{{ upgrade.reason }}</em>
        <template v-if="upgrade.available">
          <span>{{ upgrade.derived_version }} ← {{ upgrade.derived_from }} · Γ={{ upgrade.probe_gamma }}</span>
          <a-button
            size="small"
            type="primary"
            :loading="approvingUpgrade"
            data-testid="rsi-upgrade-approve"
            @click="approveUpgrade"
          >
            {{ t('rsiGovernance.upgradeApprove') }}
          </a-button>
        </template>
      </div>
    </GlassCard>

    <GlassCard :title="t('rsiGovernance.queueTitle')">
      <p v-if="!proposals.length && !notReady" class="rsi-hint" data-testid="rsi-empty">
        {{ t('rsiGovernance.empty') }}
      </p>
      <table class="rsi-table" data-testid="rsi-queue">
        <thead>
          <tr>
            <th>{{ t('rsiGovernance.colTarget') }}</th>
            <th>{{ t('rsiGovernance.colType') }}</th>
            <th>{{ t('rsiGovernance.colRisk') }}</th>
            <th>{{ t('rsiGovernance.colStatus') }}</th>
            <th>{{ t('rsiGovernance.colAction') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in proposals" :key="p.proposal_id" class="rsi-row">
            <td>{{ p.target }}</td>
            <td>{{ p.proposal_type }}</td>
            <td><a-tag>{{ p.risk_level }}</a-tag></td>
            <td data-testid="rsi-row-status">{{ p.status }}</td>
            <td>
              <template v-if="p.status === 'pending'">
                <a-input
                  v-if="!hasExecutableSequence(p)"
                  v-model:value="sequenceDraft[p.proposal_id]"
                  data-testid="rsi-sequence-input"
                  :placeholder="t('rsiGovernance.sequencePlaceholder')"
                  class="rsi-sequence-input"
                />
                <a-button size="small" data-testid="rsi-approve" @click="approve(p)">
                  {{ t('rsiGovernance.approve') }}
                </a-button>
                <a-button size="small" data-testid="rsi-reject" @click="reject(p)">
                  {{ t('rsiGovernance.reject') }}
                </a-button>
              </template>
              <span v-if="evidence[p.proposal_id]" data-testid="rsi-evidence">
                {{ evidence[p.proposal_id].skillId }}
                {{ evidence[p.proposal_id].hit
                  ? t('rsiGovernance.evidenceHit')
                  : t('rsiGovernance.evidenceMiss') }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </GlassCard>
  </div>
</template>

<style scoped>
.rsi-governance-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rsi-hint {
  opacity: 0.7;
  margin: 0 0 12px;
}
.rsi-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.rsi-toolbar label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
}
.rsi-agent-input {
  width: 180px;
}
.rsi-state-select,
.rsi-sequence-input {
  width: 150px;
}
.rsi-limit-input {
  width: 110px;
}
.rsi-baseline {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
  font-size: 13px;
}
.rsi-gen-detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}
.rsi-gen-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  opacity: 0.75;
}
.rsi-gen-section {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
}
.rsi-gen-section strong {
  font-size: 12px;
  opacity: 0.8;
  margin-right: 4px;
}
.rsi-gen-line {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}
.rsi-gen-target {
  font-weight: 600;
}
.rsi-gen-verdict {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}
.rsi-gen-verdict em {
  font-style: normal;
  opacity: 0.7;
  font-size: 12px;
}
.rsi-gen-lineage-item {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.rsi-gen-lineage-arrow {
  opacity: 0.6;
  margin: 0 2px;
}
.rsi-sequence-input {
  width: 200px;
  margin-right: 6px;
}
.rsi-not-ready {
  margin: 12px 0 0;
  color: var(--color-warning, #b8860b);
}
.rsi-param-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.rsi-param-name {
  min-width: 120px;
  font-size: 13px;
}
.rsi-overrides-readonly {
  font-size: 13px;
  opacity: 0.85;
}
.rsi-status {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 12px;
  font-size: 13px;
}
.rsi-status em {
  opacity: 0.7;
  font-style: normal;
}
.rsi-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.rsi-table th,
.rsi-table td {
  text-align: left;
  padding: 8px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.2);
  vertical-align: top;
}
</style>
