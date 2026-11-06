/**
 * 本体静态目录（升级计划 UI-0/UI-3）。
 *
 * - CQ 追溯矩阵逐行照抄唯一事实源 docs/specs/2026-11-05-ontology-cq.md（§CQ 追溯矩阵）；
 *   该表增删改时本文件必须同步，显示处标注「静态表」。
 * - **D 组默认关矩阵不在本文件**：项名与现值一律取
 *   `GET /knowledge/observability/default-off`（服务端名册 `neurova/knowledge/defaultOffFlags.py`）。
 *   这里曾抄过一张八行静态表，票面是九项——漏的那一项是 D-03，而抄表那侧的守卫用
 *   `rows.length` 相等自证，漏一行照样绿（2026-11-06 撤表，改由读数面供数）。
 */
import type { CqRow } from '@/types/ontology'

export const CQ_ROWS: CqRow[] = [
  {
    cqId: 'CQ-01',
    question: '哪些订单当前被归为高风险订单？',
    actor: '知识使用者',
    priority: 'P1',
    query: 'GET /v1/knowledge-graph/{agent_id}/knowledge-graph（条件类推导实例 HighRiskOrder）',
    testId: 'tests/unit/knowledge/ontology/test_conditionClassDerivation.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-02',
    question: '某主体与另一主体之间有哪些直接关系？',
    actor: '知识使用者',
    priority: 'P1',
    query: 'POST /v1/knowledge/access/query（facts 检索，谓词过滤）',
    testId: 'tests/unit/knowledge/ontology/test_ontology_gate.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-03',
    question: '从某实体出发沿传递关系能到哪些实体？',
    actor: '知识使用者',
    priority: 'P1',
    query: 'ForwardChainingEngine.transitiveClosure(agentId, predicate)',
    testId: 'tests/unit/knowledge/ontology/test_forward_chaining.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-04',
    question: '抽取出的未登记关系词形去了哪里、如何转正？',
    actor: '本体管理员',
    priority: 'P1',
    query: 'GET/POST /v1/knowledge/ontology/relation-candidates*',
    testId: 'tests/unit/knowledge/ontology/test_relationMapping.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-05',
    question: '一条推导结论由哪些规则与前提得出、如何精确撤销？',
    actor: '本体管理员',
    priority: 'P1',
    query: 'DerivationLedger.premisesOf(factId) / dropRule',
    testId: 'tests/unit/knowledge/ontology/test_derivation_retract.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-06',
    question: '检索命中里哪些是推导事实、哪些是观察事实？',
    actor: '知识使用者',
    priority: 'P1',
    query: '检索命中 derivation 标注（derivation_citation 单源）',
    testId: 'tests/unit/knowledge/test_derivationCitation.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-07',
    question: '本体全库能否确定性交换导出、读回无损？',
    actor: '集成方',
    priority: 'P1',
    query: 'GET /v1/knowledge/ontology/export.ttl',
    testId: 'tests/unit/knowledge/ontology/test_turtleExport.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-08',
    question: '一条事实的说法来源与证据链是什么？',
    actor: '审计员',
    priority: 'P1',
    query: 'knowledge_assertions / knowledge_activities（血缘段）',
    testId: 'tests/unit/knowledge/test_digest_chain_integrity.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-09',
    question: '上层本体（实体/事件/代理）如何约束类型层级？',
    actor: '本体建模者',
    priority: 'P1',
    query: 'upper-lite 种子（seedUpperLite）＋父链查询',
    testId: 'tests/unit/knowledge/ontology/test_upperLite.py',
    status: 'implemented',
  },
  {
    cqId: 'CQ-10',
    question: '某类事实在历史某时点是否成立（双时态）？',
    actor: '审计员',
    priority: 'P2',
    query: 'asOf/knownAt 查询（B11 落地，REST 参数未接线）',
    testId: 'tests/unit/knowledge/ontology/test_bitemporalQuery.py',
    status: 'planned',
  },
  {
    cqId: 'CQ-11',
    question: '写入前能否按自定义形状（SHACL 语义）做完整性校验？',
    actor: '本体管理员',
    priority: 'P2',
    query: 'shapes 注册表＋dry-run（B10 落地，POST /ontology/validate）',
    testId: 'tests/unit/knowledge/ontology/test_ontologyShapes.py',
    status: 'implemented',
  },
]

/** upper-lite 静态树（与 neurova/knowledge/ontology/upper_lite.py 七类一致；仅展示用）。 */
export const UPPER_LITE_TREE = {
  root: 'Entity',
  children: [
    { label: 'Continuant', children: ['Agent', 'Document', 'Concept'] },
    { label: 'Occurrent', children: ['Event'] },
  ],
}
