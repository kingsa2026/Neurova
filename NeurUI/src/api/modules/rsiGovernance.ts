import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// Types — RSI 进化审批面（工单 011）
//
// 字段名对齐后端 `RSIOrchestrator.get_status()` 与提案对象的 to_dict()，
// 不在前端另立一套解释（另立一套就会漂移）。
// ---------------------------------------------------------------------------

export type ProposalStateFilter = 'all' | 'pending' | 'applied' | 'rejected' | 'rolled_back'

export interface RsiProposal {
  proposal_id: string
  agent_id?: string
  proposal_type: 'skill_manifest' | 'action_definition' | 'pr_patch'
  target: string
  content: string
  description: string
  risk_level: 'low' | 'medium' | 'high'
  status: ProposalStateFilter
  created_at: string
  approved_by?: string
  approved_at?: string
  applied_at?: string
  snapshot_id?: string
  rejection_reason?: string
}

export interface RsiVerdict {
  state: 'passed' | 'failed' | 'unevidenced' | string
  reason?: string
}

export interface RsiStatus {
  agent_id?: string
  iteration_count: number
  convergence_status: string
  deployment_phase: number
  phase_advanced: boolean
  phase_persisted: boolean
  phase_verdict: RsiVerdict
  candidates: { generated: number; pruned: number; pass_rate: number }
  rollback_history: unknown[]
  escalation?: { verdict?: RsiVerdict; proposals?: string[]; skipped?: { system: string; reason: string }[] }
  metrics?: Record<string, unknown>
  /** 回执负债读数（Issue #289 · 003）：账本新增两列必须在界面可见。 */
  debt?: RsiDebtReadout
  /** 参数活性读数（Issue #289 · 004 M3）：三态不折叠。 */
  parameter_activity?: RsiParameterActivity
  /** 证据机器读数（survey §10.2 批次）：三态如实呈报，缺席说原因。 */
  eval_outcome?: RsiThreeStateReadout
  sealed_evidence?: RsiSealedEvidence
  improver_paired_probe?: RsiPairedProbeReadout
  quality_curves?: RsiQualityCurves
  cost_vector?: { last?: Record<string, number> | null; totals?: Record<string, number> }
  pruner_failed_cost?: { eliminated: number; total_realized_cost: number; zero_cost_ids?: string[] }
  proxy_reference_correlation?: RsiThreeStateReadout & { pairs?: number; arm?: string; degenerate?: boolean }
  transfer?: RsiThreeStateReadout
  coverage?: { expected: string[]; covered: string[]; uncovered: string[]; alert: boolean }
  checkpoint_columns?: Record<string, unknown> & { missing?: string[] }
  audit_schedule?: { stride: number; scheduled_points: number[]; snapshots_recorded: number[] }
  /** A5 升级可用性：available=true 时批准走 governance 端点。 */
  improver_upgrade?: {
    available: boolean
    reason?: string
    derived_version?: string
    summary?: string
    derived_from?: string
    probe_state?: string
    probe_gamma?: number | null
  }
}

/** 三态读数通用形态（measured / insufficient_data / unevidenced——缺席必须说原因）。 */
export interface RsiThreeStateReadout {
  state: 'measured' | 'insufficient_data' | 'unevidenced' | string
  score?: number | null
  reason?: string
  detail?: string
}

/** 密封档验收证据（D1）：决策落定后的独立验收读数。 */
export interface RsiSealedEvidence extends RsiThreeStateReadout {
  evidenced_cases?: number
  blind_cases?: number
  covered_families?: string[]
  cases?: { id: string; family: string; score: number; detail: string }[]
}

/** Eq8 配对探针读数（A3/A4）：带符号 Γ＋逐臂计账＋共享分类。 */
export interface RsiPairedProbeReadout extends RsiThreeStateReadout {
  states?: number
  evidenced_pairs?: number
  realized_evaluations?: number
  policy_versions?: { t?: string; baseline?: string }
  arms?: Record<string, { realized: number; quality_mean?: number | null; evidenced: number; improved?: string[]; regressed?: string[] }>
  quality_at_milestones?: Record<string, unknown>
}

/** 质量三曲线（C2）：archive-best / deployed / final 逐 checkpoint 分列。 */
export interface RsiQualityCurves {
  state: 'measured' | 'insufficient_data' | string
  curve: { checkpoint: number; deployed?: number; final?: number; archive_best?: number }[]
  archive_best?: number | null
}

/** 负债读数（`available: false` = 账本未开，**不是**"没有欠账"）。 */
export interface RsiDebtReadout {
  available: boolean
  reason?: string
  outstanding?: number
  priced_rows?: number
  unknown_rows?: number
  settled_rows?: number
  last_write_failure?: string | null
  next_step?: { allow: boolean; reason: string; outstanding: number }
}

/** 参数活性读数：`no_data` / `sparse` / `never_proposed` 三态各成一值。 */
export interface RsiParameterActivity {
  states: Record<string, string>
  movements: Record<string, number>
  vocabulary: string[]
  overall: string
  reason?: string | null
}

export interface RsiApproveEvidence {
  applied: boolean
  applied_skill_id: string
  registry_hit: boolean
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

const BASE = '/governance/rsi'

function scopedParams(agentId?: string): { params: Record<string, string> } {
  return { params: agentId ? { agent_id: agentId } : {} }
}

/** RSI 状态读数（阶段、晋升判据三态、候选统计、升级通道） */
/** A5 改进器换版批准（人工 gate 的人工半；409 = 无候选/已在账/无证据）。 */
export function approveImproverUpgrade(options: { agentId?: string; approvedBy: string }) {
  return api.post<ApiResponse<Record<string, unknown>>>(
    `${BASE}/improver-upgrade/approve`,
    { approved_by: options.approvedBy },
    scopedParams(options.agentId),
  )
}

export function getRsiStatus(agentId?: string) {
  return api.get<ApiResponse<RsiStatus>>(`${BASE}/status`, scopedParams(agentId))
}

/** 全状态提案列表（默认 all —— 只有 PENDING 可见时事后审计无从下手） */
export function listRsiProposals(options: { state?: ProposalStateFilter; agentId?: string } = {}) {
  const { state = 'all', agentId } = options
  return api.get<ApiResponse<{ proposals: RsiProposal[]; state: ProposalStateFilter }>>(
    `${BASE}/proposals`,
    { params: { state, ...(agentId ? { agent_id: agentId } : {}) } },
  )
}

/** 待审提案（保留旧形状，供只要 PENDING 的调用方） */
export function listPendingRsiProposals(agentId?: string) {
  return api.get<ApiResponse<{ proposals: RsiProposal[] }>>(
    `${BASE}/proposals/pending`,
    scopedParams(agentId),
  )
}

/**
 * 批准并应用。
 *
 * `toolSequence`：manifest 里没有可执行内容时由批准人补交 —— 不补则后端按
 * `not_supported` 拒绝（工单 010），前端不得把它显示成"已批准"。
 */
export function approveRsiProposal(
  proposalId: string,
  options: { approvedBy: string; toolSequence?: string[]; agentId?: string },
) {
  const { approvedBy, toolSequence, agentId } = options
  return api.post<ApiResponse<RsiApproveEvidence>>(
    `${BASE}/proposals/${proposalId}/approve`,
    { approved_by: approvedBy, ...(toolSequence ? { tool_sequence: toolSequence } : {}) },
    scopedParams(agentId),
  )
}

/** 拒绝提案（保持 PENDING→REJECTED 的状态机守卫在后端） */
export function rejectRsiProposal(
  proposalId: string,
  options: { reason?: string; agentId?: string } = {},
) {
  const { reason = '', agentId } = options
  return api.post<ApiResponse<null>>(
    `${BASE}/proposals/${proposalId}/reject`,
    { reason },
    scopedParams(agentId),
  )
}
