# 024 血缘查看器与 Turtle 导出

**Blocked by**: 022, 023
**阶段**: E4（收口 G01 的用户可见面）

## 目标
从一条答案依据点进去，能看到逐跳血缘链，并可导出标准文本格式。

## 涉及层
- [x] API：`GET /api/v1/knowledge/facts/{id}/lineage`
- [x] UI：知识页新增血缘抽屉；`citation.py` 的句柄机制从记忆域扩到知识域，使答案可回指第 X 条依据
- [x] 导出：自拼 RDF/Turtle 文本（纯格式化，零新增依赖）
- [x] 测试：`tests/unit/knowledge/test_turtle_export.py` + 前端血缘渲染用例

## 验收标准
- 一条推导事实可从 UI 走到原始陈述文本。
- 导出的 Turtle 可被自身解析器读回（不引外部校验器），字段往返无损。
- 无血缘数据的事实显式标注缺失维，不以空链冒充"已溯源"。

## 完成状态（2026-09-21）

| 落点 | 内容 |
| --- | --- |
| `foundation/lineage_view.py` | `FactLineageView.trace(factId)`：断言跳（谁/何时/介质/原文/活动/链位+摘要）+ 推导跳（规则 + 前提及其原文）+ `missing[]` + `provenance_state`。只走一层推导，前提若又是推导的，再请求一次它的 trace |
| `ontology/turtle.py` | `serialize/serializeFact` + `parseTurtle`：Turtle 谓语列表子集，写读共用一份字形定义（`_safePredicate`/`literal`/`_splitTopLevel`），形状对不上抛 `TurtleSyntaxError` 而不是半解析 |
| `api/endpoints/knowledge_core.py` | `GET /facts/{fact_id}/lineage`、`GET /facts/{fact_id}/turtle`（`text/turtle`）；未知事实 404，不回空对象 |
| `memory/citation.py` | 句柄扩到知识域：`fact_id → f1`，解开写 `fact_id="…"` 而不是冒充 `memory_id`；`attrFor(handle)` 是唯一的字段选择处 |
| `agent/{tkg,graph}_retriever_adapter.py` | 两条事实检索器的载荷带 `fact_id`，句柄才认得出这是底座事实 |
| `components/KnowledgeLineageDrawer.vue` | 抽屉：三元组头 + 缺维告警 + 时间线两形跳 + 前提可点回上级 + 导出按钮 |
| `pages/KnowledgePage.vue` | 冲突队列事实侧每条加"查看血缘"，先看清来源再裁决 |

### 三条判据各自怎么落的

1. **推导事实从 UI 走到原始陈述文本**：`test_derivedFactWalksToItsPremisesOriginalText`
   （后端）+ 抽屉用例"列出前提并把前提的原始陈述一起带出来"。前提原文取自前提自己的
   断言行，不在推导跳里另存一份——否则同一段文字又出现两个权威。
2. **Turtle 可被自身解析器读回、字段无损**：`test_exportedTurtleParsesBackWithEveryField`
   钉的正是最难的一条：`他说："青海湖是高原湖泊"\n第二行` —— 中文、内嵌引号、换行
   全在一次往返里。解析器按引号状态切 token（`_splitTopLevel`），不靠 `split()`。
3. **缺维显式**：`missing` 为 `assertions` / `activity` / `medium_ref` /
   `premise_statements`（后端命名），前端 `LINEAGE_DIM_KEYS` 映射到两段式驼峰 locale 键
   （i18n 守卫不许蛇形键，这张表就是翻译本身），认不出的维度走
   `lineageMissingOther` 带原文兜底，绝不显示裸键。空 `hops` + 有 `missing` 时告警与
   空态同时出现——"这里没内容"和"这条没溯源"必须长得不一样。

### i18n 与提交面

22 个新键 × 11 份 locale（`conflictViewLineage` + `lineage*`）。locale 文件在本轮被他人的
`collab.*` 在途件同时改着，所以 locale 只按 hunk 切分提交（HEAD + 我这 22 键），
他人在途的 hunk 原样留在工作树。

### 读数

后端：`tests/unit/knowledge/test_turtle_export.py` 10 例、
`tests/unit/api/test_knowledge_lineage_endpoint.py` 4 例、
`tests/unit/api/test_knowledge_integrity_endpoint.py` 4 例、
`tests/unit/memory/test_citation_registry_weknora.py` 新增 `TestFactHandlesInKnowledgeDomain` 5 例。
前端：`KnowledgeLineageDrawer.test.ts` 8 例；`vue-tsc --noEmit` 0 错；
`vitest run src/pages src/components` 584 passed / 1 failed——那 1 例是
`ChatPage.reasoningFollow` 对 `MessageSteps.vue` 模板文本的正则，本工单未触碰该文件。
locale 一致性用例仍报 34 个 `collab.*` 键缺失，属他人在途件（设计文档 §11.5 已登记）。
