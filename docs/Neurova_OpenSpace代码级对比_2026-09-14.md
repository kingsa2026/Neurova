# Neurova × HKUDS/OpenSpace 代码级对比（2026-09-14）

> 对象：https://github.com/HKUDS/OpenSpace （港大数据科学实验室 HKUDS，7.7k★，MIT，Python 3.12+，~12 万行）
> 定位：**"The Skill Management Layer for AI Agents" —— AI Agent 的技能管理层**
> 本方基线：Neurova `neurova/skills*`、`neurova/skill_system*`、`neurova/evolution/*`、`tool_executor.py`、`context/orchestrator.py`、`post_chat_pipeline.py`
> 源码锚点：`E:/项目/openspace-compare`（浅稀疏克隆，仅 openspace/ 核心包 + docs/examples/benchmarks；未检出 apps/、tests/、assets/）
> 本报告只做分析与立项建议，不含实施。所有"借鉴"项均遵循增量原则（只提升不下降、不动核心框架）。

---

## 0. 一页结论

OpenSpace 是**目前对标过的所有项目里，与 Neurova 技能体系同域度最高的一个**（此前 Dify/OC/Langflow/QwenPaw 都是平台整体，工具技能只是切片；OpenSpace 整个产品就是"技能管理层"）。它的四层架构 —— **质量证据层 → 受控进化层 → 本地优先 Hub → Agent Harness** —— 恰好是 Neurova 已有的"封装→改进→评审→生命周期"闭环的**控制论强化版**。

核心判断：

1. **Neurova 的闭环"有回路、缺闸门"**。Neurova 的进化链（AutoSkillBuilder/AutoSkillImprover/genetic engine + C10 评审闸）是真实接线的差异资产（OpenClaw 专项对比已确认 OC 无此闭环），但进化产物的质量验证停在"人看 diff + 跑全量 pytest"；OpenSpace 停在"**机器可复核的行为证据**"——routing eval + replay eval + 反幻觉契约，人只裁决例外。
2. **Neurova 缺技能质量的"归因素"**。OpenSpace 把 选用→应用→完成→兜底 做成五计数漏斗，且用 `skill_phase_failed_skill_ids` 明令"**工具兜底完成不得记技能成功**"——这是技能统计不被污染的关键；Neurova 的 use_count/success 没有这层归因区分。
3. **信任态与开关正交是缺的维度**。OpenSpace 技能有三个独立维度：`is_active`（版本指针）/ `enabled`（复用开关，硬过滤）/ `trust_state`（provisional↔trusted，证据驱动，失败即刻降级）。Neurova 只有 enabled 一维 + C10 一次性审批，**没有"可逆的、随使用证据波动的信任态"**。
4. **技能/工具注入预算化是共识最大弱点**。OpenClaw 专项对比说"每轮全量注入 schema 是最大最便宜的优化点"但缺施工细节；OpenSpace 给了完整蓝图：delta 目录常驻（1% 上下文预算/250 字描述/超限比例压缩/100 条裁剪）→ DiscoverSkills 元数据 → Skill 工具全文三级渐进披露 + 阶梯检索（direct→keyword 高置信→BM25→embedding→LLM 只在置信不足时介入）。
5. **OpenSpace 自身有水分，引用需谨慎**：README 宣称拦截 prompt injection/凭据外泄，实现里阻断级只有 1 条字面规则；benchmark "65.2%→78.7%" 的 warm 分支把**同任务 verifier 输出打包成反馈技能注入**（含验收目标值），更接近"重放自进化"而非泛化收益；旧库无 trust 列时上传默认放行。这些在 §4 单独列账。

**评分（本次范围内维度）**：OpenSpace 技能管理层 **9.2 / Neurova 技能体系 7.4**。OpenSpace 胜在证据-进化-信任的控制论完备性与预算化注入；Neurova 胜在多用户协作模型、声明式权限六类、工具基因引擎与反思式文本进化（GEPA）、认知层纵深——这些 OpenSpace 没有。

---

## 1. 架构速览

### OpenSpace（四层，全部共享一个运行时）

```
openspace/
├── skill_engine/          # 41.7k 行 —— 核心：registry/store/protocol/analyzer/evolver
│   ├── evidence/          # 证据事件/包/水位/脱敏（store.py 2.5k 行）
│   ├── signals/           # 证据→质量信号（detector 决策表/policy 准入/reconciliation）
│   ├── triggers/          # ANALYSIS/QUALITY_SIGNAL/MANUAL 三类触发器 + SQLite 作业队列
│   ├── decision/          # 证据包→变异授权裁决（引用完整性校验）
│   ├── evolution/         # 流水线：admission→candidates→authoring(staging)→validator
│   │                      #   →behavior_eval(routing+replay)→commit→recovery
│   └── patch.py           # FULL/DIFF/PATCH 多文件补丁 + fuzzy 六级匹配
├── runtime/ + application.py   # 唯一执行契约 ExecutionRequest/ExecutionResult，
│                               #   CLI/TUI/MCP/gateway/dashboard 五入口共用
├── grounding/             # 33.9k 行：工具管线八段式/权限引擎/bash 只读分类器/沙箱/ToolRAG
├── cloud/                 # 8.7k 行：本地优先 Hub、上传信任门、包放置协议、遥测 outbox
├── host_skills/           # 教宿主 agent 用 OpenSpace 的两个 SKILL.md
└── benchmarks/terminal_bench  # frozen backbone cold/warm 实验
```

### 与 Neurova 的映射（**2026-09-15 落地后刷新**，原始判定保留在各行括注）

| OpenSpace | Neurova 对应 | 状态（09-15 刷新） |
|---|---|---|
| skill_engine/registry + store | skill_system.py(SkillRegistry) + skills/skill_service.py(manifest) + skill_pool_manager.py | ◐ 存储真源加固（manifest identity/漏斗/trust + 原子写）；**三套模型并存仍未归一**（重构级债，见 §8） |
| protocol.py（模型可见协议） | skills/skill_injection.py + orchestrator.build_tools_for_llm | ✅ 目录常驻接线（P0-3，预算化+provisional 软标注）；三级披露中元数据档由关键词/语义阶梯承担，无独立 DiscoverSkills 工具（$mention 覆盖） |
| evidence/ + signals/ + decision/ | 漏斗四计数+归因 / trust 观测一票 / source_evidence / 脱敏 / 作业队列 | ◐ 最小闭环在（P0-1/2+P1-2/3/4）；完整证据层（事件包/水位/detector 决策表）刻意不搬 |
| evolution/ 流水线 + 异步作业队列 | AutoSkillBuilder/AutoSkillImprover/skill_lifecycle/C10 评审闸 | ✅ 队列(P1-4)+熔断(P0-3 Wave E)+行为回归 routing 档(P1-1)；replay 档=harness+真执行器（ab_library.make_agent_ab_executor），提交对账=原子写+失败回滚（P1-5） |
| trust_state | usage 漏斗 + identity.trust 两态 | ✅ P0-2+Wave E：两态状态机+召回消费面（高 fallback/零完成熔断、目录 provisional 标注） |
| version DAG + .skill_id | manifest identity + version_history 线性修订链 | ✅ P1-6（最小 DAG 口径：单父边；多父合成未建）；skill_version_api 假数据全清 |
| cloud/ 上传门 | marketplace submit 证据门 + admin 人审 | ✅ P2-1（注入扫描+密钥 fail-closed+provisional 拒传） |
| grounding ToolRAG/lazy tools | A6 tool_search（既有！BM25+目录+三控制工具，Wave E 收口开关）+ 技能侧阶梯+语义档 | ✅ 行判定当时已过时（A6 已在位）；Wave E 补语义档(bge ONNX)+熔断+tool_search 三级开关 |

---

## 2. 逐机制对比（含双侧锚点）

### 2.1 技能身份与版本 DAG ★★

**OpenSpace**：
- 每技能目录带 `.skill_id` sidecar（`registry.py:46,207-233`）：导入生成 `{dir}__imp_{uuid8}`，进化产物 `{name}__v{gen}_{uuid8}` 并回写（`evolver.py:782,812`）。**ID 跨复制/迁移永不重生成**——云绑定、信任账本、DAG 全部以它为锚。
- 版本 DAG：每次变更 = 新 SkillRecord 节点（`types.py:43-57`）。FIX 原地换 ID、旧内容 `content_snapshot` 进库、仅最新版 `is_active`；DERIVED 多 parent 新目录；CAPTURED 根节点。边表 `skill_lineage_parents`（`store.py:341-348`），ancestry BFS/子树 API 齐备（`store.py:2399-2475`）。provenance_refs 记录"这个版本由哪个任务的哪份证据产生"。
- 重启防重：FIX 后路径不变 ID 变，sync 用 active path 集合兜底（`store.py:920-927`）。

**Neurova**：`Skill.version` 字段 + `AutoSkillImprover.apply_improvement` patch 位递增 + `config["revisions"]` 有界 5 条（`evolution/skill_improver.py:578-673`）；`skill_version_api.py:55` 版本表**硬编码假数据**。无血缘概念；市场技能跨复制无稳定身份。

**判定**：Neurova 的"版本管理演示级"是已知债。OpenSpace 的 sidecar + DAG 不是过度设计——**信任观测、上传门禁、行为回归全都要求"版本可指认"**，没有身份锚，质量数据就会像 09-07 技能安装 404（写侧漏迁）和 EKB 3920 垃圾事故那样再断一次。启发：技能身份 sidecar 化（低成本、manifest 已有扩展位）+ revisions 快照升级为带 parent 边的最小 DAG，先不追多 parent。

### 2.2 存储层

**OpenSpace**：单库 SQLite（`PROJECT_ROOT/.openspace/openspace.db`），WAL/busy_timeout 30s/读侧独立短连接 `query_only`（`store.py:478-515`），幂等 `IF NOT EXISTS`+`_ensure_column_locked` 迁移（`store.py:538-628`）。**计数器不做 Python 更新，原子 SQL + events/observations 聚合派生**（`types.py:498-500`、`store.py:2128-2137`）。

**Neurova**：manifest.json（每 agent 一份）+ catalog.json + experience_knowledge.db + evolution/*.json 多处分治；SQLite 用 `threading.RLock`。有 RLock 契约但无 WAL 口径与 query_only 读连接的做法值得核对现状。

**判定**：单库收口是方向但不是 P0（迁库有 EKB 事故教训：测试打真库）。可先做的：**质量计数器从"Python 累加写 JSON"改为 SQL 原子聚合派生**——Neurova 的 use_count 落 manifest 正是 09-08 审计里"写放大"的同类病灶。

### 2.3 多源发现与优先级

**OpenSpace**：`OPENSPACE_HOST_SKILL_DIRS`(env) → config skill_dirs → project(.claude/.openspace/.agents 三级) → user → bundled，**路径首见者胜**（`runtime/skill_registry.py:38-75`）；条件技能 `paths` glob 激活、未激活 SkillTool 直接 PermissionDeny（`registry.py:1050-1089`、`protocol.py:828-840`）；gitignored 目录不参与发现；嵌套去重（父有 SKILL.md 跳子树）。

**Neurova**：per-agent SkillService manifest + marketplace link + hub_client + pool 四路，无统一"发现优先级"（正是三套模型缝合处最容易打架的地方）。

**判定**：同路径优先级、条件激活（paths 门控）可借鉴，中优；与 Neurova 的 agent 级隔离正交，增量安全。

### 2.4 检索与注入预算化 ★★★（本次对比最大施工价值项）

**OpenSpace 模型可见协议（protocol.py，3942 行）**：
- **三级渐进披露**：① 目录常驻 = 每轮 **delta attachment**，只发新增技能，每条 `- name: description[- when_to_use]`（`agents/skill_context.py:41-75`、`protocol.py:111-138`）；② `DiscoverSkills` 工具 = 只回元数据永不回正文；③ `Skill` 工具 = 唯一全文通道，正文以 attachment 注入并附带 allowed_tools/model/effort/scope 上下文修改器（`protocol.py:1096-1147`）。
- **预算硬数字**（`protocol.py:57-63`）：清单预算 = 上下文窗口 ×4 字符 ×**1%**，无模型信息回退 8000 字符；单描述 ≤250；过滤清单 ≤30 条；技能 >100 先按优先级裁剪并追加"还有 N 个，请 DiscoverSkills 或 `select:<name>`"；超预算时 bundled 条目保底完整、其余按比例截描述，<20 字符只留名字（`:141-188,206-230`）。全部可在 SkillConfig 配（`config/grounding.py:296-319`）。
- **阶梯检索，LLM 兜底**（`protocol.py:497-614`）：direct 匹配(100)/唯一前缀(80) → keyword 打分（name×4/description×2/when_to_use×2/body×0.5+质量微调），高置信阈值 6.0 且领先 1.5× 即返回 → 否则 BM25(×3 top_k)→embedding cosine 混合（`skill_ranker.py:98-128`）→ 仍置信不足（score≥0.25、margin≥0.05、ratio≥1.15）才调 LLM 选择器；`select:` 前缀强制精确未命中**不得退化为语义检索**（防幻觉降级）；LLM 失败则**无技能继续**。embedding 缓存 pickle 落盘、`invalidate_cache(skill_id)` 显式失效（⚠️ 键不含内容哈希，原地改 SKILL.md 会陈旧——**Neurova 若做须把 body_sha256 入键**，registry 已有该字段）。
- **质量感知召回**：enabled 硬过滤 4 处；LLM 选择前质量过滤 `applied+fallback≥2 且 completions==0`、`selections≥2 且 fallback/selection>0.5` 直接剔除（`registry.py:1323-1354`）。

**Neurova 现状**：技能以 function-calling schema 每轮全量注入（`orchestrator.py:1748-1792`）；`render_skill_catalog` 实现了目录渲染+别名压缩但**全仓零调用方**；`$skill-name` mention 全文注入已对齐 Codex（12000 字符预算）；无按任务检索选技能（`enable_active_skill_acquisition` 默认关）。**OpenClaw 专项对比 #1 结论就是"每轮全量双注入是最大最便宜的优化点"——当时缺施工蓝图，现在有了。**

**判定/启发（P0 候选）**：
- 把 `render_skill_catalog` 接线为**增量 delta 目录**（仿 §2.4-①），带 1% 预算与压缩规则；
- 检索阶梯可**直接复用 Neurova 本地 bge ONNX 向量**做 embedding 级（免外部 API），keyword 级复用 `_skill_keywords_match_input`，LLM 级最后兜底——顺序与阈值照抄 OpenSpace；
- 质量过滤依赖 §2.5 的计数漏斗，先补计数后开过滤（增量不下降：过滤器默认关，计数就绪后开）。

### 2.5 质量漏斗与信任生命周期 ★★★

**OpenSpace**：
- 五计数漏斗 `total_selections/invocations/applied/completions/fallbacks` + `trust_successes/failures`（`types.py:455-496`）。
- **归因防污染是灵魂**（`store.py:1587-1659`、`types.py:344-350`）：success = 技能被实际应用 ∧ 任务完成 ∧ 不在 phase_failed 集合；failure = **仅**技能阶段失败（工具兜底救回的）；任务整体失败但无技能归因 → 只加 fallback 计数**不动 trust**。LLM 自述 `execution_status` 被 prompt 里显式声明"NOT ground truth"（`prompts/skill_engine_prompts.py:117-119`），事实以执行快照为准。
- 信任状态机（`store.py:1310-1354`）：失败即刻降 provisional；晋升需 `successes_since_failure ≥ 2` 且观测 `UNIQUE(skill_id, observation_id)`（observation_id=`task:{task_id}`，**每任务最多一票**，重复上报 ON CONFLICT 不计数）。进化产物出生即 provisional（`evolver.py:790,929,1069`）。
- 三维正交：trust 是软信号（目录打 `(provisional; success 3/5=60%)` 给 LLM 看）+ 云上传硬门禁；enabled 是硬过滤；is_active 是版本指针。

**Neurova**：`SkillService.use_count`（每轮 POST_EXECUTE 累加，`agent_core.py:1587-1672`）+ `skill_experience` applied 记录 + `AdaptiveToolWeights` 滑动窗口（**工具级有权重衰减，技能级没有**）。技能级无 applied/completions/fallback 漏斗、无归因区分、无可逆信任态。生命周期 active→stale→archived 是**时间驱动**（14/30 天无使用），不是**证据驱动**。

**判定/启发（P0 候选）**：技能级补 `selections/applied/completions/fallbacks` 四计数（采集点现成：orchestrator 选入 schema≈selected、tool_executor.execute_skill_tool 命中=invoked、post_execute=applied，**缺的是"任务完成归因"这一票**——可在 PostChatPipeline 收尾时按本轮任务成败 + skill_phase 失败标记回写）；加 `trust_state` 两态列 + 失败降级/两次独立成功晋升，与 stale 状态机共存（一个管时间、一个管质量）。这组数据同时喂 §2.4 召回过滤、§2.9 上传门禁、前端质量徽标——一次投入三处消费。

### 2.6 受控进化流水线 ★★★★（控制论范式差异最大项）

**OpenSpace 管线全貌**（`evolution/engine.py:75-281`）：

```
checkpoint/信号/人工 → TriggerJob（SQLite 异步队列，claim/attempts/stale 恢复）
→ EvidencePacket（profile 冻结视图：水位+必含 refs+预算+脱敏，缺 required→不足）
→ DecisionEngine（LLM 判例 + 确定性校验：evidence_claims 引用完整性、
   FIX 必须有 target skill_file ref；分析与 packet 事实冲突 → 以 packet 为准）
→ Admission（noop/candidate/direct；候选 merge_key 攒复发证据，partial unique index 防双挂起）
→ Authoring（staging-only：只写 staging/proposed，活跃目录零接触；
   FIX/DERIVED 可带 packet 审计工具，CAPTURED 一律禁工具）
→ Validator（确定性优先：schema/scope/secret/重复度/契约；语义审查只能加严）
→ BehaviorEval（提交闸：routing eval 正负触发词跑真实选择器 + replay eval
   基线 vs 候选跑同任务；静态检查永远不能批准，缺 runner 直接拒）
→ Commit（备份式原子：disk→skill_store→sidecar→registry_refresh，
   任一步失败 _rollback_disk；悬挂 committing 由崩溃对账恢复）
```

每个阶段自身也回写为证据 ref（`evidence/types.py:10-45` 后半段），全链路可审计；redaction 脱敏失败→整包构建失败宁可不产出（`packet_builder.py:285-291`）；密钥文件禁读（`allowed_read_roots` + `contains_secret`，`:559-564`）。

**Neurova 对应物**：触发=post_chat_pipeline 同步钩子（pattern mining/encapsulation/improver）+ 人工 create_skill；准入=C10 评审闸（人看 diff）+ Hermes 约束闸（尺寸≤15KB/增长≤20%/语义保持/全量 pytest）；产物=template pending→approve；回滚=revisions 有界快照。**闭环真实存在（差异资产，OpenClaw 确认 OC 无），但五个控制件缺位**：
1. 无异步作业队列（post 链同步跑，进化分析阻塞/失败即丢，无 attempts/stale 恢复）；
2. 无证据封闭集（improver 把失败 trace 直拼 prompt，无 packet 水位/profile/预算，**且无脱敏——会话原文进 LLM 有密钥外流面**）；
3. 无行为回归（pytest 是代码回归不是**技能行为回归**：routing 误召回/漏召回、改后同任务 replay 都不测）；
4. staging 语义弱（pending 是标志位，不隔离目录，活跃文件在审批前可被检索到的路径要看接线）；
5. 无提交对账（apply_improvement 写 manifest+落盘+registry 多步无原子性/回滚链）。

**判定/启发（P1 重头）**：不照抄全套（Neurova 单用户桌面体量撑不起 25k 行 evolution/），按"最小控制件"移植：
- **行为回归之 routing eval**：技能产物落盘前跑正反触发词 × 现有选择器（Neurova 关键词匹配已实现，正例须命中/负例须不命中，零 LLM）——直接防"造了个万能技能抢召回"；
- **证据包最小版**：improver/analyzer 输入加脱敏（正则替换 key/token/Authorization，Neurova 已有 `web_reach` 脱敏件可复用）+ 字符预算；
- **异步化**：进化提案从 post 链摘出来入 SQLite 队（Neurova 已有同类模式：notifications outbox），失败可重试不拖慢对话；
- **提交原子化**：apply_improvement 的多步写入包成"备份→写→校验→失败还原"单事务。

### 2.7 CAPTURED 反幻觉契约 ★★★

**OpenSpace**（新技能从哪来才可信）：三道闸——
1. **CaptureContract**（`types.py:230-260`）：提案必须声明 capability/preconditions/procedure_refs/validation_refs/limitations；
2. **确定性契约检查**（`capture_contract.py:67-137`）：procedure_refs 必须来自执行类证据（file_history/skill_event/tool_event/tool_result），validation_refs 必须来自观察类，**且两组不得同一 ref、不得同一 observation（tool_use_id）——"我做了 X"不能同时充当"X 被验证了"**；证据显示失败→拒；limitations 写"正确性未验证"这类免责声明→直接拒（不许用免责兜住没验证的主张）；
3. **独立语义复核**（`capture_semantic.py:246-266,434-444`）：schema 锁死的结构化评审工具，fail-closed；批准要求 validation_relation ∈ {oracle, independent_method, cross_implementation_comparison, readback}——**self_assertion 与重跑同一实现不算独立验证**。

**Neurova**：AutoSkillBuilder 封装 = 序列出现阈值+成功率达标→产模板（`skill_encapsulation.py:359`），无"后置条件被独立验证"概念；C10 靠人看。反思式文本进化改的是描述文本，不造新技能，不同风险。

**判定/启发（P1）**：给 AutoSkillBuilder 的 capture 路径加**最小契约检查**：封装产物的"该技能有效的证据"必须来自≥2 个不同 task 的成功观测（复用 §2.5 漏斗数据即得），且不得与"被封装的那次执行"同一 observation。纯计数即可落地，不引入 LLM 复核也能把"回声室"（09-05 肌肉记忆 P-C 同类病灶）焊死。

### 2.8 Tool RAG / lazy tools / 工具质量罚分 ★★

**OpenSpace**（grounding，33.9k 行）：
- 双轨：系统侧 `ToolPreselector`（预算 max_tools=20；deferred>50 才开 LLM filter；按 server 级分类 utility 精确定选 + domain_servers 宽松全纳）+ 模型侧 `tool_search` meta 工具（`is_deferred` 契约默认 MCP/GUI 全 defer；命中后**下一轮 turn 才注入 schema**；未加载工具被调用返回定向 hint，`pipeline/execution.py:712-782`）。
- 工具质量罚分喂排序：`score × penalty`，penalty 公式显式（`quality/types.py:83-116`）：<3 次调用免疫；rate≥0.4→1.0；否则 0.3+rate/0.4×0.7，连续失败≥3 追加≤0.3，钳位 [0.2,1.0]；滚动窗 100。
- 八段式工具管线（deferred 拦截→schema 校验→validate→归一化→pre-hooks→权限→执行→结果→post-hooks），deny/granted 均写证据。

**Neurova**：53 内置工具 + Skill + MCP 全量进 schema（orchestrator 同一处病灶）；`AdaptiveToolWeights` 已有滑动窗口权重+惰性衰减+持久化（Dify P0 落地，语义上已是 quality penalty 的近亲，**但小样本免疫与显式钳位是否等价需核对**）；无 deferred/lazy 机制；工具执行管线为 tool_executor 四段式（解析→执行→回写→经验），与八段式差距主要在 pre/post hooks 与权限前校验双相。

**判定/启发（P1-P2）**：与 §2.4 技能注入同病同源，宜合并为一个"工具面预算化"工程：技能/工具共用阶梯检索 + deferred 语义。quality penalty 先做**等价性核对**（Neurova 权重公式 vs OpenSpace 钳位公式），缺小样本免疫则补一条。

### 2.9 云 Hub / 上传门禁 / 分发边界 ★★

**OpenSpace**：
- 上传门禁 = **先本地查信任账本后触网**：`SKILL_TRUST_UNKNOWN/SKILL_RECORD_PATH_MISMATCH/SKILL_NOT_TRUSTED` 三硬码，provisional 拒传；信任状态不进 multipart（本机事实不外泄）；第二道门 = 密钥脱敏 fail-closed（`client.py:1549-1585`）。
- 血缘随技能走：上传带 origin_type/parent_cloud_ids/content_diff（仅 public 计算），derive/fix 的 parent 必须已有云绑定否则抛 `PARENT_CLOUD_BINDING_REQUIRED` 并给出政策选项（先传 parent / 转 imported）。
- **下载不静默导入**：云候选只附结果 + `cloud_action_required`；导入必须落本地目录树并注册；复用只认本地注册表。
- 包放置协议：路径 ≥3 段、一次只准新建一个子段、selection_ref 须来自最新一轮候选（防跨轮 UUID 过期）。
- 遥测白名单 5 事件 + 重试 outbox（先脱敏后落库）；技能质量上报默认关。

**Neurova**：marketplace（aliyun skillhub 源 + 站内提交/admin 人工审核）+ skillhub 联邦注册（link_market_skill_to_agent 双落）。审核是"人审闸"，无证据门、无密钥门、无血缘传递；zip/dir 本地安装**绕过注入扫描**（信任边界不一致，基线报告发现）。

**判定/启发（P2 + 顺带债）**：marketplace submit 加"trusted 才可提交"自动门禁（人工审核保留，二者叠加=人看质量、机器拦底）；**顺带修安装门 bypass**——这是 Neurova 自身存量 bug（doctrine 放大视角：统一 `scan_skill_for_install` 到所有注册入口），非纯借鉴项。

### 2.10 安全面总账

| 项 | OpenSpace | Neurova | 判定 |
|---|---|---|---|
| 技能文本安全扫描 | 7 条正则，**仅 1 条阻断**，4 入口+云检索全覆盖（`skill_utils.py:23-50`） | `skill_install_gate.scan_skill_for_install` fail-closed，但 **zip/dir 安装绕过** | 覆盖面学它，规则强度它反而不如 Neurova |
| bash 注入检测 | `$(`/反引号/`${`/heredoc/history-exp 等，命中→剥夺只读自动放行（`bash_injection.py:54-76`，"宁误报不漏报"+自曝无 AST 局限） | 工具治理预检链 | 可对照清单查漏 |
| 权限模型 | 工具级 deny>ask(三 bypass-immune)>allow>mode 六源规则 + headless fail-closed ask→deny（`permissions/engine.py:300-514,232-272`） | 技能级声明六类 fail-closed + `skill_permission_scope` ContextVar 仲裁 | **Neurova 技能声明维度更先进**；headless→deny 语义核对现状 |
| 沙箱 | bubblewrap/sandbox-exec 进程级，E2B 可选云；Windows 不支持 | file_operation 沙箱根 + 治理预检 | OpenSpace 无沙箱时 Windows 反而是盲区；Neurova 主战场在 Win，此项不追 |

### 2.11 Benchmark 方法论（含诚实 caveat）

**OpenSpace**：Terminal-Bench 20 题冻结集、frozen backbone（固定模型/迭代/工具白名单/关记忆）、cold=`skills_disabled` / warm=`--replay-from-run`。**但 warm 种子含 `_build_replay_feedback_skill`（`openspace_harbor_agent.py:1875-2024`）：把上次同任务 trial 的 verifier 输出、reward.txt、"Extracted Acceptance Targets"（鼓励照抄期望值）打包成技能注入**——这是"带答案的重放自进化"，13.5pt 提升不能当跨任务泛化收益引用。作者另设 `visible_test_context_enabled` 默认 False，说明知道边界，但 replay 分支绕开了它。

**Neurova**：Hermes 对齐的 `evolution/eval/` 七模块 + simulated 评测已有。启发：**做"技能库进化收益 A/B"时 seed 必须剥离 verifier 输出，只用"成功任务的工具序列"这类无答案证据**；且对照要像它一样固定 backbone。这条是避坑项，不是照抄项。

---

## 3. Neurova 差异资产清单（不回退项）

1. **进化闭环真实接线**（post_chat_pipeline 全链 + 反思式 GEPA 文本进化）——OpenSpace 的 analyzer 是判例员，Neurova 的 improver 会**反思式变异**，且带 benchmark GATE；OC 对比已确认此资产，本对比确认 OpenSpace 也未超越（它的 authoring 无 GEPA 式变异策略）。
2. **声明式技能权限六类 + ContextVar 作用域仲裁**——OpenSpace 权限在工具级，无"技能申报、执行期仲裁"模型。
3. **多用户/协作模型**（owner/visibility/share/push/admin）——OpenSpace cloud 有 private/public 但无 user-share 语义（它的用户模型更薄；注意其 API 面 pool 接线债见 §5）。
4. **工具基因引擎**（genetic engine）——OpenSpace 无对应。
5. **肌肉记忆/结晶/认知层**全栈——超出 OpenSpace 域，它没有记忆温度/情绪/巩固体系。
6. **AIGC/画布/渠道等宿主能力**——域外。

---

## 4. OpenSpace 自身弱点台账（借鉴时须避开）

1. `check_skill_safety` README 宣称强于实现（阻断仅 `ClawdAuthenticatorTool` 字面一条）；
2. benchmark warm 含 verifier 反馈技能（§2.11），归因存疑；
3. `upload_trust.py:126-128` 旧库无 trust 列默认投影 trusted——fail-closed 叙事的反例；
4. 云搜索 `effective_visibility` 缺省 public（缺元数据按最宽口径）；
5. embedding 缓存键无内容哈希（§2.4）；
6. Linux 沙箱域名过滤未完成（默认全断网，功能上"安全但不可用"）；
7. evolution 管线 ~25k 行、evidence 2.5k 行 store——**重量级**，Neurova 体量不可整体照搬；
8. MCP `execute_task` 阻塞式要求客户端 timeout≥600s；host gateway 仅飞书/WhatsApp 两通道。

---

## 5. 启发清单（按投入产出排序，全部为增量项）

> 验收纪律沿用修复教义：每项先写测试红→绿；契约错位类 bug 放大视角修到根因；不新建第二套平行体系。

### P0（直击存量弱点，低依赖）
| # | 项 | 最小可行方案 | 验收 |
|---|---|---|---|
| P0-1 | **技能质量漏斗** | SkillRecord/manifest 扩 4 计数（selected/applied/completed/fallback）+ 归因规则"兜底完成不计功"；采集点：orchestrator 选入、execute_skill_tool 命中、PostChat 收尾回写 | 计数单测 + 注入含兜底场景的回归用例 |
| P0-2 | **trust_state 两态**（provisional/trusted） | 新列 + 失败即刻降级 + ≥2 独立成功晋升（按 task_id 去重一票）；进化产物出生 provisional；与 stale 时间轴正交 | 状态机纯函数测试（对齐 skill_lifecycle 测试风格） |
| P0-3 | **注入目录接线** | `render_skill_catalog` 接为增量 delta + 1% 预算 + 描述压缩（参数照抄 §2.4，可配）；超预算别名压缩已实现，补常驻通道 | i18n 守卫测不破 + token 预算单测 + live 走查一轮 schema 数下降 |
| P0-4 | **安装门 bypass 收口** | `scan_skill_for_install` 统一到 SkillService.install_skill 与 /skill-pool/install-from-zip（Neurova 自身存量信任边界不一致，顺带） | 红用例：含注入模式的 zip 本地安装被拦 |

### P1（进化链控制件）
| # | 项 | 最小可行方案 | 验收 |
|---|---|---|---|
| P1-1 | **routing 行为回归** | 技能模板批准/进化提交前，正反触发词跑现有 `_skill_keywords_match_input`；静态即可、零 LLM | 造"万能技能"负例必须被拦 |
| P1-2 | **进化输入脱敏 + 预算** | improver/analyzer prompt 注入前过 key/token/Authorization 正则（复用 web_reach 脱敏件）+ 字符预算 | 含密钥会话样本 → 提案 prompt 无密钥 |
| P1-3 | **CAPTURED 独立证据** | AutoSkillBuilder：封装证据须 ≥2 个不同 task 成功观测，与被封装执行不同源 | 回声室场景回归 |
| P1-4 | **进化提案异步队列** | 提案出 post 链，入 SQLite trigger 表（claim/attempts/stale），drain 挂启动+空闲 | 队列崩溃恢复测试 |
| P1-5 | **apply_improvement 原子化** | 备份→写盘→registry→校验→失败还原；悬挂态对账 | 中途 kill 一致性测试 |
| P1-6 | **技能身份 sidecar** | `.skill_id` 语义进 manifest extra；版本/revisions 挂 parent 边（最小 DAG），替换 skill_version_api 假数据 | 现有版本测试对齐 |

### P2（分发与工具面）
| # | 项 | 最小可行方案 |
|---|---|---|
| P2-1 | 上传/提交证据门 | marketplace submit 须 trusted + 密钥脱敏 fail-closed；人审保留叠加 |
| P2-2 | 工具面预算化 | 阶梯检索（keyword→bge embedding→LLM 兜底）+ deferred/lazy；与 P0-3 同工程合并立项 |
| P2-3 | quality penalty 等价核对 | AdaptiveToolWeights 补小样本免疫/连续失败附加/钳位口径核对 |
| P2-4 | 技能库 cold/warm A/B | eval/ 扩展；seed 剥离 verifier（避 OpenSpace 坑） |
| P2-5 | 条件激活 paths | frontmatter paths→运行时按工作区激活（低频，观察） |

### 不借鉴（成文）
- 整体 25k 行 evolution/evidence 框架（体量不匹配）；
- bubblewrap/sandbox-exec 沙箱栈（Windows 主战场不适配）；
- cloud 包放置三步协议/agent-key bootstrap（Neurova 有自己的账号体系，无对应痛点）；
- bundled 技能豁免压缩等社区向细节（生态阶段未到）。

---

## 6. 与既往对比文档的关系

- 《OpenClaw 工具技能专项对比》"每轮全量注入是最大最便宜优化点"→ 本文 P0-3/P2-2 补上施工蓝图与参数；
- 《Dify 对比》"真实执行体仅 web-search"→ OpenSpace 的答案是**不预置执行体，用演化从真实使用中长出**（内置技能仅 1 个 `remember`）——印证生态供给靠闭环不靠仓库；
- 《Hermes 对比》评审闸/约束闸/benchmark GATE → 本文 P1-1/P1-3 把"闸"从人审下移到机器证据；
- 《肌肉记忆》P-C 回声室修复 → P1-3 的"独立证据"是该病灶在技能封装侧的根治延伸；
- 09-07 技能安装 404 / EKB 垃圾事故 → 共同教训：技能身份与写入门禁必须先于一切自动化（P0-4/P1-6 的动机）。

---

## 7. 落地终态（2026-09-15，未提交）

**146 个新用例全绿；受影响七目录回归 7458 passed。**

| 项 | 落点（文件:锚点） | 关键语义 |
|---|---|---|
| P0-1 质量漏斗 | turn_context（轮次账本）→ tool_executor.execute_skill_tool 咽喉 → post_chat 步骤 9.06 → SkillService manifest | selections/applications/completions/fallbacks + 派生率；兜底完成不计功 |
| P0-2 信任两态 | skill_service `compute_trust_transition`/`record_trust_observation`，identity.trust 寄居 | 失败即降 provisional、2 个独立任务观测晋升（session#turn 一票）；进化产物出生 provisional；usage 契约零触碰（lifecycle seed-on-first-sight 不破） |
| P0-3 目录接线 | skill_injection.render_skill_catalog 升级 + orchestrator `_skill_catalog_section` 单源双路径 | 250 字描述/30 行上限+未列提示/超预算别名压缩；`skill_catalog_enabled`（初版默认关→同日收口 SettingPage 默认开） |
| P0-4 安装门收口 | SkillService.install_skill 咽喉接 scan + `.incoming` 暂存原子交换 | 覆盖 zip/dir/pool 全本地路径；**顺带根治预存 bug：zip 解压目录与 target 同路径，rmtree 自删源——zip 安装此前从未成功** |
| P1-1 routing 回归 | skill_injection.routing_sanity_check + approve_template 接线 | 名述自洽/正例可召回/负例不抢召回，零 LLM；未过保持 pending 并回填 routing_issues |
| P1-2 进化输入脱敏 | 新模块 skills/evolution_inputs_guard + record_usage 写入侧 | 密钥形态脱敏+2000 字预算；下游（mutator/统计/审批面）全拿干净文本；**Bearer 序必须先于 KV 档否则漏网** |
| P1-3 独立证据 | ToolPattern.source_evidence + `_check_encapsulation` | ≥2 个不同来源成功才封装（防回声室）；无 source_key 存量调用逐观测独立（兼容零回退）；post_chat 喂 session#turn |
| P1-4 异步队列 | 新模块 evolution/job_queue（SQLite WAL/幂等入队/BEGIN IMMEDIATE 原子 claim/租约恢复/fail 阶梯） | `NEUROVA_EVOLUTION_QUEUE=1` 显式开启 post_chat 改道；启动 recover_stale 释放崩溃租约；**drain 单轮 exclusion 防自旋重试** |
| P1-5 原子化 | _save_manifest tmp+os.replace+fsync；update_auto_skill/apply/revert 落盘失败整体回滚 | manifest 截断清零隐患根治（providers 事故同型）；改进"内存新版盘上旧版"劈叉根治 |
| P1-6 身份版本 | manifest identity/version_history（线性修订 DAG @n/parent 边）+ skill_version_api 全端点换真源 | 假版本表/假成功端点清除；check/notifications 读 catalog+修订链；update 走 MarketImporter(force) |
| P2-1 提交证据门 | skill_install_gate.evaluate_submission_gate + marketplace submit | 注入扫描+密钥 fail-closed+本地同源 provisional 拒上架；admin 人审叠加 |
| P2-2 阶梯检索 | skill_injection.select_skills_for_turn + _build_tools_for_llm | ≤max 全量（现状）；>max 精确名必进+打分 top-k；零命中回退全量；`skill_schema_budget_enabled`（初版默认关→同日收口 SettingPage 默认开） |
| P2-3 小样本免疫 | closed_loop._windowed_success_rate | <3 观测 rate 不罚（乘数方向保留，阈值齿轮不失明）；≥3 全语义生效 |
| P2-4 cold/warm A/B | 新模块 evolution/eval/ab_library | 双臂 harness；verifier 只进评分面；warm 种子白名单+SeedLeakError（OpenSpace 泄漏坑的反面纪律） |
| P2-5 paths 激活 | skill_injection.match_skill_paths（目录/工具面共同过滤） | config.paths glob 设定即条件激活；未设定零变化；空输入不滤（保 system 字节稳定）；$mention 显式调用绕门 |

**开关收口（2026-09-15 用户拍板：默认全开 + SettingPage 高级选项卡）**：
- 三开关落 `data/app_settings.json` advanced 段（`skill_catalog_enabled` / `skill_schema_budget_enabled` / `evolution_queue_enabled`，默认 True；desktop_provider 同族后端热读）；SettingPage 高级选项卡新增「技能召回与进化」卡（三开关+中文说明，i18n 11 语 8 键）；
- 三态优先级：agent 显式配置（AgentConfig 默认 None=跟随全局）> 全局设置 > 内置默认；`NEUROVA_EVOLUTION_QUEUE` env 显式值最优先（运维逃生门）；
- 回归：默认开全量重跑 context/agent/core/skills/evolution/api **6662 passed**；期间根治一处落地自伤——`_build_tools_for_llm` 曾调 `self._resolve_recall_flag`，存量 `MagicMock(spec=[])` 替身契约下 AttributeError 被吞致技能段整体跳过（G2 测试抓到），改内联解析修复。

**预存失败台账（已证与本落地无关）**：
1. `tests/unit/context/test_tools_prompt_and_schema.py::test_empty_tools_returns_empty_description` —— 工作区在途 AIGC 的 `workflow:template_short_drama` 泄漏进工具面（纯净 stash 仍失败）；
2. `tests/unit/api/test_model_capability_endpoints.py::test_legacy_classname_strings_normalized` —— 他会话 llm/ 在途改动的中间态（本次运行已转绿）。

**开关默认态沿革**：初版三开关默认关（增量保守）；同日用户拍板**默认全开**并收口 SettingPage 高级选项卡（「技能召回与进化」卡，见上节）。paths/trust/漏斗/脱敏为无开关加法键（现有消费面不受影响）。

### 7.1 Wave E 补录（同日：召回闭环 + A/B 真接线，+23 测绿）

侦查更正：**工具面预算化/延迟加载其实早已存在**——A6 `neurova/context/tool_search.py`（BM25 目录+`tool_search/tool_describe/tool_call` 三控制工具，候选>40 激活，orchestrator 已接线），§1 原行判定过时。Wave E 落地：

- **语义检索档**：新模块 `skills/skill_semantics.py`（bge ONNX 经 `get_embedding_engine`，向量缓存**内容哈希为键**（反面教训=OpenSpace 缓存坑）、零向量不入库、引擎缺失静默降级关键词档）；`select_skills_for_turn` 融合 keyword+cosine（floor 0.15，弱语义不加分）；预算内语义只排序不淘汰（宁全不缺）；
- **trust/质量召回熔断**：`quality_blocked` 单源判据（applications≥2 且（零完成或 fallback>0.5）→ 本轮不进工具面，**不受预算开关约束**——它是安全闸）；目录对 provisional 软标注 `(provisional)`；
- **turn 级 skills_off**（`turn_context`）+ `make_agent_ab_executor`：cold 臂 schema+目录同源缺席，`run_cold_warm_ab` 可直挂真 Agent——P2-4 的 replay 接线闭环；
- **开关面收口 SettingPage**：`tool_search_enabled`、`skill_semantic_recall_enabled` 两新键（卡内共五开关，默认全 True；env `NEUROVA_TOOL_SEARCH` 显式值仍最优先）。i18n 共 12 新键×11 语。

回归：skills/evolution/context/security 3219 + core 1785（排除并行会话在途 sleep 中间态三文件）全绿；前端 62+vue-tsc 净。

### 7.2 未偿清单（登记，非本轮范围）

| 项 | 定性 | 说明 |
|---|---|---|
| 三套技能模型归一（Skill/SkillInfo/SkillMetadata + pool 双轨） | 核心重构 | 触面=注册表/兼容层/API 全链，"不动核心框架"约束下宜单独立项、契约测试先行 |
| DiscoverSkills 独立元数据工具 | 可选增强 | 现由目录+$mention+阶梯承担发现职能，缺口不致命 |
| replay 种子自动采集器 | 半接线 | `build_seed_from_successful_run` 白名单已就绪，缺"历史成功 run → 种子集"的持久化约定 |
| embedding 档生产实测 | 待办 | 单测以替身引擎验证；真机首轮向量化待一次 live 走查 |
| pool/API 双轨用户模型分裂（越权面） | 存量债 | 基线巡检发现（skill_pool_api 鉴权缺位），不属 OpenSpace 十项，另案处理 |
