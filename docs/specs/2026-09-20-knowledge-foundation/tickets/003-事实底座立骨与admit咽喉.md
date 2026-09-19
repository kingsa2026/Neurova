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

## 完成状态（2026-09-20，16 用例全绿）

落位：`neurova/knowledge/foundation/knowledge_facts.py`（`KnowledgeFactStore`）、
`admission.py`（`KnowledgeAdmissionGate` / `AdmissionRequest` / `AdmissionReceipt` /
`AdmissionSegmentMissing`），migration 版本域 `knowledge_foundation`。

对设计做的三处收口（均为减少后续返工，不扩大范围）：
1. **两表一次建全目标列**（溯源/生命周期/使用回写列先占位、值为 NULL/默认），
   004–010 只加行为不再 ALTER 同一张表——这是扩展-收缩里"扩展"的前置。
2. `KnowledgeFactStore(db_path=None)` 直接 `ValueError`，**不留默认值**：
   B01 的成因就是无参构造悄悄落 `:memory:`，这里从签名上堵死（测试须显式传 `":memory:"`）。
3. 缺段策略：`admit()` 默认抛 `AdmissionSegmentMissing` 并逐名列出缺段；
   只有显式 `allowPendingSegments=True` 才放行，且回执带 `pendingSegments` 供下游识别。
   七段中 `identity_resolution` 当前只有精确名+别名（006 补相似度与聚类），
   `segmentsApplied` 里写明 `(base exact/alias)`，不冒充全链已通。

**踩到并修的坑（值得记住）**：用例名写成 `def testXxx`（漏下划线）时 pytest **既不收集也不报错**，
整份文件静默不跑——本次 13 个用例 collected 0 items 才发现。已加常驻守卫
`tests/unit/core/test_pytest_collection_hygiene.py`（全仓扫 `def test[A-Z]`，当前 0 残留）。

