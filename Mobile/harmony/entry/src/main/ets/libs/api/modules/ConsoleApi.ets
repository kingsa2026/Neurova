/**
 * ConsoleApi - Console 域 API 模块（车道F：蜂群协作过程视图读面）
 *
 * 后端事实源：neurova/api/endpoints/console.py（挂 /v1/console 前缀，
 * 挂载见 endpoints/__init__.py `("...console", "/v1/console", "Console API")`）。
 *   GET /console/chat/runs/{parent_session_id}/graph       → {code:0,data:{parent_session_id,nodes,edges,meta}}
 *   GET /console/chat/runs/{parent_session_id}/candidates  → {code:0,data:{parent_session_id,revision,candidates,conflicts,incomplete,source}}
 *
 * 返回形状事实源：neurova/agent/swarm_graph_projection.py（GraphNode/GraphEdge/GraphMeta
 * TypedDict）与 candidate_projection.py（CandidateReport）。本文件是**手抄对齐**——
 * 后端改字段必须同批改这里与 SwarmFlowPanel.ets（对齐 PC 端 types/swarmGraph.ts 先例）。
 *
 * 归一纪律：后端 JSON 经 HttpClient 透传，字段缺失/类型漂移在本模块边界逐字段
 * 防御读出（页面层不做裸 Record 解析，防 undefined 渲染崩溃）；读面失败（含
 * run 台账关闭 503）诚实 throw，由调用方 fail-soft。
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 图节点三类同构（nodeType 判别：run | approval | candidate） */
export interface SwarmGraphNode {
  id: string;
  nodeType: string;
  run_id: string;
  member_name: string;
  kind: string;            // internal | external | ''（卡节点空串）
  executor_tool: string;
  status: string;          // run 状态 / 审批裁决态 / 候选状态
  depth: number;           // 派生深度（0=未知）
  team_id: string;
  started_at: number;
  finished_at: number;
  duration_ms: number;
  error_type: string;
  level: string;           // 审批卡：L0/L1/L2
  decision: string;        // 审批卡：approve/reject
  decided_by: string;
  request_id: string;
  candidate_id: string;
  artifact_keys: string[];
  base_revision: number;
  note: string;
}

/** 图边四类（v2 全边集）：spawn | dependency | approval | candidate */
export interface SwarmGraphEdge {
  id: string;
  type: string;
  from: string;
  to: string;
  level: string;
  status: string;
  decision: string;
  decided_by: string;
}

/** 图 meta（诚实标注：截断 / 候选账本缺事件） */
export interface SwarmGraphMeta {
  revision: number;
  generated_at: number;
  truncated: boolean;
  candidates_incomplete: boolean;
  counts: Record<string, number>;
}

/** 图投影本体 */
export interface SwarmGraphProjection {
  nodes: SwarmGraphNode[];
  edges: SwarmGraphEdge[];
  meta: SwarmGraphMeta;
}

/** 图端点信封 data（parent_session_id + 投影本体） */
export interface SwarmGraphResult extends SwarmGraphProjection {
  parent_session_id: string;
}

/** 候选板单条候选（后端 CandidateReport.toDict 去 content 投影） */
export interface CandidateEntry {
  candidate_id: string;
  run_id: string;
  artifact_keys: string[];
  base_revision: number;
  status: string;
  conflict_with: string[];
  note: string;
  created_at: string;
  decided_at: string;
}

/** 候选板重放投影快照（incomplete=账本缺事件的诚实标注） */
export interface CandidateBoardResult {
  parent_session_id: string;
  revision: number;
  candidates: CandidateEntry[];
  conflicts: CandidateEntry[];
  incomplete: boolean;
  source: string;
}

// ---------------------------------------------------------------------------
// 边界归一（防御读出：后端字段缺失/类型漂移不致渲染崩溃）
// ---------------------------------------------------------------------------

/** 任意值 → Record（非对象回落空表） */
function toRec(v: Object | undefined): Record<string, Object> {
  if (v === undefined || v === null) {
    const empty: Record<string, Object> = {};
    return empty;
  }
  return v as Record<string, Object>;
}

function readStr(rec: Record<string, Object>, key: string, fb: string = ''): string {
  const v = rec[key];
  if (v === undefined || v === null) {
    return fb;
  }
  return String(v);
}

function readNum(rec: Record<string, Object>, key: string, fb: number = 0): number {
  const v = rec[key];
  if (typeof v === 'number' && !isNaN(v)) {
    return v;
  }
  const n = Number(v);
  return isNaN(n) ? fb : n;
}

function readBool(rec: Record<string, Object>, key: string, fb: boolean = false): boolean {
  const v = rec[key];
  if (typeof v === 'boolean') {
    return v;
  }
  return fb;
}

function readStrArray(rec: Record<string, Object>, key: string): string[] {
  const v = rec[key];
  if (!Array.isArray(v)) {
    return [];
  }
  const out: string[] = [];
  for (const item of v as Object[]) {
    out.push(item === undefined || item === null ? '' : String(item));
  }
  return out;
}

/** 单节点归一（未知 nodeType 原样透传，渲染端按非 run 兜底成卡） */
function toNode(raw: Object): SwarmGraphNode {
  const rec = toRec(raw);
  const node: SwarmGraphNode = {
    id: readStr(rec, 'id'),
    nodeType: readStr(rec, 'nodeType', 'run'),
    run_id: readStr(rec, 'run_id'),
    member_name: readStr(rec, 'member_name'),
    kind: readStr(rec, 'kind'),
    executor_tool: readStr(rec, 'executor_tool'),
    status: readStr(rec, 'status'),
    depth: readNum(rec, 'depth', 0),
    team_id: readStr(rec, 'team_id'),
    started_at: readNum(rec, 'started_at', 0),
    finished_at: readNum(rec, 'finished_at', 0),
    duration_ms: readNum(rec, 'duration_ms', 0),
    error_type: readStr(rec, 'error_type'),
    level: readStr(rec, 'level'),
    decision: readStr(rec, 'decision'),
    decided_by: readStr(rec, 'decided_by'),
    request_id: readStr(rec, 'request_id'),
    candidate_id: readStr(rec, 'candidate_id'),
    artifact_keys: readStrArray(rec, 'artifact_keys'),
    base_revision: readNum(rec, 'base_revision', 0),
    note: readStr(rec, 'note'),
  };
  return node;
}

function toEdge(raw: Object): SwarmGraphEdge {
  const rec = toRec(raw);
  const edge: SwarmGraphEdge = {
    id: readStr(rec, 'id'),
    type: readStr(rec, 'type'),
    from: readStr(rec, 'from'),
    to: readStr(rec, 'to'),
    level: readStr(rec, 'level'),
    status: readStr(rec, 'status'),
    decision: readStr(rec, 'decision'),
    decided_by: readStr(rec, 'decided_by'),
  };
  return edge;
}

function toMeta(raw: Object | undefined): SwarmGraphMeta {
  const rec = toRec(raw);
  const countsRaw = toRec(rec['counts']);
  const counts: Record<string, number> = {};
  for (const k of Object.keys(countsRaw)) {
    counts[k] = readNum(countsRaw, k, 0);
  }
  const meta: SwarmGraphMeta = {
    revision: readNum(rec, 'revision', 0),
    generated_at: readNum(rec, 'generated_at', 0),
    truncated: readBool(rec, 'truncated', false),
    candidates_incomplete: readBool(rec, 'candidates_incomplete', false),
    counts: counts,
  };
  return meta;
}

function toCandidate(raw: Object): CandidateEntry {
  const rec = toRec(raw);
  const entry: CandidateEntry = {
    candidate_id: readStr(rec, 'candidate_id'),
    run_id: readStr(rec, 'run_id'),
    artifact_keys: readStrArray(rec, 'artifact_keys'),
    base_revision: readNum(rec, 'base_revision', 0),
    status: readStr(rec, 'status'),
    conflict_with: readStrArray(rec, 'conflict_with'),
    note: readStr(rec, 'note'),
    created_at: readStr(rec, 'created_at'),
    decided_at: readStr(rec, 'decided_at'),
  };
  return entry;
}

/** graph 端点 data → SwarmGraphResult（字段逐项防御读出） */
function normalizeGraph(data: Object): SwarmGraphResult {
  const rec = toRec(data);
  const nodesRaw = Array.isArray(rec['nodes']) ? rec['nodes'] as Object[] : [];
  const edgesRaw = Array.isArray(rec['edges']) ? rec['edges'] as Object[] : [];
  const result: SwarmGraphResult = {
    parent_session_id: readStr(rec, 'parent_session_id'),
    nodes: nodesRaw.map(toNode),
    edges: edgesRaw.map(toEdge),
    meta: toMeta(rec['meta']),
  };
  return result;
}

/** candidates 端点 data → CandidateBoardResult */
function normalizeCandidates(data: Object): CandidateBoardResult {
  const rec = toRec(data);
  const candRaw = Array.isArray(rec['candidates']) ? rec['candidates'] as Object[] : [];
  const conflictRaw = Array.isArray(rec['conflicts']) ? rec['conflicts'] as Object[] : [];
  const result: CandidateBoardResult = {
    parent_session_id: readStr(rec, 'parent_session_id'),
    revision: readNum(rec, 'revision', 0),
    candidates: candRaw.map(toCandidate),
    conflicts: conflictRaw.map(toCandidate),
    incomplete: readBool(rec, 'incomplete', false),
    source: readStr(rec, 'source'),
  };
  return result;
}

// ---------------------------------------------------------------------------
// ConsoleApi
// ---------------------------------------------------------------------------

export class ConsoleApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /**
   * 蜂群协作拓扑图投影（P1-1，v2 全边集 spawn+依赖+审批+候选）。
   * 失败（网络/鉴权/run 台账关闭 503）诚实 throw，调用方 fail-soft。
   */
  async fetchSwarmRunGraph(parentSessionId: string): Promise<ApiResponse<SwarmGraphResult>> {
    const path = `/console/chat/runs/${encodeURIComponent(parentSessionId)}/graph`;
    const res = await this.client.get<Object>(path);
    if (res.code !== 0 || res.data === undefined || res.data === null) {
      throw new Error(res.message && res.message.length > 0 ? res.message : 'swarm graph unavailable');
    }
    const ok: ApiResponse<SwarmGraphResult> = {
      code: 0,
      message: res.message,
      data: normalizeGraph(res.data),
    };
    return ok;
  }

  /**
   * 候选板重放投影（P2-3：H-4 事件折叠，重启后可查）。
   * 失败诚实 throw；调用方可把它当非致命面（图为主、候选为辅）。
   */
  async fetchSwarmRunCandidates(parentSessionId: string): Promise<ApiResponse<CandidateBoardResult>> {
    const path = `/console/chat/runs/${encodeURIComponent(parentSessionId)}/candidates`;
    const res = await this.client.get<Object>(path);
    if (res.code !== 0 || res.data === undefined || res.data === null) {
      throw new Error(res.message && res.message.length > 0 ? res.message : 'candidate board unavailable');
    }
    const ok: ApiResponse<CandidateBoardResult> = {
      code: 0,
      message: res.message,
      data: normalizeCandidates(res.data),
    };
    return ok;
  }
}
