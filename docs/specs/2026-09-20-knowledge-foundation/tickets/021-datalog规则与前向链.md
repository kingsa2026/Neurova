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
