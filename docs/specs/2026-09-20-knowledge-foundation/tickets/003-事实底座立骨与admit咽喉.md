# 003 事实底座立骨与 admit 咽喉骨架

**Blocked by**: 002
**阶段**: E1（设计文档 §4.2、§5）

## 目标
`KnowledgeFactStore` 能建库、`admit()` 能作为唯一写入口收一条最小事实并原样查回——
示踪弹打穿 schema + 逻辑 + 查询 + 测试。

## 涉及层
- [ ] 数据层：`data/knowledge/knowledge_facts.db`，migration 版本域 `knowledge_foundation`；
      本票只建 `knowledge_subjects` + `knowledge_facts` 两表（形状见 §4.2，
      骨架取自 `temporal_knowledge_graph.py:181-196`），其余表由后续票按段扩
- [ ] 逻辑层：`foundation/knowledge_facts.py` 的 `KnowledgeFactStore`（`get_*`/`reset_*` 成对工厂、
      `threading.RLock`）+ `foundation/admission.py` 的 `KnowledgeAdmissionGate.admit()` 七段骨架
      （§5；本票实现入参契约与段编排，未落地的段显式抛 `NotImplementedError` 而非静默跳过）
- [ ] 单例纪律：底座不得在构造期打开外部服务连接，默认 `:memory:` 只允许测试传入
- [ ] 测试：`tests/unit/knowledge/test_fact_store_core.py`、`test_admission_gate_skeleton.py`

## 验收标准
- 一条事实 admit → 按 `subject_key` 查回，字段无丢失。
- 生产装配路径**不得**再出现无参构造导致 `:memory:` 的形态（对照 B01 的成因）。
- 未实现段调用即抛，测试里不允许用"跳过该段"来变绿。
- 幂等：同库重复初始化不报错、不重复建表。
