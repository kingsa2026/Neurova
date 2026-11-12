# 本体能力问题目录（CQ）与需求追溯（B9 L0，2026-11-05）

> 定位：本文件是本体层**能力问题（Competency Questions）的唯一事实源**（升级计划 §12.1）。
> 每条 CQ 映射到查询与测试，做需求追溯；`test_cqTraceability.py` 按本表断言
> 零孤儿（引用的测试文件必须存在）、P1 必须有查询与测试、status 闭集。
> 术语表与领域边界随后附；CQ 的增删改必须连同查询与测试一同落，不许只有问题没有判据。

## 领域边界

| 维度 | 范围 |
|---|---|
| In scope | 企业/个人知识的三元组事实（主体-谓词-客体＋限定）、类型层级、关系特征、推导与溯源、多租户隔离、交换导出 |
| Out of scope | OWL DL 完整语义、SPARQL 文本查询、第三方 SHACL 引擎、真实企业源连接器（B14 只预留接口）、BFO/SUMO/DOLCE 整包 |
| 数据源 | 文档条目抽取（graph_bridge）、对话轮次、MCP 信息源、企业源接口（预留） |
| 租户 | 本体按租户分区（v25+）；种子按租户首跳补齐 |
| 语言 | 中文为主（label/别名/词形归一），导出带 `@zh` 语言标记 |
| 时效 | `valid_from/valid_until`（valid time）＋`recorded_at/retracted_at`（transaction time）；双时态查询归 B11 |

## 术语表（L0 随附）

| 术语 | 定义 | 别名 | 关联 term_id |
|---|---|---|---|
| 事实（Fact） | 一条主体-谓词-客体的断言行，带限定/置信/来源/时效 | 三元组 | `knowledge_facts` |
| 主体（Subject） | 规范化后的实体，canonical_label＋别名＋主类型 | 实体 | `knowledge_subjects` |
| 术语（Term） | 本体词表的一行：concept/relation/property | 词表项 | `ontology_terms` |
| 条件类（Condition Class） | 由基类＋属性条件合取定义的等价类，机器自动归入实例 | 高风险订单式类 | `ontology_rules(shape=conjunction)` |
| 关系特征（Relation Feature） | 逆/对称/传递/函数（cardinality=1）| 属性特征 | `ontology_terms` v29 列 |
| 推导（Derivation） | 由规则从前提事实推出的结论，账本可溯、可精确撤销 | 推理结论 | `knowledge_derivation_edges` |
| 候选（Candidate） | 抽取出的未登记关系词形，等人工批准/拒绝 | 未知关系 | `ontology_relation_candidates` |

## CQ 追溯矩阵

| cq_id | question | actor | priority | query | test_id | status |
|---|---|---|---|---|---|---|
| CQ-01 | 哪些订单当前被归为高风险订单？ | 知识使用者 | P1 | `GET /v1/knowledge-graph/{agent_id}/knowledge-graph`（条件类推导实例，`HighRiskOrder`） | tests/unit/knowledge/ontology/test_conditionClassDerivation.py::TestConditionClassDerivation | implemented |
| CQ-02 | 某主体与另一主体之间有哪些直接关系？ | 知识使用者 | P1 | `POST /v1/knowledge/access/query`（facts 检索，谓词过滤） | tests/unit/knowledge/ontology/test_ontology_gate.py::TestFiveRules | implemented |
| CQ-03 | 从某实体出发沿传递关系能到哪些实体？ | 知识使用者 | P1 | `ForwardChainingEngine.transitiveClosure(agentId, predicate)` | tests/unit/knowledge/ontology/test_forward_chaining.py::TestTransitiveClosure | implemented |
| CQ-04 | 抽取出的未登记关系词形去了哪里、如何转正？ | 本体管理员 | P1 | `GET / POST /v1/knowledge/ontology/relation-candidates*` | tests/unit/knowledge/ontology/test_relationMapping.py::TestUnknownRelationCandidate | implemented |
| CQ-05 | 一条推导结论由哪些规则与前提得出、如何精确撤销？ | 本体管理员 | P1 | `DerivationLedger.premisesOf(factId)`／`dropRule` | tests/unit/knowledge/ontology/test_derivation_retract.py | implemented |
| CQ-06 | 检索命中里哪些是推导事实、哪些是观察事实？ | 知识使用者 | P1 | 检索命中 `derivation` 标注（derivation_citation 单源） | tests/unit/knowledge/test_derivationCitation.py | implemented |
| CQ-07 | 本体全库能否确定性交换导出、读回无损？ | 集成方 | P1 | `GET /v1/knowledge/ontology/export.ttl` | tests/unit/knowledge/ontology/test_turtleExport.py | implemented |
| CQ-08 | 一条事实的说法来源与证据链是什么？ | 审计员 | P1 | `knowledge_assertions`/`knowledge_activities`（血缘段） | tests/unit/knowledge/test_digest_chain_integrity.py | implemented |
| CQ-09 | 上层本体（实体/事件/代理）如何约束类型层级？ | 本体建模者 | P1 | upper-lite 种子（`seedUpperLite`）＋父链查询 | tests/unit/knowledge/ontology/test_upperLite.py::TestUpperLiteSeeds | implemented |
| CQ-10 | 某类事实在历史某时点是否成立（双时态）？ | 审计员 | P2 | asOf/knownAt 查询（B11 落地；W0-1 补 accessQuery 显式签名＋MCP 透传＋非法 4xx） | tests/unit/knowledge/ontology/test_bitemporalQuery.py | implemented |
| CQ-11 | 写入前能否按自定义形状（SHACL 语义）做完整性校验？ | 本体管理员 | P2 | shapes 注册表＋dry-run（B10 落地） | tests/unit/knowledge/ontology/test_ontologyShapes.py | implemented |
| CQ-12 | 数值属性能否参与计算（聚合/比较出结论）？ | 分析师 | P2 | 函数层（specs/2026-11-12 W2 落地：受限 AST＋selector 聚合＋咽喉入账） | tests/unit/knowledge/ontology/test_functionDerivationGovernance.py | implemented |
| CQ-13 | 对象当前处于什么状态、允许哪些迁移？ | 运维员 | P2 | 状态机（specs/2026-11-12 W3 落地：has_state＋迁移闭集＋事件桥） | tests/unit/knowledge/ontology/test_stateMachineValidation.py | implemented |
| CQ-15 | 动作的前置条件不满足时是否拒绝执行？ | 运维员 | P2 | 动作语义（specs/2026-11-12 W4 落地：precondition 不触工具＋单管道转交） | tests/unit/knowledge/ontology/test_actionPrecondition.py | implemented |
| CQ-14 | 假设某状态变化后下游会受什么影响？ | 运维员 | P2 | 推演（specs/2026-11-12 W5 落地：副本隔离零生产写＋diff 报告） | tests/unit/knowledge/ontology/test_simulationDiff.py | implemented |
| CQ-16 | 这个决定依据什么、导致了什么下游后果？ | 审计员 | P2 | 决策因果（specs/2026-11-12 W7 落地：决策台账＋caused 闭包 trace） | tests/unit/knowledge/ontology/test_decisionCausalChain.py | implemented |
| CQ-17 | 过去有没有同类场景的判例？ | 审计员 | P2 | 判例检索（specs/2026-11-12 W7 落地：词法混合计分，嵌入偏差登记） | tests/unit/knowledge/ontology/test_decisionPrecedents.py | implemented |

## 追溯规则

1. P1 CQ 的 `query` 与 `test_id` 不得为空；`test_id` 指向的文件必须真实存在（守卫：`test_referencedTestFilesExistZeroOrphan`）。
2. 新增能力必须先在此表补 CQ（或确认既有 CQ 覆盖），再落码——CQ 驱动、先红后绿。
3. `status` 闭集：`implemented`（查询与测试均已落）/ `partial`（部分落，注明缺口）/ `planned`（工作包待实施）。
4. **本表的 `status` 列是计划态（人管）**；产品页面的 CQ 表与通过率卡不再抄本表——
   元数据（问题/角色/优先级/查询/测试）由服务端名册
   `neurova/knowledge/ontology/cq_matrix.py` 照抄本票面（对拍守卫
   `test_cqMatrixReadout.py::test_registryMetadataMatchesSpecDocRowByRow` 钉漂移），
   `status` 由探针查产品面符号给**现值**（`GET /v1/knowledge/ontology/cq-matrix`，
   登录可读）：能力接线/退役自动翻转，不靠人改表。本表 status 变更时探针判据须同步对齐。
