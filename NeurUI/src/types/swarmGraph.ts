/**
 * 蜂群协作图投影类型（P1-1/P2-3/P2-4）。
 *
 * 事实源：后端 `neurova/agent/swarm_graph_projection.py` 与
 * `neurova/agent/candidate_projection.py` 的 TypedDict。本文件是**手抄对齐**——
 * 字段集合由 `tests/unit/api/test_swarm_graph_contract.py` 双向钉住，后端改字段
 * 必须同批改这里与 SwarmFlowPanel.vue，漏改即红。
 *
 * 纪律（P2-4）：服务端只出投影、前端只做渲染——本文件只描述投影结构，
 * 不 import 事件语义、不做 trace 解释。
 */

/** 图节点三类同构（nodeType 判别）：run 成员节点 / 审批卡 / 候选卡。 */
export interface SwarmGraphNode {
  id: string
  nodeType: SwarmGraphNodeType
  run_id: string
  member_name: string
  kind: SwarmGraphMemberKind
  executor_tool: string
  status: string
  depth: number
  team_id: string
  started_at: number
  finished_at: number
  duration_ms: number
  error_type: string
  level: string
  decision: string
  decided_by: string
  request_id: string
  candidate_id: string
  artifact_keys: string[]
  base_revision: number
  note: string
}

export type SwarmGraphNodeType = 'run' | 'approval' | 'candidate'

/** 内置成员 / 外部编码代理（团队名册 executor 成员）。 */
export type SwarmGraphMemberKind = 'internal' | 'external' | ''

/** v2 全边集（拍板 D-A）：spawn+依赖+审批+候选。 */
export type SwarmGraphEdgeType = 'spawn' | 'dependency' | 'approval' | 'candidate'

export interface SwarmGraphEdge {
  id: string
  type: SwarmGraphEdgeType
  from: string
  to: string
  /** 审批边：L0/L1/L2 */
  level?: string
  /** 审批边=裁决态（approved/rejected/pending）；候选边=候选状态 */
  status?: string
  /** 审批边：approve/reject */
  decision?: string
  decided_by?: string
}

export interface SwarmGraphMeta {
  /** 候选板集成版本（P2-3 投影） */
  revision: number
  generated_at: number
  /** runs 超上限被截（诚实标注） */
  truncated: boolean
  /** 候选账本缺事件（P2-3 incomplete 透传） */
  candidates_incomplete: boolean
  counts: Record<string, number>
}

export interface SwarmGraphProjection {
  nodes: SwarmGraphNode[]
  edges: SwarmGraphEdge[]
  meta: SwarmGraphMeta
}

/** 投影出的单条候选（= 后端 CandidateReport.toDict 去掉 content）。 */
export interface CandidateProjectionEntry {
  candidate_id: string
  run_id: string
  artifact_keys: string[]
  base_revision: number
  status: string
  conflict_with: string[]
  note: string
  created_at: string
  decided_at: string
}

/** 候选板重放投影快照（incomplete=账本缺事件的诚实标注）。 */
export interface CandidateBoardSnapshot {
  revision: number
  candidates: CandidateProjectionEntry[]
  conflicts: CandidateProjectionEntry[]
  incomplete: boolean
  source: string
}

/** 图端点信封 data（parent_session_id + 投影本体）。 */
export interface SwarmGraphResult extends SwarmGraphProjection {
  parent_session_id: string
}

/** 候选端点信封 data。 */
export interface CandidateBoardResult extends CandidateBoardSnapshot {
  parent_session_id: string
}
