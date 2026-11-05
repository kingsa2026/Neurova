# Neurova 本体引擎的 OWL 2 RL 子集声明（B11 L5，2026-11-05）

> 定位：本文是"本引擎支持/不支持哪些 OWL 2 RL 公理"的**唯一事实源**，
> 守卫 `test_owl2rlProfile.py` 与引擎逐条互咬。三态标注：
> **物化**（推导落库，账本可溯）/ **校验**（写前/dry-run 判定，不落推导）/
> **仅导出**（互操作声明，无运行时承诺）。语义上界选 OWL 2 RL 而非 DL：
> RL 面向规则引擎与 RDBMS，与本仓 Datalog 片段＋SQLite 递归 CTE 同构；
> DL/HermiT/Pellet 与"零第三方依赖、本地单进程"冲突（§12.12）。

## 支持的公理（每条标注三态与机制锚点）

| 公理 | 三态 | 机制锚点 |
|---|---|---|
| rdfs:subClassOf | 物化（is_a 传递闭包）＋校验（父链一致性） | `ontology_terms.parent_term_id`＋`auto_transitive:is_a`（B8/B9） |
| rdfs:subPropertyOf | 物化（`auto_subproperty:*` 搬移规则） | `ensureAutoRules`（B8） |
| rdfs:domain | 校验（写前定义域判定，不物化为 is_a） | `validation.py` domain 项 |
| rdfs:range | 校验（写前值域判定，不物化） | `validation.py` range 项 |
| owl:inverseOf | 物化（`auto_inverse:*` 反向补边） | `rule_engine._fireInverse`（B8 inverse 形状） |
| owl:SymmetricProperty | 物化（`auto_symmetric:*` 双向补边） | 同上 |
| owl:TransitiveProperty | 物化（`auto_transitive:*` 闭包＋递归 CTE） | `transitiveClosure`＋auto 规则 |
| owl:FunctionalProperty（functional） | 校验（`cardinality=1` 闭合世界拒写，**不推 owl:sameAs**） | `validation.py` cardinality 项 |
| 受限 hasValue（条件类） | 物化（`shape=conjunction`：基类∩hasValue ⇒ 自动归入） | `rule_engine` 条件类（B1）；灰度 `NEUROVA_CONDITION_CLASSES_ROUTE` 默认 off（D-06） |
| 分层否定（Datalog not） | 物化（否定只指向更浅层） | `rule_engine._stratify` |

## 不支持的公理（登记即拒或形状不存在，不静默半支持）

| 公理 | 拒法 |
|---|---|
| owl:unionOf / complementOf / oneOf | 规则形状闭集只认 relay/conjunction/inverse（`registerRule` 未知形状即 RuleError） |
| owl:equivalentClass（完整形式） | 条件类只支持"基类∩hasValue"受限形；完整等价类（多条件任意组合、匿名类嵌套）不在 DSL 内 |
| owl:sameAs | 明确不做（§6：自动合并误伤不可逆；跨词表用 skos:exactMatch，实体合并走 canonical ID＋人工审批） |
| 任意嵌套/聚合/算术 | `rule_engine.py:3` 边界声明：那是函数层不是规则语言 |
| OWL 2 DL 完整语义 / 外部推理机 | 零第三方依赖决策（specs/2026-09-20 六项） |

## 物化与灰度

- 推导事实一律经唯一写咽喉（`_admitDerivedFact`，`derived_by`＋账本），撤销精确。
- 条件类物化默认**观察态**（记账不进检索主路，`NEUROVA_CONDITION_CLASSES_ROUTE=1` 翻主路）；
  转正须 L9 的 CQ/检索 A-B 读数（§12.6 设计 5）。
- 物化模式按规则类 observe/enforce 复用 B1 灰度口径，不新增第二套开关体系。
