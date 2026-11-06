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
  DerivationChain,
  EnterpriseDescriptor,
  EnterpriseSourceConfig,
  FactQueryBody,
  FactQueryItem,
  IriResolution,
  OntologyEnvelope,
  OntologyQualityReport,
  OntologySchemaData,
  OntologyShape,
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

/** 提交映射描述符（仅管理员）：非法描述符 400 带定位拒因且零落库。 */
export function submitEnterpriseSource(body: {
  source_id: string
  descriptor: EnterpriseDescriptor
  enabled?: boolean
}) {
  return api.post<ApiResponse<EnterpriseSourceConfig>>(`${BASE}/enterprise/sources`, body)
}
