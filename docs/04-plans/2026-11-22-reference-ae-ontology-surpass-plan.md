# reference_ae 本体域超越实施计划（2026-11-22）

> **性质**：实施计划（备稿待拍板，源自同日 [reference_ae 本体域专项对照评测](../08-research/reference_ae_vs_neurova_ontology_evaluation_2026-11-22.md)）。
> **现状**：本体专项评分卡（8 维 20 子项，各 0–5）**Neurova 83/100 vs 参照系 ae 89/100，落后 6 分**。
> **目标**：同卡同锚点复评 **保底 90（反超 1）/ 标准 91 / 冲刺 93**；全部实施后逐子项回填评测报告。
> **纪律**：修复教义七条全适用——每卡先红后绿、live-verify 真后端自证、单一事实源（不建平行体系）、全命中点扫荡、净 LOC 纪律。凡 reference_y 批已落地项（三臂门禁/缺口审计/贡献度评估/映射 transform/impact 预标注/证据哈希绑定/位置锚定/逐论断引用）不重复立项。

---

## 0. 分值推演与卡片总表

缺口只在十个子项：A3/C1/C2/D1/D2/E2/G3/H2（落后）与 B1/G2（可冲刺）。已领先且满分的子项（A1/A2/B3/E1/F2/H1）不动。

| 子项 | 现分 | ae | 差 | 对应卡 | 目标 | 增量 |
|---|---|---|---|---|---|---|
| A3 标准形式化与公理 | 4 | 5 | −1 | U1 运行时 SHACL 校验档 | 5 | +1 |
| C2 查询能力与规模 | 3 | 5 | −2 | U2 查询缓存 + U3 批量装载 | 4 | +1 |
| C1 存储后端与持久化 | 3 | 5 | −2 | U8 图存储门面（需拍板） | 4 | +1 |
| D1 规则与符号推理 | 4 | 4 | 0 | U5 Rete v2 求值档 | 5 | +1 |
| D2 真值维护与时间推理 | 4 | 5 | −1 | U4 Allen 区间代数引擎 | 5 | +1 |
| E2 冲突检测与质量门 | 4 | 5 | −1 | U6 消解建议面+质量门阈值化 | 5 | +1 |
| G3 可视化与探索 | 3 | 5 | −2 | U7 Studio 三视图 | 4 | +1 |
| H2 文档/示例/部署 | 4 | 5 | −1 | U9 教程+示例集 | 5 | +1 |
| B1 数据源摄取与映射 | 4 | 5 | −1 | U10 列画像（机动） | 5 | +1 |
| G2 工具面 | 4 | 4 | 0 | U11 CLI+IDE 技能包（机动） | 5 | +1 |

**推演**：批一（U1–U3）+批二（U4–U6）+批三（U7/U9）= **+7 → 90，反超成立**；加 U8 = 91；再加机动 U10/U11 = 93。

| 批 | 卡 | 分值贡献 | 工作量 |
|---|---|---|---|
| 批一 P0（本周） | U1、U2、U3 | +2 | S+M+M |
| 批二 P1（下周） | U4、U5、U6 | +3 | M+L+M |
| 批三 P2（第三周） | U7、U9（必做）+U8（拍板） | +2～+3 | M-L+S+L |
| 机动 | U10、U11 | +2 | M+S-M |

---

## 1. 总原则（纪律映射到本计划）

1. **单一事实源**：SHACL 运行时只新增「求值器」，shapes 定义仍只有 `shapes.py` 的 `ShapeRegistry` 一处；图存储门面下 SQLite 仍是唯一默认生产实现；查询缓存的水位派生自库本身（免挂写入口钩子）；冲突消解只做**只读建议面**，不建第二写路径。
2. **先红后绿**：每卡红灯判据先行并实测红，再最小实现转绿；提交说明附红→绿输出。
3. **live-verify**：每卡完成在真后端（9527，注意清理遗留进程与代理变量）走真实链路自证。
4. **诚实边界**：不宣称未实现的能力（对照对方 HermiT/Pellet 占位桩的反面教材）；可选依赖未安装时显式 `not_supported`。
5. **全命中点扫荡**：涉及写入口的改动（缓存失效/SHACL enforce 段）先 grep 全部消费方再动手。

---

## 2. 批一 P0：补最深的两分（C 维 + A3）

### U1 运行时 SHACL 校验档（A3 4→5）

- **断点**：本仓 shapes 是 JSON DSL 五约束子集（`shapes.py`），`path_json` 存而未用；运行时校验只有内置六条+DSL 逐条判；无标准 SHACL 引擎语义（`shapes.py:8-9` 自述不做）。对方已证明「本体→SHACL 自动派生→pyshacl 运行时校验→违规解释」单文件可编排（对方 engine.py:200-402）。
- **改什么**：
  - 新增 `neurova/knowledge/ontology/shacl_runtime.py`：`validateShapesRuntime(store, tenantId, *, mode)` ——shapes **单源**仍取 `ShapeRegistry`，经既有 `export/shacl.py:exportShaclShapes()` 序列化为标准 sh: Turtle 作 shapes graph；数据图复用 `turtle.serializeAll()` 确定性投影；内部 **lazy import pyshacl**（fail-soft：未安装→`not_supported` 诚实返回，不装也能跑全仓）。
  - 三档开关 `NEUROVA_ONTOLOGY_SHACL_RUNTIME=off|shadow|enforce`（默认 off）：`enforce` 挂准入咽喉段 3 之后作段 3.5（`admission.py` 现有 `ontology.violations` 拒写点旁，不改动段 3 语义）；`shadow` 只记 findings 不拒写；violations 映射进既有三态严重级 findings 流。
  - REST 读面：`POST /ontology/validate/shacl`（dry-run 语义，返回结构化 violations+英文/中文解释）。
- **红灯**：构造违反 minCount/class 约束的事实集——`enforce` 档 admit 被拒且 finding 含 sh 路径解释；`off` 档同一数据照常入库（行为不变）；未装 pyshacl 时返回 not_supported 不抛裸异常。
- **绿灯**：红灯三项全转绿 + 内置六条校验零回归（A/B）+ 单源证明（运行时用的 shapes graph 与 `exportShaclShapes` 输出逐字节一致）。
- **live-verify**：真后端三态各验一次（off 放行/shadow 记账/enforce 拒绝），REST dry-run 面可用。
- **风险**：pyshacl 全图校验代价大 → 校验范围按 targetClass 圈定 subject 邻域子图，不开全图；依赖引入见 D-U1。
- **工作量**：M（2–3 天）。

### U2 SPARQL 查询缓存（带失效）（C2 前半）

- **断点**：`sparql_query.py:43-75` 每次查询都 `serializeAll` 全量重投影+rdflib 重解析；无缓存。对方有缓存但**无失效机制**（其代码自述缺陷）——本仓必须补失效。
- **改什么**：新增 `neurova/knowledge/ontology/query_cache.py`：投影图按 `(tenantId, terms_fingerprint, facts_watermark)` 键做进程内 LRU（上限 `NEUROVA_ONTOLOGY_SPARQL_CACHE`，默认 128）。`terms_fingerprint = max(terms.updated_at)+count`，`facts_watermark = max(facts.id)+count`——**水位派生自库本身，任何写入口都不需要挂钩子**（避免扫荡遗漏，天然单一事实源）。`runSparqlQuery` 改走缓存，命中免重投影。
- **红灯**：同一查询连续两次执行，第二次命中缓存（解析/投影计数打点断言）；插入新事实后同查询结果包含新事实（水位变化→失效正确）；跨租户键隔离（租户 A 写入不误伤租户 B 缓存）。
- **绿灯**：既有 SPARQL 契约测试零回归；同库态结果与不缓存时逐字节一致（确定性不变）。
- **live-verify**：真后端同查询两次延迟显著下降、写入后结果即时更新。
- **工作量**：S（1 天）。

### U3 批量装载契约（C2 后半）

- **断点**：事实入库仅逐条 admit；企业源初始化同步缺 bulk 形态。对方 bulk_loader（分批+进度回调+载入前校验）是成熟契约。
- **改什么**：新增 `neurova/knowledge/ontology/bulk_load.py`：`bulkLoadFacts(store, rows, *, batchSize=500, onProgress=None, dryRun=True)` ——**逐行仍走准入咽喉（不绕行）**，批内 `BEGIN IMMEDIATE` 事务，任一违规**整批回滚零落盘**（对齐 `pipeline.py` dry-run 语义），失败行号+原因回执；进度回调按批上报。REST：`POST /ontology/facts/bulk`（dryRun 默认 true）。
- **红灯**：1 万行构造、第 7 批混入违规 → 全量零落盘+失败行号准确；`dryRun=true` 零写入；进度回调次数 = ceil(n/batch)。
- **绿灯**：单条准入语义不变（A/B 零新增失败）。
- **live-verify**：真后端 bulk 端点跑通 dry-run→正式两段。
- **工作量**：M（2 天）。

---

## 3. 批二 P1：推理两卡+质量门（+3）

### U4 Allen 区间代数引擎接线（D2 4→5）

- **断点**：`upper_lite.py` 已声明 before/after/overlaps/during 时间词汇但明示「不得生成传递规则」（不推理）；`cognitive_layers/memory_layer/temporal_reasoner.py` 系死码（DCPM 接线审计已登记）；事实层已有 `valid_from/valid_until` 双时态列（knowledge_facts.py:76-77）。时间推理是对方明确强项（13 关系完整引擎+双时相 TMS）。
- **改什么**：
  - 新增 `neurova/knowledge/ontology/temporal_algebra.py`：`classifyIntervalRel(a, b)`（13 关系闭集判定）+ `compose(r1, r2)`（Allen 合成表，返回关系集合）。
  - **死码处置（先比后合）**：`temporal_reasoner.py` 零消费方，直接退役删除，能力由新模块承接（不保留第二份）。
  - 接线：从事实层读取带 `valid_from/until` 窗口的事实对，判定结果作为**派生事实过准入咽喉入账**（`source_kind=rule`，规则 id 前缀 `auto_temporal_`，纳入 derivation_ledger——可沿边精确撤销）；谓词单源用 upper_lite 词汇。触发时机=带时间窗口事实 admitted 后的增量求值（复用 U5 的触发骨架亦可）。
- **红灯**：13 关系判定对拍手工真值表全对；合成表抽验（如 before∘before=before、during∘overlaps 的合成集合）正确；删除前提事实后派生时间关系被精确撤销（账本沿边）。
- **绿灯**：upper_lite 现有四关系词汇语义零回归；不引入无界传递（D-U6 拍板边界内）。
- **live-verify**：真后端写入两条带时间窗事实→查询到派生时间关系→撤销前提→关系消失。
- **工作量**：M（2–3 天）。

### U5 Rete v2 求值档（D1 4→5）

- **断点**：`rule_engine.py:74` `EVALUATION_STRATEGIES=("full_replay","rete")`，其中 rete 仅 alpha 预筛；规则限 ≤2 正原子（:208-210）；逐事实 fireFor 全规则扫描，规模化弱。对方有完整 Rete（alpha/beta/token/terminal+激活去重）。
- **改什么**：新增 `neurova/knowledge/ontology/rete_network.py`：AlphaNode（谓词+元数预编译）/ BetaNode（绑定一致性合并）/ TerminalNode（结论过咽喉入账）+ 激活去重（防同绑定重复点火）。`EVALUATION_STRATEGIES` 增第三档 `"rete_network"`（默认仍 semi-naive 不变；`NEUROVA_ONTOLOGY_EVAL_STRATEGY` 可选）。该档内规则形状放宽至 **≤3 正原子合取与 relay 链式**（默认语言是否同步放宽见 D-U3）；分层否定语义不变（否定仍只指向更浅层）。
- **红灯**：同一规则集（含 3 原子合取、relay 链、分层否定、inverse）在 semi-naive 与 rete_network 两策略下**结论集逐条相等**（扩容现有 test_semiNaiveEquivalence 模式）；3 原子规则在旧语言下登记被拒、rete_network 档内正确点火且推导过咽喉。
- **绿灯**：既有前向链全量测试零回归；激活去重断言（同一绑定只点火一次）。
- **live-verify**：真后端切换策略档位跑同一数据集，结论与台账一致。
- **风险**：Rete 实现复杂度高 → 默认策略不变、等价性测试钉死，随时可退回。
- **工作量**：L（4–5 天）。

### U6 冲突消解建议面 + 质量门阈值化（E2 4→5）

- **断点**：`quality.py:61` consistency 恒 1.0 静态值；无阈值门；多源值冲突只有检测、无消解策略。对方有确定性质量门（阈值+metrics）与七策略消解族。
- **改什么**：
  - `quality.py`：metrics 改**可计算**——孤儿率/缺 label 率/逆关系单边数/引用完整率/父链环数（判据全部复用现有 findings 扫描，不新增第二套判定）；新增 `qualityGateCheck(report, thresholds)` 返回 `passed/threshold_failures`，阈值参数 `min_coverage/max_findings` 等；quality REST 端点回传 thresholds+failures（字段只增不改）。
  - 新增 `conflict_advice.py`：同 subject+predicate 多源冲突的**只读建议面**——策略闭集 `latest/highest_confidence/majority_vote/source_credibility/manual_review`（对方七策略裁剪为本仓语义），输出建议值+理由+涉及证据清单；**不自动改写**，落地仍走人工审批/既有写路径（D-U5）。
- **红灯**：恒 1.0 断言退役，构造孤儿/单边用例断言指标<1；阈值触发时 `threshold_failures` 非空且 passed=False；构造双源冲突（置信 0.9 vs 0.4）断言建议=highest_confidence 选中值且理由含证据引用。
- **绿灯**：quality 端点现有消费方零回归。
- **live-verify**：真后端 quality 面看真实指标；冲突建议面对构造冲突给出建议。
- **工作量**：M（2–3 天）。

---

## 4. 批三 P2：可视化+文档+存储门面（+2～+3）

### U7 Studio 决策/血缘/时间线三视图（G3 3→4）

- **断点**：决策台账/推导账本/双时态事实的数据面与 REST 齐全，前端无可视化消费；对方 Explorer 有 Decision/Lineage/时间线工作区。
- **改什么**：NeurUI Ontology Studio 增三只读面板：①决策因果图（吃决策台账 trace 端点，力导向/分层布局，caused/influenced/precedent 三边型）；②推导谱系（premises→conclusion 分层 DAG，规则/函数分色）；③双时态时间线（valid_from/until 区间条+asOf 拖动）。纯前端读面，不动后端契约；i18n 11 locale 对齐。
- **验收**：vitest+vue-tsc 0 错；真后端构造 ≥3 决策/2 因果边/5 推导链数据后三面板取数渲染正确。
- **工作量**：M-L（3–4 天）。

### U8 图存储门面（C1 3→4）【需拍板 D-U4】

- **断点**：本体域锁定单机 SQLite，无可插拔图后端；导出面已产出 GraphML/GEXF/Cypher 但无运行时挂接面。对方 RDF 五后端+LPG 四后端。
- **改什么**：新增 `neurova/knowledge/ontology/graph_backend.py`：`GraphBackend` 协议（add/query/serialize/drop 最小面）+ `SQLiteBackend`（现有存储行为**逐字节保持**的唯一生产实现）+ `resolveGraphBackend()`（`NEUROVA_ONTOLOGY_GRAPH_BACKEND=sqlite` 默认）；第二实现 `EmbeddedRdfBackend`（oxigraph，可选依赖 fail-soft）仅作契约能力证明，默认不切换。契约测试套件对两实现对拍。
- **红灯**：契约套件对 SQLiteBackend 全绿；EmbeddedRdfBackend 通过同一契约套件（若安装）；未安装 oxigraph 时 resolve 显式 not_supported。
- **工作量**：L（4–5 天）。**动存储层，拍板后再实施。**

### U9 本体教程 + 示例集（H2 4→5）

- **改什么**：指南 5 篇（建模入门/规则与推理/版本门禁与回滚/SPARQL 查询/九格式导出）落 docs 指南目录；`examples/ontology/` 3 个**离线可跑**脚本（建术语+形状校验、批量装载+门禁、导出互操作），每脚本头部写明预期输出。
- **验收**：示例逐个用 `.venv` 真跑，输出与文档一致；0-index 登记。
- **工作量**：M（2 天）。

---

## 5. 机动卡（冲刺 92–93，拍板后插队）

### U10 连接器列画像（B1 4→5）

- **改什么**：describeSchema 补列画像（distinct 数/null 率/min/max/样例值，采样上限 `NEUROVA_SCHEMA_PROFILE_SAMPLE`）；画像落 `ontology_catalog` 既有表（只增列）；schema_suggester 关系候选吃画像证据（唯一性/外键覆盖率加权）。**不铺新连接器**（广度不硬拼对方，深挖既有五驱动）。
- **工作量**：M。

### U11 `neurova-ontology` CLI + IDE 技能包（G2 4→5）

- **改什么**：CLI 薄壳四命令（terms/validate/export/sparql，全部转交既有处理函数，零业务复制）；技能包（SKILL.md 式提示词+工具清单）覆盖主流 IDE 生态——纯分发层，不建第二工具面。
- **工作量**：S-M。

---

## 6. 待拍板清单

| 项 | 问题 | 建议 |
|---|---|---|
| D-U1 | pyshacl 依赖引入方式 | extras/可选依赖 + lazy import fail-soft，**不入核心 requirements**；若入须锁版本并过依赖审计 |
| D-U2 | SHACL 运行时默认档位 | off 起步 → shadow 观察一周 → enforce 拍板晋升（默认关不误伤现网） |
| D-U3 | 规则语言是否同步放宽 3 原子 | 仅 rete_network 档内支持，默认语言保持 2 原子一个版本周期，观察后再议 |
| D-U4 | 图存储门面是否立项 | 建议立项（C1 是最大单项缺口），oxigraph 作可选依赖；SQLite 永远是默认实现 |
| D-U5 | 冲突消解是否允许自动改写 | 只做只读建议面+人工审批，不自动写（治理优先，避免第二写路径） |
| D-U6 | 时间派生关系是否生成传递规则 | 维持 upper_lite「不生成传递规则」原边界，传递性由 Allen 合成表在查询期给出，不入规则库 |

---

## 7. 不照搬清单

1. **不铺十余种数据源连接器**——广度不硬拼，深挖既有五驱动+画像。
2. **不做双 MCP/两套版本 API**——对方工具数漂移（16/22/15）正是单一事实源纪律防的病。
3. **不宣称 OWL DL/HermiT/Pellet**——本仓诚实边界声明是优势，勿学对方占位桩。
4. **不做内存图为主的知识图谱**——本仓写入即落库+审计的路线更符合治理定位。
5. **不做事后严重级分类替代写前门禁**——本仓 dry-run 整批拒绝+三臂对照保留并强化。
6. **不自动改写冲突事实**——建议面+人在环。

---

## 8. 执行顺序与依赖

```
周1：U2(缓存,S) ──┬── U1(SHACL,M) ──┬──（并行，互不依赖）
      U6a(质量门) ─┘                  │
周2：U3(批量装载,M) │ U4(Allen,M) ────┤（U4 依赖死码退役决策，无代码依赖）
周3：U5(Rete,L) │ U6b(冲突建议,M) │ U7(三视图,M-L)
周4：U9(教程示例,M) + 复评回填
拍板后插队：U8(存储门面,L) / U10(画像,M) / U11(CLI,S)
```

- U1 依赖 D-U1/D-U2 拍板；U8 依赖 D-U4；U5 的 3 原子放宽依赖 D-U3；U6b 依赖 D-U5；U4 依赖 D-U6。
- 其余卡之间无代码依赖，可两路并行。

---

## 9. 复评与总验收

1. **同卡同锚点复评**：20 子项逐项按 §2 锚点（0–5）重打，证据更新到实施后 file:line；结果回填评测报告 §3（新增「实施后」列）或出复评附记。
2. **总验收线**：保底 90（反超 ae 89）、标准 91、冲刺 93；未达保底须逐子项写明原因。
3. **过程纪律**：每卡提交附红灯/绿灯实测输出+live-verify 证据；涉及共享文件用 patch 法 A/B 自证零新增失败；净 LOC 超标须在提交说明列明去向。
4. **回退设计**：U1 三档开关随时回 off；U2 缓存可整体旁路；U5 策略档默认不变；U8 默认实现不变——四卡均「默认零行为变化」，风险可控。

---

## 10. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| pyshacl 全图校验性能 | enforce 档写延迟上升 | targetClass 圈定子图校验；shadow 档先观察；pyshacl 不可用时显式降级 |
| Rete 实现引入回归 | 推理结论错误 | 等价性测试逐条对拍+默认策略不变+随时可退 |
| 缓存水位失效遗漏 | 读到旧图 | 水位派生自库本身（max(id)+count），免挂钩子；契约测试覆盖写后失效 |
| 时间派生关系污染主路 | 检索被自动关系干扰 | 沿用物化档 observe/enforce 判据单源，observe 起步 |
| 前端三视图数据量 | 大台账渲染卡顿 | 分页+渲染上限，复用既有 REST 分页契约 |

---

## 11. 拍板与增补（2026-11-22，用户拍板：不分批不留候选，一次全做）

**拍板决议**：本计划全部卡片一次全量实施，原「三批/机动/后续候选」分期框架作废；§5 机动卡 U10/U11 转正式卡；推理域增补三张新卡 U12/U13/U14（源自推理引擎对照结论：对方反向链/解释生成/差分测试可鉴，本仓补齐后推理维 D1 冲 5 分）。六项待拍板全部按 §6 建议执行：

- D-U1 **做（2026-11-22 二次拍板升级）**：pyshacl 声明进 `requirements.txt` 与 `requirements-ci.txt`——install.py 与桌面端首启链都只消费 requirements.txt，声明即两条首启路径自动安装（单一事实源，不另造安装名单）；代码侧仍 lazy import + fail-soft（shacl_runtime.py 点名豁免，形态同 sparql_query.py 的 rdflib）；开发/测试环境装入 .venv。
- D-U2 **做**：`NEUROVA_ONTOLOGY_SHACL_RUNTIME` 默认 `off`，实现 off/shadow/enforce 三档；enforce 段挂 admission 段 3.5。
- D-U3 **做**：3 原子放宽仅限 `rete_network` 档内支持，默认语言保持 2 原子。
- D-U4 **做**：图存储门面立项，SQLite 为唯一默认生产实现，oxigraph 为可选第二实现（fail-soft，未装显式 not_supported），默认不切换。
- D-U5 **做**：冲突消解只做只读建议面 + 人工审批，不自动改写。
- D-U6 **做**：时间派生关系不生成传递规则、不入规则库；传递性由 Allen 合成表在查询/求值期给出。

### U12 反向链与定理证明（新增，D1 冲 5）

- **断点**：本仓只有前向链+溯因，无反向链目标证明；对方 `deductive_reasoner.py:190-511` 有合一器+反向链定理证明+论证校验。
- **改什么**：新增 `neurova/knowledge/ontology/backward_chaining.py`：`proveGoal(store, goalTriple, *, maxDepth)` ——从目标三元组反向展开：事实命中→证毕；否则枚举规则 head 匹配→递归证明全部 body 原子→返回证明树（规则 id+绑定+子证明）；环检测（目标栈）+深度上限（默认 16，`NEUROVA_ONTOLOGY_PROVE_DEPTH`）；与 `abduction.py` 共用解释树节点形态（fact/rule 步骤+missing 清单），**只读不写**（不产生派生事实，不碰咽喉——与 U4 前向派生严格分轨）。
- **红灯**：构造 3 原子 relay 链+2 条基础事实，`proveGoal` 对可证目标返回完整证明树、对不可证目标返回 missing 前提清单；目标环（A⇒B⇒A）在深度上限内终止不炸。
- **绿灯**：与前向链一致性——前向链能推出的结论，反向链必能证明（对拍测试）；既有溯因测试零回归。
- **工作量**：M-L（3 天）。

### U13 解释生成器（新增，D1/E1 增强消费面）

- **断点**：本仓溯因有解释树（`abduction.py:48-170`），但无统一的「推理路径/辩护」自然语言生成面；对方 `explanation_generator.py:138-462` 按 InferenceResult/Proof/AbductiveExplanation 生成结构化+模板化文本。
- **改什么**：新增 `neurova/knowledge/ontology/explanation.py`：`explainDerivation(store, factId)` / `explainProof(proofTree)` ——吃推导账本（derivation_ledger 既有前提边）与 U12 证明树，产出统一结构 `{conclusion, steps[{kind: fact|rule|function, ref, binding, premiseIds}], missing[], text}`，text 为中文模板化串（规则名/前提/结论三段式）；挂 MCP 溯因工具与 REST 读面复用（不建第二账本，纯投影）。
- **红灯**：对一条两级推导链产出 steps 长度=3（2 规则+1 事实）、premiseIds 与账本一致；对无推导事实返回纯 fact 步骤。
- **绿灯**：abduction 既有测试零回归；text 模板含规则 id 与前提三元组。
- **工作量**：M（2 天）。

### U14 真值维护差分测试（新增，护 D2 实施质量）

- **断点**：对方对 TMS/时序/工件索引配了差分测试（随机操作序列对拍参考实现）；本仓推导撤销/物化档缺同强度护栏。
- **改什么**：新增 `tests/unit/knowledge/ontology/test_derivationDifferential.py`：随机化操作序列（登记规则/断言事实/撤销前提/删规则/改版，种子固定可复现）对拍「精确撤销账本」vs「全量重放重建」两模型的结论集与账本一致性；覆盖 observe/enforce 两档读侧排除。
- **红灯/绿灯**：首跑即以当前实现跑通（护栏性质，无行为变更）；若暴露不一致即修根因。
- **工作量**：S-M（1–2 天）。

### 全量实施顺序（单一批次，按依赖并行）

```
波1（无共文件冲突，可三路并行）：U2 缓存 │ U6 质量门+冲突建议 │ U4 Allen+死码退役
波2：U1 SHACL 运行时（装 pyshacl）│ U3 批量装载 │ U12 反向链 │ U13 解释生成
波3：U5 Rete v2 │ U14 差分测试 │ U11 CLI+技能包
波4：U8 存储门面 │ U10 列画像 │ U9 教程示例 │ U7 前端三视图
收口：admission 段 3.5 接线 + REST 路由统一挂 + 全量 A/B + live-verify + 复评回填
```

路由统一挂：U1/U3/U6/U12/U13 的 REST 端点由主控在 `knowledge_ontology.py` 一次性集中添加（避免并行会话同文件冲突）；各实施卡只交付处理函数与测试。
