# 021 Datalog 规则与前向链（G09）

**Blocked by**: 020
**阶段**: E4（§6.3）

## 目标
从已有事实推出新事实，且推导可解释。

## 涉及层
- [ ] 数据层：`ontology_rules`（head/body、`negation_as_failure`、`stratification_level`、`enabled`）
- [ ] 逻辑层：`ontology/rule_engine.py` 的 `ForwardChainingEngine`——分层前向链 + 递归 CTE 传递闭包；
      **零新增依赖**，不引规则库
- [ ] 不做清单（写进模块 docstring）：SPARQL 文本查询、OWL DL 完整语义、外部推理服务
- [ ] 测试：`tests/unit/knowledge/ontology/test_forward_chaining.py`、`test_stratified_negation.py`

## 验收标准
- 传递性规则 + 3 条原始事实推出预期新事实数。
- 含否定的分层程序不产生矛盾双结论（有反例用例）。
- 规则循环依赖时报错并指出环，不静默截断。

---

## 完成状态（2026-09-20 实施）

**规则形状 = 三元组上的 Datalog 片段**（迁移 v9 建 `ontology_rules`，SQL 由
`ontology/rule_engine.py` 持有、`foundation_schema` 统一注册）：

    head(X, Z) :- b1(X, Y), b2(Y, Z)            # 二元接力
    head(X, Y) :- b(X, Y)                       # 搬移
    head(X, Z) :- b1(X, Y), b2(Y, Z), not b3(X, Z)   # 分层否定
    传递闭包 = 同谓词自接力的特例，交给 SQLite 递归 CTE

不做清单写在模块 docstring 里（SPARQL 文本查询 / OWL DL / 外部推理服务 / 聚合与算术 /
存在量词造新实体）：那些要的不是规则引擎而是函数层，偷偷塞进规则语言只会让"能表达什么"
再次变成只有作者知道的事。

**三条实现决定，都是被测试逼出来的**：
- **推导事实经咽喉入库**，带 `qualifier.derived_by` 与 `medium_ref=rule:<id>` 的断言。直插 SQL
  会造出一批"没有主体消解、没有血缘、没有置信"的孤儿行——B03/G12 换个入口复活。
- **不动点判据认"新行"不认"重新算出同一行"**：折回已有行（`dedupedByContent`）不计产出，
  否则每轮都"产出"同一批事实、永远不收敛。
- **写了新事实就点燃相关规则**（`admit()` 段3 后半 → `fireFor(agentId, predicate)`），
  并用线程局部标志禁止推导再触发推导。规则引擎没人调用就是又一个 B01，所以这不是可选项。

分层与循环：注册时算层（正边取 `max(依赖)+1`），否定只准指向**更浅层已算完**的谓词；
绕出环来直接 `RuleError` 并指出是哪条边，被拒的规则不留半行。
`test_negationThroughCycleIsRefusedWithTheLoopNamed` 钉的就是这个。

**判据与实测**（`tests/unit/knowledge/ontology/test_forward_chaining.py` 10 例）：
链尾 v9 且两张本体表就位；两条 `part_of` 原始事实恰好推出**一条** `甲 part_of 丙`
（多一条算错，少一条也算错）；再跑一轮零新增；推导行可解释（qualifier 指到规则、
断言来源是 `rule:`）；否定真的挡住结论且被挡的那条不落地；正递归自己收敛；
闭包一次查到全链（甲→乙→丙→丁 从甲可达三个），数据里有环也不吊死、不产自反副产物；
五种坏形状（无肯定正文 / >2 原子 / 中项接不上 / 变元不是单个大写字母 / 元素键不合法）
全在写入处拒。

回归：`tests/unit/knowledge` + `tests/unit/agent` **1746 passed / 0 failed**
（迁移链守卫随 v9 更新：必查表集加 `ontology_rules`，链尾断言 9）。
真数据复核：生产库升到 v9 后 130 条目 / 92 事实 / 87 主体 / 分叉 0 未动，
检索 0.855489 / 0.831667 / 0.1 —— 没规则时推理段是零成本的空转体，一旦登记规则就自动生效。
