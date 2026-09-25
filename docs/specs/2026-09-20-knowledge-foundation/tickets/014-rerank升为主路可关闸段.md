# 014 rerank 升为主路可关闸段（灭 B05）

**Blocked by**: 011
**阶段**: E2（§7）

## 目标
已有的精修能力（`knowledge/rerank/`）从旁路 API 进入对话主路，且可关闸、成本可控。

## 涉及层
- [ ] 逻辑层：主路末端接 `WeightRerankRunner`（默认，无外部依赖）与可选 `ModelRerankRunner`
      （provider 缺席即降级并记 `unevidenced`，不得静默当"已重排"）
- [ ] 配置：门控开关 + top-k 截断，避免整池重排引发成本尖峰
- [ ] 测试：`tests/unit/knowledge/test_main_path_rerank.py`

## 验收标准
- 关闸态与 011 开闸态逐条一致；开闸态 002 读数不降。
- `semantic_search_api.py` 与主路共用同一 runner 实现，不出现第二份排序逻辑。
- 模型重排缺席时的降级路径有显式读数，不冒充"已生效"。

---

## 完成状态（2026-09-20 实施）

**主路末端接上了一段可关闸的精排**：`knowledge/rerank/main_path.py` 的
`refineMainPathResults` 挂在 `hybrid_search_knowledge` 融合之后（`hybrid.py` 末端），
默认方法 `weight`（零外部依赖）。旁路 API 那份自己装配 runner 的代码删掉，
改成 `rerank_factory.buildRunner` 单源别名 —— **API 与主路共用同一份装配**，
这条本身有判据（`api._build_rerank_runner is rerank_factory.buildRunner`）。

**三条纪律**：先精排再截断（RRF 11–30 名的候选必须能被顶进前 10，否则精排只是在
已选定的池子里洗牌）；通道分一律取 `confidence_breakdown`，不在这一步重算；
**模型通道不在事件循环里跑** —— `hybrid_search_knowledge` 是同步函数却被 async 适配器
直接调用，provider 是同步 HTTP，跑进去会卡住整个服务，因此主路请求 model 而当前在循环内时
退化为加权，且结果上的 `rerank_method` 如实写 weight（标成 model 就是冒充已生效）。

**默认态是量出来的，不是拍的**（冻结锚点：30 例 / admin 全语料 / top-5）：

| 态 | recall@5 | MRR | 未命中率 | 未命中例 |
|---|---|---|---|---|
| 关闸 | 0.855489 | 0.83 | 0.1 | architecture / general / big_verify |
| 开闸 | 0.855489 | **0.831667** | 0.1 | 同上 |
| 冻结基线 | 0.855489 | 0.83 | 0.1 | 同上 |

关闸逐位等于基线（旧行为一字未动，且不带 `rerank_score` 新字段）；开闸召回与未命中率
一字未动、MRR 略升 ⇒ 判据"开闸读数不降"成立，默认翻向开。**并且证明它不是空接**：
真检索下 top-5 确实换序（`蜂群并发成本护栏` 的第 5 名从 `f9a4c251` 变 `f94dba01`；
`记忆` 查询的前两名互换）。

**判据**（`tests/unit/knowledge/test_main_path_rerank.py` 13 例 + `test_hybrid_service.py` 增 1 例）：
RRF 序与加权和序相反的场景下重排生效并盖 `rerank_score`/`rerank_method`；截断发生在精排之后；
候选池严格 `limit * poolFactor`（用替身 runner 数交来的文档数，成本上限不能只在嘴上）；
分数取自 breakdown 不重算；provider 缺席/为 None 都退化且 note 带原因；
后端故障（`RerankBackendError`）继续上抛，不许被一次静默退化抹平。

**一处需要判据解释的旧用例**：`test_four_routes_breakdown` 断言的是 RRF 融合段的 top-1，
主路精排上桌后它不再是最终序 —— 改为显式关闸测融合段，另开一例断言"默认态下融合之上
还有一段精排、最终序是精排序、`rrf_score` 不被抹掉"。不是把旧断言改绿，是把两段的合同分开钉。

回归：`tests/unit/knowledge/` 556 passed / 0 failed；`tests/unit/agent/` 1161 passed
（`test_post_chat_p0_latency_observability` 一例在全目录并发跑时因机器负载超时，
单跑该文件 21 passed —— 属 §11.5 已登记的时序脆弱族，非本票引入）；
`tests/unit/api -k "semantic or rerank or hybrid"` 37 passed。
