/**
 * 本体语义栈 API 客户端（升级计划 UI-0–UI-4；端点契约见
 * docs/02-api/API_REFERENCE.md 第 19 节）。
 *
 * 只封装已落格的后端端点（B1–B14 实测）：
 * - terms/schema/quality/derivations/relation-candidates/shapes/
 *   pipeline/{run,diff,rollback}/iri/五种导出
 * - access/{query,analyze,validate,use} 四动词门面（query 支持 asOf/knownAt）
 * - enterprise/sources 描述符提交与状态回显（B14 预留接口的唯一 REST 入口）
 * - facts/{factId}/lineage 与 adoption 复用 knowledge.ts 既有实现，不在这里重抄
 *
 * 仍未落地的是企业源**真实连接器**（DB/ERP API/事件流的 fetchBatch，另立项）：
 * 本模块只有描述符校验/落库/回显，没有任何「已连接」的调用；UI 侧继续以
 * 「接口预留 / 适配器未注册」诚实态呈现，不造假调用。
 */
import api from '@/api'
import type { ApiResponse } from '@/types/response'
import type {
  CqRow,
  DerivationChain,
  DefaultOffReadingsResponse,
  EnterpriseDescriptor,
  EnterpriseSourceConfig,
  EnterpriseSourceHealth,
  FactQueryBody,
  FactQueryItem,
  IriResolution,
  OntologyActionRow,
  OntologyComputeResult,
  OntologyDecisionChainNode,
  OntologyDecisionRow,
  OntologySimulationReport,
  OntologySimulationRow,
  OntologyEnvelope,
  OntologyFunctionRow,
  OntologyQualityReport,
  OntologySchemaData,
  OntologyShape,
  OntologyStateMachineRow,
  OntologyShapeWrite,
  OntologyTerm,
  OntologyTermWrite,
  OntologyValidateResponse,
  PipelineDiffResponse,
  PipelineRollbackResponse,
  PipelineRunResponse,
  RelationCandidate,
  ValidateTriple,
} from '@/types/ontology'

const BASE = '/knowledge'

// ---------------------------------------------------------------------------
// 术语（GET cursor 分页 / POST / PUT / DELETE）
// ---------------------------------------------------------------------------

export function listOntologyTerms(params?: { limit?: number; cursor?: string; fields?: string }) {
  return api.get<ApiResponse<OntologyEnvelope<OntologyTerm>>>(`${BASE}/ontology/terms`, {
    params: { limit: params?.limit, cursor: params?.cursor, fields: params?.fields },
  })
}

export function getOntologySchema() {
  return api.get<ApiResponse<OntologySchemaData>>(`${BASE}/ontology/schema`)
}

/** G5：可用领域包清单（概要：packId/namespace/basedOn/note/termCount）。
 * P1-11（审计 2026-11-14）：后端路径是 /ontology/domain-packs，少拼 ontology
 * 段会被 knowledge 的 GET /{knowledge_id} 参数路由吃掉报"条目不存在"。 */
export function listDomainPacks() {
  return api.get<ApiResponse<Array<{ packId: string; namespace: string; basedOn: string; note: string; termCount: number }>>>(`${BASE}/ontology/domain-packs`)
}

/** G5：导入领域包（admin，只补缺幂等；返回补上条数）。 */
export function importDomainPack(packId: string) {
  return api.post<ApiResponse<{ pack_id: string; added: number }>>(`${BASE}/ontology/domain-packs/${encodeURIComponent(packId)}/import`)
}

/** G4：可用 IRI 命名空间注册表（前缀 → 基座；空 namespace 语义 = 缺省 kbg:）。 */
export function listOntologyNamespaces() {
  // P1-8（全库断点审计 2026-11-12）：后端路径是 /ontology/namespaces；
  // 少拼 ontology 段时请求被 knowledge 的 GET /{knowledge_id} 吃掉报 404。
  return api.get<ApiResponse<Record<string, string>>>(`${BASE}/ontology/namespaces`)
}

export function createOntologyTerm(body: OntologyTermWrite) {
  return api.post<ApiResponse<OntologyTerm>>(`${BASE}/ontology/terms`, body)
}

export function updateOntologyTerm(termId: string, body: OntologyTermWrite) {
  return api.put<ApiResponse<OntologyTerm>>(
    `${BASE}/ontology/terms/${encodeURIComponent(termId)}`,
    body,
  )
}

export function deleteOntologyTerm(termId: string, params?: { agent_id?: string }) {
  return api.delete<ApiResponse<unknown>>(
    `${BASE}/ontology/terms/${encodeURIComponent(termId)}`,
    { params },
  )
}

// ---------------------------------------------------------------------------
// 关系候选（B8；审批仅管理员）
// ---------------------------------------------------------------------------

export function listRelationCandidates(status: 'pending' | 'approved' | 'rejected' = 'pending', limit = 100) {
  return api.get<ApiResponse<{ items: RelationCandidate[] }>>(`${BASE}/ontology/relation-candidates`, {
    params: { status, limit },
  })
}

export function approveRelationCandidate(candidateId: string, basis = '') {
  return api.post<ApiResponse<{ candidate: RelationCandidate; activity_id: string }>>(
    `${BASE}/ontology/relation-candidates/${encodeURIComponent(candidateId)}/approve`,
    {},
    { params: basis ? { basis } : {} },
  )
}

export function rejectRelationCandidate(candidateId: string, basis = '') {
  return api.post<ApiResponse<{ candidate: RelationCandidate; activity_id: string }>>(
    `${BASE}/ontology/relation-candidates/${encodeURIComponent(candidateId)}/reject`,
    {},
    { params: basis ? { basis } : {} },
  )
}

// ---------------------------------------------------------------------------
// 解释链（B11）与稳定 IRI（B12）
// ---------------------------------------------------------------------------

export function getDerivationChain(factId: string) {
  return api.get<ApiResponse<DerivationChain>>(
    `${BASE}/ontology/derivations/${encodeURIComponent(factId)}`,
  )
}

/** kbg:<term> 与外部 IRI → 术语行；未知 404（解析失败显式报错，不静默）。 */
export function resolveOntologyIri(iri: string) {
  return api.get<ApiResponse<IriResolution>>(
    `${BASE}/ontology/iri/${encodeURIComponent(iri)}`,
  )
}

// ---------------------------------------------------------------------------
// 形状注册表（B10 L4；写入前/dry-run 同求值器）
// ---------------------------------------------------------------------------

export function listOntologyShapes(enabledOnly = false) {
  return api.get<ApiResponse<{ items: OntologyShape[]; total: number }>>(
    `${BASE}/ontology/shapes`, { params: { enabled_only: enabledOnly } },
  )
}

export function createOntologyShape(body: OntologyShapeWrite) {
  return api.post<ApiResponse<{ shape: OntologyShape; activity_id: string }>>(
    `${BASE}/ontology/shapes`, body,
  )
}

export function updateOntologyShape(shapeId: string, body: OntologyShapeWrite) {
  return api.put<ApiResponse<{ shape: OntologyShape; activity_id: string }>>(
    `${BASE}/ontology/shapes/${encodeURIComponent(shapeId)}`, body,
  )
}

export function deleteOntologyShape(shapeId: string) {
  return api.delete<ApiResponse<{ activity_id: string }>>(
    `${BASE}/ontology/shapes/${encodeURIComponent(shapeId)}`,
  )
}

// ---------------------------------------------------------------------------
// 发布治理（B6 pipeline run/diff + B12 rollback REST）
// ---------------------------------------------------------------------------

export interface PipelineRunPayload {
  agentId?: string
  tenantId?: string
  termUpserts?: Array<Record<string, unknown>>
  ruleRegistrations?: Array<Record<string, unknown>>
  factCandidates?: Array<Record<string, unknown>>
  reason?: string
}

export function runOntologyPipeline(body: PipelineRunPayload) {
  return api.post<ApiResponse<PipelineRunResponse>>(`${BASE}/ontology/pipeline/run`, body)
}

export function getOntologyPipelineDiff(params: { fromBaseline?: string; toBaseline?: string }) {
  return api.get<ApiResponse<PipelineDiffResponse>>(`${BASE}/ontology/pipeline/diff`, { params })
}

export function rollbackOntologyPipeline(body: { toBaselineId: string; reason?: string }) {
  return api.post<ApiResponse<PipelineRollbackResponse>>(
    `${BASE}/ontology/pipeline/rollback`, body,
  )
}

// ---------------------------------------------------------------------------
// 四动词访问门面（B3；UI-1/UI-2 是首个仓内消费者）
// ---------------------------------------------------------------------------

export function accessQuery(body: FactQueryBody, params?: { agent_id?: string; scope?: string }) {
  return api.post<FactQueryItem[]>(`${BASE}/access/query`, body, { params })
}

export function accessAnalyze(body: Record<string, unknown>) {
  return api.post<Record<string, unknown>>(`${BASE}/access/analyze`, body)
}

export function accessValidate(body: { tenantId?: string; agentId?: string; triples: ValidateTriple[] }) {
  return api.post<ApiResponse<OntologyValidateResponse>>(`${BASE}/access/validate`, body)
}

/** use 动词 → 事实采纳写回（治理门同源：仅管理员）。 */
export function accessUse(factId: string, body: { outcome: string }) {
  return api.post<ApiResponse<{ fact_id: string; outcome: string }>>(
    `${BASE}/access/use/${encodeURIComponent(factId)}`,
    body,
  )
}

// ---------------------------------------------------------------------------
// 导出（B12 L7：五格式 REST；RDF 1.1 基线，RDF 1.2 只观察）
// ---------------------------------------------------------------------------

export function exportOntologyTtl(agentId?: string) {
  return api.get<string>(`${BASE}/ontology/export.ttl`, {
    responseType: 'text',
    params: agentId ? { agent_id: agentId } : {},
  })
}

export function exportOntologyJsonLd(agentId?: string) {
  return api.get<string>(`${BASE}/ontology/export.jsonld`, {
    responseType: 'text',
    params: agentId ? { agent_id: agentId } : {},
  })
}

export function exportOntologyOwl(version?: string) {
  return api.get<string>(`${BASE}/ontology/export.owl`, {
    responseType: 'text',
    params: version ? { version } : {},
  })
}

export function exportOntologyShacl() {
  return api.get<string>(`${BASE}/ontology/export.shacl`, { responseType: 'text' })
}

export function exportOntologyProv() {
  return api.get<string>(`${BASE}/ontology/export.prov`, { responseType: 'text' })
}

// ---------------------------------------------------------------------------
// 质量报告（B13 L9，只读）
// ---------------------------------------------------------------------------

/** GET /ontology/quality：OOPS! 结构子集＋两个可计算指标；事实源在 ontology/quality.py。 */
export function getOntologyQuality() {
  return api.get<ApiResponse<OntologyQualityReport>>(`${BASE}/ontology/quality`)
}

// ---------------------------------------------------------------------------
// 默认关能力读数面（§15.1「观测与开关」；只读，不提供写入开关）
// ---------------------------------------------------------------------------

/**
 * GET /observability/default-off：九项 D 组开关的现值形读数（治理门＝管理员）。
 * 现值由各项归属模块的谓词给出，服务端名册不第二次读 env，这里也不抄一份表。
 */
export function listDefaultOffFlags() {
  return api.get<ApiResponse<DefaultOffReadingsResponse>>(`${BASE}/observability/default-off`)
}

// ---------------------------------------------------------------------------
// CQ 追溯现值读数面（登录可读；名册与探针在 neurova/knowledge/ontology/cq_matrix.py）
// ---------------------------------------------------------------------------

/** GET /ontology/cq-matrix：元数据照 specs 票面，status 为探针现值（非抄表）。 */
export function listCqMatrix() {
  return api.get<ApiResponse<{ items: CqRow[] }>>(`${BASE}/ontology/cq-matrix`)
}

// ---------------------------------------------------------------------------
// 企业源描述符（B14：只校验/落库/回显，真实连接器另立项）
// ---------------------------------------------------------------------------

export function listEnterpriseSources() {
  return api.get<ApiResponse<{ items: EnterpriseSourceConfig[]; total: number }>>(
    `${BASE}/enterprise/sources`,
  )
}

export function getEnterpriseSource(sourceId: string) {
  return api.get<ApiResponse<EnterpriseSourceConfig>>(
    `${BASE}/enterprise/sources/${encodeURIComponent(sourceId)}`,
  )
}

/** 手动触发一轮摄取（批 C1，仅管理员）：enabled=False 零读取；400 带定位拒因。 */
export function triggerEnterpriseIngest(sourceId: string) {
  return api.post<
    ApiResponse<{
      result: { admitted: number; rejected: number; batches: number; truncated: boolean; cursor: string } | { skipped: boolean; reason: string }
      source: EnterpriseSourceConfig
    }>
  >(`${BASE}/enterprise/sources/${encodeURIComponent(sourceId)}/ingest`)
}

/** 提交映射描述符（仅管理员）：非法描述符 400 带定位拒因且零落库。 */
export function submitEnterpriseSource(body: {
  source_id: string
  descriptor: EnterpriseDescriptor
  enabled?: boolean
}) {
  return api.post<ApiResponse<EnterpriseSourceConfig>>(`${BASE}/enterprise/sources`, body)
}

/** 连接健康探测（仅管理员）：适配器 health() 三态，探测不改变"已注册"语义。 */
export function getEnterpriseSourceHealth(sourceId: string) {
  return api.get<ApiResponse<EnterpriseSourceHealth>>(
    `${BASE}/enterprise/sources/${encodeURIComponent(sourceId)}/health`,
  )
}

/** 手动触发单条附件取回（批 C7c 第三块，仅管理员）：存档源逐条可控、引用过期 502 原话。 */
export function triggerEnterpriseMedia(sourceId: string, msgId: string) {
  return api.post<
    ApiResponse<{ status: string; msgid?: string; path?: string; size?: number; media_name?: string }>
  >(`${BASE}/enterprise/sources/${encodeURIComponent(sourceId)}/media`, { msg_id: msgId })
}

/** 删除连接器（仅管理员）：只删配置，已摄取事实/断言保留（响应 message 点名）。 */
export function deleteEnterpriseSource(sourceId: string) {
  return api.delete<ApiResponse<{ source_id: string }>>(
    `${BASE}/enterprise/sources/${encodeURIComponent(sourceId)}`,
  )
}

// ── W2/W3：函数层与状态机（specs/2026-11-12 §4/§5，runtime 分区）─────────────

export function listOntologyFunctions() {
  return api.get<ApiResponse<OntologyFunctionRow[]>>('/knowledge/ontology/functions')
}

export function createOntologyFunction(body: {
  function_id: string
  expr_text: string
  output_predicate: string
  input_bindings?: Record<string, unknown>
  materialization?: 'observe' | 'enforce'
  label?: string
  definition?: string
  enabled?: boolean
}) {
  return api.post<ApiResponse<OntologyFunctionRow>>('/knowledge/ontology/functions', body)
}

export function deleteOntologyFunction(functionId: string) {
  return api.delete<ApiResponse<{ function_id: string }>>(
    `/knowledge/ontology/functions/${encodeURIComponent(functionId)}`)
}

/** W2：函数 dry 求值。P1-12（审计 2026-11-14）：后端是
 * POST /ontology/functions/{function_id}/compute，function_id 在路径里，
 * 放请求体必 404。 */
export function computeOntologyFunction(body: {
  function_id: string
  subject?: string
}) {
  const { function_id, ...rest } = body
  return api.post<ApiResponse<OntologyComputeResult>>(
    `/knowledge/ontology/functions/${encodeURIComponent(function_id)}/compute`, rest)
}

export function listOntologyStateMachines() {
  return api.get<ApiResponse<OntologyStateMachineRow[]>>(
    '/knowledge/ontology/state-machines')
}

export function createOntologyStateMachine(body: {
  term_id: string
  states: string[]
  transitions: Array<{ from: string; to: string; guardPredicate?: string }>
  initial_state: string
  event_bindings?: Array<Record<string, unknown>>
  enabled?: boolean
}) {
  return api.post<ApiResponse<OntologyStateMachineRow>>(
    '/knowledge/ontology/state-machines', body)
}

export function deleteOntologyStateMachine(termId: string) {
  return api.delete<ApiResponse<{ term_id: string }>>(
    `/knowledge/ontology/state-machines/${encodeURIComponent(termId)}`)
}

export function listOntologyActions() {
  return api.get<ApiResponse<OntologyActionRow[]>>('/knowledge/ontology/actions')
}

export function createOntologyAction(body: {
  action_id: string
  label?: string
  bound_tool: string
  risk_tier?: string
  param_schema?: Record<string, unknown>
  precondition?: Record<string, unknown>
  impact?: string[]
  state_change?: Record<string, unknown>
  enabled?: boolean
}) {
  return api.post<ApiResponse<OntologyActionRow>>('/knowledge/ontology/actions', body)
}

export function runOntologySimulation(body: {
  scope?: Record<string, unknown>
  agent_id?: string
  hypotheses?: { facts?: Array<Record<string, unknown>> }
}) {
  return api.post<ApiResponse<OntologySimulationReport>>(
    '/knowledge/ontology/simulations', body)
}

export function listOntologySimulations(limit = 50) {
  return api.get<ApiResponse<OntologySimulationRow[]>>(
    `/knowledge/ontology/simulations?limit=${limit}`)
}

export function recordOntologyDecision(body: {
  category: string
  scenario: string
  reasoning: string
  outcome: string
  confidence: number
  owner_id?: string
}) {
  return api.post<ApiResponse<OntologyDecisionRow>>(
    '/knowledge/ontology/decisions', body)
}

export function listOntologyDecisions(limit = 50) {
  return api.get<ApiResponse<OntologyDecisionRow[]>>(
    `/knowledge/ontology/decisions?limit=${limit}`)
}

export function linkOntologyDecisions(decisionId: string, body: {
  target_decision_id: string
  link_kind: 'caused' | 'influenced' | 'precedent'
}) {
  return api.post<ApiResponse<Record<string, unknown>>>(
    `/knowledge/ontology/decisions/${encodeURIComponent(decisionId)}/links`, body)
}

export function traceOntologyDecision(decisionId: string, direction: string) {
  return api.get<ApiResponse<{ decision_id: string; chain: OntologyDecisionChainNode[] }>>(
    `/knowledge/ontology/decisions/${encodeURIComponent(decisionId)}/trace?direction=${direction}`)
}

export function searchDecisionPrecedents(q: string, limit = 5) {
  return api.get<ApiResponse<Array<Record<string, unknown>>>>(
    `/knowledge/ontology/decisions/precedents?q=${encodeURIComponent(q)}&limit=${limit}`)
}

export function listChunkStrategies() {
  return api.get<ApiResponse<Array<{ strategy_id: string; kind: string; params: Record<string, unknown> }>>>(
    '/knowledge/ontology/chunk-strategies')
}

export function runOntologySparql(query: string) {
  return api.post<ApiResponse<Record<string, unknown>>>(
    '/knowledge/ontology/sparql', { query })
}

export function runOntologyAbduce(body: {
  subject_label: string
  predicate: string
  object_term: string
}) {
  return api.post<ApiResponse<Record<string, unknown>>>(
    '/knowledge/ontology/abduce', body)
}

export function exportOntologyGraphML(agentId?: string) {
  const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''
  return api.get<string>(`${BASE}/ontology/export.graphml${q}`, {
    responseType: 'text',
    params: agentId ? { agent_id: agentId } : {},
  })
}

export function exportOntologyGexf(agentId?: string) {
  const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''
  return api.get<string>(`${BASE}/ontology/export.gexf${q}`, {
    responseType: 'text',
    params: agentId ? { agent_id: agentId } : {},
  })
}

export function exportOntologyCypher(agentId?: string) {
  const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''
  return api.get<string>(`${BASE}/ontology/export.cypher${q}`, {
    responseType: 'text',
    params: agentId ? { agent_id: agentId } : {},
  })
}

export function exportOntologyCsv(agentId?: string) {
  const q = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''
  return api.get<string>(`${BASE}/ontology/export.csv${q}`, {
    responseType: 'text',
    params: agentId ? { agent_id: agentId } : {},
  })
}

export function queryOntologyAccountability(params?: {
  subject?: string; actor?: string; start?: string; end?: string
}) {
  const qs = Object.entries(params ?? {})
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&')
  return api.get<ApiResponse<{ events: Array<Record<string, unknown>>; ledger_counts: Record<string, number>; total: number }>>(
    `/knowledge/ontology/accountability${qs ? '?' + qs : ''}`)
}

export function verifyDigestChain() {
  return api.get<ApiResponse<Record<string, unknown>>>('/knowledge/foundation/integrity')
}

export function searchCommunityGraph(query: string, mode: string, limit?: number) {
  return api.post<ApiResponse<Array<Record<string, unknown>>>>(
    '/knowledge/ontology/community-search', { query, mode, limit: limit ?? 5 })
}

export function listOntologyCommunities() {
  return api.get<ApiResponse<Array<{ community_id: string; level: number; member_labels: string[]; summary_text: string }>>>(
    '/knowledge/ontology/communities')
}

/** U4：社区检测手动触发（管理员）——标签传播＋持久化，返回社区行。 */
/** Ontology 设置卡读数（登录可读）：facts 重抽开关现值与来源。 */
export function getOntologySettings() {
  return api.get<ApiResponse<{ extract_on_update: boolean; source: 'env' | 'setting' | 'default' }>>(
    '/knowledge/ontology/settings')
}

/** Ontology 设置卡写面（管理员）：facts 重抽开关。 */
export function updateOntologySettings(extractOnUpdate: boolean) {
  return api.put<ApiResponse<{ extract_on_update: boolean }>>(
    '/knowledge/ontology/settings', { extract_on_update: extractOnUpdate })
}

export function detectOntologyCommunities() {
  return api.post<ApiResponse<Array<{ community_id: string; level: number; member_labels: string[]; summary_text: string }>>>(
    '/knowledge/ontology/communities/detect', {})
}

/** U3：消解队列 blocking 预读数（候选对数/全对数对比——分对数级剪枝证据）。 */
export function getOntologyBlockingStats() {
  return api.get<ApiResponse<{ full_scan: number; blocking: number; reduction_pct: number }>>(
    '/knowledge/ontology/blocking-stats')
}

/** U3：术语级 conflict_policy 声明读数（数据驱动裁决策略的 UI 回显）。 */
export function getOntologyConflictPolicy(termId: string) {
  return api.get<ApiResponse<{ term_id: string; conflict_policy: string }>>(
    `/knowledge/ontology/conflict-policy/${encodeURIComponent(termId)}`)
}

/** U5：webhook 接收面读数（enabled＋密钥指纹掩码——绝不回传明文）。 */
export function getWebhookConfig() {
  return api.get<ApiResponse<{ enabled: boolean; secret_env: string; secret_fingerprint: string }>>(
    '/knowledge/ontology/webhook/config')
}

/** U5：webhook 密钥轮换（进程内 env 指针写新随机值，回新指纹）。 */
export function rotateWebhookSecret() {
  return api.post<ApiResponse<{ secret_fingerprint: string }>>(
    '/knowledge/ontology/webhook/rotate', {})
}

/** U5：webhook 模拟推送（ok/duplicate/bad_signature 三态——诚实验收面）。 */
export function simulateWebhookPush(mode: 'ok' | 'duplicate' | 'bad_signature') {
  return api.post<ApiResponse<Record<string, unknown>>>(
    '/knowledge/ontology/webhook/simulate', { mode })
}

/** U5：webhook 幂等去重台账读数。 */
export function getWebhookDedupStats() {
  return api.get<ApiResponse<{ rows: number; sources: number }>>(
    '/knowledge/ontology/webhook/dedup-stats')
}

// ---------------------------------------------------------------------------
// Ontology rules（P2-21：自 GraphWorkbenchPage 裸写 URL 收编；路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** 规则写入口径（create 带 rule_id，update 不带——主键走路径）。 */
export interface OntologyRulePayload {
  head_predicate: string
  body: Array<Record<string, unknown>>
  basis: string
}

/** Create an ontology rule. */
export function createOntologyRule(data: OntologyRulePayload & { rule_id: string }) {
  return api.post<ApiResponse<unknown>>('/knowledge/ontology/rules', data)
}

/** Update an ontology rule. */
export function updateOntologyRule(ruleId: string, data: OntologyRulePayload) {
  return api.put<ApiResponse<unknown>>(
    `/knowledge/ontology/rules/${encodeURIComponent(ruleId)}`, data)
}

/** Delete an ontology rule（basis 走 query 留审计痕迹）。 */
export function deleteOntologyRule(ruleId: string, params?: { basis?: string }) {
  return api.delete<ApiResponse<null>>(
    `/knowledge/ontology/rules/${encodeURIComponent(ruleId)}`, { params })
}
