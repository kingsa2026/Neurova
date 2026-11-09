/**
 * 本体语义栈前端类型（升级计划 UI-0–UI-4，事实源：
 * docs/specs/2026-11-05-ontology-capability-upgrade-plan.md §15.5）。
 *
 * 纪律：
 * - 禁止 any 直塞；后端蛇形字段保持原文（契约逐字段对齐，不做翻译层）；
 * - 列表信封统一 `{items,total,next_cursor}`（B12 L6 分页口径）；
 * - severity 三级闭集 violation/warning/info（§15.4 校验分级）；
 * - 双时态 asOf（valid time）与 knownAt（transaction time）两轴独立，绝不合并。
 */

// ---------------------------------------------------------------------------
// 信封与分级
// ---------------------------------------------------------------------------

/** B12 cursor 键集分页信封（GET /ontology/terms 实测形状）。 */
export interface OntologyEnvelope<T> {
  items: T[]
  total: number
  next_cursor: string
}

/** §15.4 校验分级闭集：violation 红阻断 / warning 黄记账 / info 灰遥测。 */
export type Severity = 'violation' | 'warning' | 'info'

/** dry-run 单条 finding（与后端 validation.py 投影逐字段对齐）。 */
export interface OntologyFinding {
  kind: string
  rule: string
  message: string
  term_id?: string
  subject_key?: string
}

/** B2/B6 共用校验路径的单行结果（verdict ∈ {pass, violation}）。 */
export interface OntologyValidateRow {
  index: number
  subjectKey: string
  findings: OntologyFinding[]
  violations: OntologyFinding[]
  verdict: 'pass' | 'violation'
}

export interface OntologyValidateSummary {
  total: number
  passed: number
  violated: number
  unregistered: number
}

export interface OntologyValidateResponse {
  results: OntologyValidateRow[]
  summary: OntologyValidateSummary
}

// ---------------------------------------------------------------------------
// 术语（L2/B8/B10 写面）
// ---------------------------------------------------------------------------

/** 术语行（GET /ontology/terms 单行；多语言 labels/alt_labels 为 lang→text 映射）。 */
export interface OntologyTerm {
  term_id: string
  kind: 'concept' | 'relation' | 'property' | string
  label: string
  parent_term_id: string | null
  domain_terms: string[]
  range_terms: string[]
  range_kinds: string[]
  cardinality: number | null
  disjoint_with: string[]
  required_props: string[]
  inverse_of: string
  symmetric: boolean
  transitive: boolean
  aliases: string[]
  // G1：定义描述项（GB/T 48000.3 表 1/表 2 第 4 项；空 = 这一维没依据）
  definition: string
  // G3 结构化列表：外部 IRI 映射（kind 闭集：skos_exactMatch/skos_closeMatch/
  // skos_relatedMatch/equivalentClass，校验在注册表）
  external_iris: Array<{ kind: string; iri: string }>
  deprecated: boolean
  replaced_by: string
  identity_keys: string[]
  labels: Record<string, string>
  alt_labels: Record<string, string[]>
  module: string
  namespace: string
  iri_base: string
  qualifier_schema: Record<string, unknown>
  version: string
  created_at: string
  updated_at: string
  /** 声明形状与展开并存（读面附带，值域从哪来的另一投影）。 */
  range_terms_effective?: string[]
}

/** POST/PUT /ontology/terms 写面（None＝PUT 保留现值；显式空列表＝清空声明）。 */
export interface OntologyTermWrite {
  term_id?: string
  kind: 'concept' | 'relation' | 'property' | string
  label?: string
  parent_term_id?: string | null
  domain?: string[] | null
  range_terms?: string[] | null
  range_kinds?: string[] | null
  cardinality?: number | null
  disjoint_with?: string[] | null
  required_props?: string[] | null
  inverse_of?: string | null
  symmetric?: boolean | null
  transitive?: boolean | null
  aliases?: string[] | null
  definition?: string | null
  external_iris?: Array<{ kind: string; iri: string }> | null
  deprecated?: boolean | null
  replaced_by?: string | null
  // B10 L2 / B11 L3 声明字段：与后端 TermWriteRequest 逐字段对齐（None＝PUT 保留现值）。
  labels?: Record<string, string> | null
  alt_labels?: Record<string, string[]> | null
  module?: string | null
  identity_keys?: string[] | null
  qualifier_schema?: Record<string, unknown> | null
  version?: string
  basis?: string
}

// ---------------------------------------------------------------------------
// 规则与 schema
// ---------------------------------------------------------------------------

export interface OntologyRule {
  rule_id: string
  head_predicate: string
  head_subject_var: string
  head_object_const: string
  shape: 'relay' | 'conjunction' | 'inverse' | string
  body: Array<Record<string, unknown>>
  enabled: boolean
  version: string
}

/** GET /ontology/schema（术语 + 规则 + 版本，租户分区）。 */
export interface OntologySchemaData {
  terms: OntologyTerm[]
  rules: OntologyRule[]
  schema_version: number
  tenant_scoped: boolean
}

// ---------------------------------------------------------------------------
// 关系候选（B8，只人工批准）
// ---------------------------------------------------------------------------

export interface RelationCandidate {
  candidate_id: string
  tenant_id: string
  surface: string
  normalized_surface: string
  source_entry_id: string
  source_text: string
  confidence: number
  status: 'pending' | 'approved' | 'rejected' | string
  created_at: string
  reviewed_at: string
  reviewed_by: string
  promoted_term_id: string
}

// ---------------------------------------------------------------------------
// 推导（B11 解释链）
// ---------------------------------------------------------------------------

export interface DerivationPremise {
  fact_id: string
  rule_id: string
  rule_version: string
}

/** GET /ontology/derivations/{fact_id}；derived=false 表示观察事实，不伪造解释。 */
export interface DerivationChain {
  fact_id: string
  derived: boolean
  rule_id: string
  rule_version: string
  premise_count: number
  premises: DerivationPremise[]
  confidence: number | null
  derivation_kind: string
}

// ---------------------------------------------------------------------------
// 访问门面（B3 四动词）与事实
// ---------------------------------------------------------------------------

/** POST /access/query → /search 的命中行（条目/事实可见域检索）。 */
export interface FactQueryItem {
  id: string
  knowledge_id?: string
  title: string
  content: string
  category?: string
  tags?: string[]
  source?: string
  created_at: number
  updated_at?: number
  agent_id?: string
  metadata?: Record<string, unknown>
  duplicate?: boolean
  sources?: Array<{ source?: string; source_type?: string; ingest_time?: string }>
}

export interface FactQueryBody {
  query: string
  category?: string
  tags?: string[]
  source?: string
  author?: string
  source_type?: string
  ocr_used?: boolean
  page_min?: number
  updated_after?: number
  source_modified_after?: string
  source_modified_before?: string
  asOf?: string
  knownAt?: string
}

/** POST /ontology/validate 候选三元组（dry-run 入参）。 */
export interface ValidateTriple {
  subjectLabel: string
  subjectKey?: string
  predicateTermId: string
  objectTerm: string
  qualifier?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// 发布治理（B6/B12）
// ---------------------------------------------------------------------------

export interface PipelineRunResponse {
  baselineId: string
  applied: { terms: number; rules: number; facts: number }
  summary: Record<string, unknown>
}

export interface PipelineDiffResponse {
  added: Record<string, unknown>
  removed: Record<string, unknown>
  changed: Record<string, unknown>
}

export interface PipelineRollbackResponse {
  restored: { terms: number; rules: number; shapes: number }
  audit: Record<string, unknown>
  activity_id?: string
}

/** B10 L4 形状注册表行（GET /ontology/shapes）。 */
export interface OntologyShape {
  shape_id: string
  tenant_id?: string
  target_kind: 'relation' | 'concept'
  target_term_id: string
  path: Record<string, unknown>
  constraint_kind: string
  constraint: Record<string, unknown>
  severity: 'violation' | 'warning' | 'info'
  message: string
  enabled: boolean
  version: string
}

export interface OntologyShapeWrite {
  shape_id: string
  target_kind: 'relation' | 'concept'
  target_term_id?: string
  path?: Record<string, unknown>
  constraint_kind: string
  constraint: Record<string, unknown>
  severity?: 'violation' | 'warning' | 'info'
  message?: string
  enabled?: boolean
  version?: string
}

// ---------------------------------------------------------------------------
// 稳定 IRI（B12）
// ---------------------------------------------------------------------------

/** GET /ontology/iri/{iri} 命中形态；未知 IRI 走 404（前端显式报错，不静默）。 */
export interface IriResolution {
  kind: 'term'
  term_id: string
  term: OntologyTerm
}

// ---------------------------------------------------------------------------
// 质量报告（B13 L9）与企业源（B14）
// ---------------------------------------------------------------------------

/** GET /ontology/quality 单条缺陷（OOPS! 结构子集，可计算项才报）。 */
export interface QualityFinding {
  kind: string
  severity: Severity
  target: string
  message: string
}

/** GET /ontology/quality：term_count + findings + 两个可计算指标。 */
export interface OntologyQualityReport {
  tenant_id: string
  term_count: number
  findings: QualityFinding[]
  metrics: { consistency: number; conciseness: number }
}

/** POST/GET /enterprise/sources 单源回显。 */
export interface EnterpriseSourceConfig {
  source_id: string
  descriptor: Record<string, unknown>
  cursor: string
  enabled: boolean
  /** 适配器是否真注册进进程内单表——与「描述符已落库」两态互不冒充。 */
  adapter_registered: boolean
  /** 页面重设计配套批：添加/更新时间（ISO 串，落库时间戳）。 */
  created_at?: string
  updated_at?: string
  /** 已获取数据量＝knowledge_assertions.actor_id='source:<id>' 计数。 */
  ingested_count?: number
}

/** GET /enterprise/sources/{id}/health 探测结果（三态＋原话）。 */
export interface EnterpriseSourceHealth {
  source_id: string
  status: 'ok' | 'degraded' | 'error' | string
  reason: string
}

/** 描述符写面形状（与后端 schema_mapping.validateDescriptor 同口径）。 */
export interface EnterpriseDescriptor {
  sourceType: 'sql' | 'erp_api' | 'event_stream' | 'file' | 'http_pull' | 'chat' | string
  columns: string[]
  subject: { template?: string; column?: string }
  predicate: { termId: string }
  object: { kind: 'column' | 'template' | 'term' | 'literal'; column?: string; template?: string; termId?: string; value?: string }
  qualifiers?: Record<string, string>
  validFrom?: string
  validUntil?: string
  /** 变体字段（VARIANT_CLOSED_SETS 单点）：file→format+path；sql→driver；erp_api/chat→vendor。 */
  format?: string
  path?: string
  driver?: string
  vendor?: string
  // 连接扩展字段（registry.buildAdapter 逐类型消费；specs/2026-11-07 页面重设计配套批）
  /** sql：游标列（标识符白名单）/网络地址/库表查询/凭据→环境变量名映射 */
  cursorColumn?: string
  host?: string
  port?: string | number
  database?: string
  table?: string
  query?: string
  credentialEnv?: Record<string, string>
  /** erp_api：基地址/金蝶 formId/用友 tokenPath */
  baseUrl?: string
  formId?: string
  tokenPath?: string
  /** chat：捕获面数据库路径（缺省走数据根 channel_ingress.db） */
  ingressDb?: string
  /** chat：来源两态（批 C7c 甲案）——capture 缺省 / archive 会话存档投影面（仅 wecom） */
  chatSource?: 'capture' | 'archive'
  /** chat archive：官方 C 动态库路径（部署侧显式给，不猜官方件名） */
  archiveSdkPath?: string
  /** chat archive：存档专用 Secret 的环境变量名（指针，值不进配置） */
  archiveSecretEnv?: string
  /** chat archive：publickey_ver → 私钥路径；裸文件名在约定目录解析（统一存放路径口径） */
  archivePrivateKeys?: Record<string, string>
  /** chat archive：隐私白名单（通道层落库前过滤） */
  archiveRoomAllowlist?: string[]
  archiveUserAllowlist?: string[]
}

// ---------------------------------------------------------------------------
// 静态目录（CQ 追溯矩阵 / D 组默认关矩阵）
// ---------------------------------------------------------------------------

/** CQ 行（docs/specs/2026-11-05-ontology-cq.md 追溯矩阵；status 闭集）。 */
export interface CqRow {
  cqId: string
  question: string
  actor: string
  priority: 'P1' | 'P2'
  query: string
  testId: string
  status: 'implemented' | 'planned'
}

/**
 * D 组默认关读数行（§13 / §15.1「观测与开关」）。
 *
 * 形状来自服务端名册（`neurova/knowledge/defaultOffFlags.py`）经
 * `GET /knowledge/observability/default-off` 回显——不是前端抄的静态表：
 * 抄表那一份漏过 D-03，而它的守卫用长度相等自证，漏一项照样绿。
 */
export interface DefaultOffReading {
  flagId: string
  envKey: string
  declaredDefault: string
  mode: string
  isDefault: boolean
  homeModule: string
  readoutRef: string
}

export interface DefaultOffReadingsResponse {
  items: DefaultOffReading[]
}
