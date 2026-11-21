# Neurova 递归自演化实施详案

> 状态：备稿（待评审拍板，未实施）
> 日期：2026-11-21
> 定位：把仓内既有的五臂演化机制收口为统一、安全、可递归的自演化体系，并让空转机制第一次真正跑通。
> 性质：方案文档。实施时按修复教义逐卡先红后绿；本文不作为事实源引用代码行为，动手前以现场代码为准。

---

## 0. 摘要

Neurova 已有**五臂**各自成形的演化机制（参数级 RSI、文本/技能进化、工具与技能闭环、提案生命周期、行为规则自改进 dreaming），且纪律件成熟（三态判据、渐进部署、回滚管理、全自动前置探针、case-first 评测纪律）。

**第二轮代码级调研（2026-11-21，含 data/ 运行痕迹实证）的核心结论**：多数机制**从未真正咬合**——RSI 1018 次迭代 0 次应用（相位 4 顶格、参数族候选枯竭、回滚持久化默认关）、EvalCase 器械完整但生产零立案、multi_agent 评测无跑批入口且从未落盘。**缺的不只是收口，首先是"跑通"**。

因此第一期分两步：**R 批（修补）**让已建成机制第一次跑通完整闭环；**P 批（优化/治理）**补齐统一对象注册表、跨臂世代账本、应用级存活门禁、门禁链编排、影子验证、L2 生效通道与元层策略。第一优先级是**安全地基**：禁改内核注册表 + 存活探针，确保任何一代演化都不可能把系统改到"agent 跑不起来"。

**总体纲要：进化全程自动进行，跑不通自动回滚**（§2.0）——自动化按对象分级解锁、自动权限按证据逐级挣取；回滚永远全自动；人工仅保留裁判件变更、禁改清单变更、相位未达标的高危 L2 放行三处。

---

## 1. 代码现状盘点（事实基础）

### 1.1 演化机制全景（五臂）

**臂一：参数级 RSI（`neurova/evolution/rsi/`，30 文件 8919 行，已接线）**

- `RSIOrchestrator`（orchestrator.py:201，工厂 `create_rsi_orchestrator`:2078）：主循环 `run_iteration()`(:938) = 收集四系统反馈信号 → 收敛分析 → 逐参数生成候选（步进 0.05/0.10/0.15/0.20）→ 棘轮三段剪枝 → 负债反向闸 → （phase≥2）快照→应用→前后双测→增益/配对CI/例级回归→回滚判定→密封档验收→资源记账→阶段晋升评估。
- 消费方（生产接线确认）：`agent_core.py:1470`（构造注入）、`post_chat_pipeline.py:3586-3595`（后台驱动迭代）、`evolution/closed_loop.py:672`、`api/endpoints/governance.py`（status/提案审批/换版批准端点）。
- `RSIIntegrationManager`（integration_manager.py:26）：参数宿主，`OPTIMIZABLE_PARAMETERS` 5 族 11 参数，`apply_optimization`(:311) 带边界夹紧 + 回执落盘（写失败即撤销）。

**臂二：文本/技能演化评测管线（`neurova/evolution/eval/`，25 模块）**

- `eval/runner.py`：变异 → 打分 → 约束闸 → **留出集对比** → 部署/拒绝。明文纪律：留出集是判据、benchmark 是 GATE 不是 fitness、不达标保留基线（deployed_text 永远是已过闸最优）。
- 配套：`bench_gate`（benchmark 门）、`blind_selection`（盲选）、`calibration`（噪声带）、`leak_critic`（泄漏批评）、`constraints`（尺寸/增长/语义保持）、`failure_analysis`、`history_ledger`。
- 现状：`config/evolution_settings.json` 中 `text_evolution: true`（文本进化主开关已开，仅影响 eval/factory 装配、service.evolve、post_chat 的 LLM 文本进化段三处）；`auto_apply_skill_evolution` 默认关（产物先 pending 待审）。
- **完整链路（第二轮调研逐跳实证）**：post_chat 触发 → `skill_improver.propose_pending_improvements_async` 字典提案（只写 revisions 快照不改正文）→ `text_evolution_enabled()` 门 → `service.build_dataset`（golden/挖掘/合成三级回退）→ `service.evolve`(service.py:781)：heldout 切分 → 执行器装配单点 `resolveEvolutionExecutor`（真臂预算闸 `checkRealArmBudget`，超帽回落 SimulatedAgent 并留痕）→ `factory.make_skill_evolution_runner`（LLMJudge+ConstraintValidator+LeakCritic+bench_gate+ledger）→ `runner.run`（runner.py:978：核选 coreset → judge 可用性探针 → 迭代循环【变异→约束闸→泄漏闸→评测→台账】→ 八道判定门：holdout 回归/coreset 复核/无改进/例级回归/执行套件回归/锚定地板/成本规则/成本硬门/**bench 回归门**）→ 过门产 `deployed_text` → pending 提案 + 工件落盘。
- **部署落点（唯一变更点）**：`service.decide`(service.py:1387) → `_apply_to_skill`(:1552) 把 `improved_text` 写入 `<agent_skills_dir>/manifest.json` 的 `manifest.config.context_template`（运行时经 skill 目录注入、$mention 全文、SkillDocSkill 执行三处读取）→ `update_auto_skill` 四道质量门 + `_reenter_review_gate` 再评审（进化审批与技能生效审批是串联双闸）→ journal.git commit + 工件转 applied。批准前基线被改过 → `baseline_changed` 拒绝。
- **诚实边界**：`bench_gate` 对纯文本候选恒中性（无 apply_fn → `neutral_reason="no_apply_fn"`，绝不假称测过）；`leak_critic` 评测前拦截背题候选；`blind_selection` 仅 near-tie 时作盲选证据不参与判定；judge 回退/成本软门提案即使 auto_apply 开着也强制人工。

**臂三：工具与技能闭环（`evolution/closed_loop.py` + `evolution/skill_*` 九件套）**

- 工具权重自适应、工具生命周期（含肌肉记忆降级）、基因引擎、经验反哺；`tool_executor.py` 已真实消费 `touch(name, success)`，`context/orchestrator.py:1237` 消费 `on_before_tool_selection`（过滤 archived/frozen、按权重排序、degraded ×0.7）。
- **技能进化九件套（第二轮调研确认全部活接线）**：`skill_recording`（POST_EXECUTE 事件接四本账）→ `skill_evidence`（成败全量轨迹，败 100/成 20 留存 + 证据包）→ `skill_improver`（失败模式分析→改进提案→apply/revert，落 config.revisions）+ `skill_experience`（经验库：待审队列/重建/淘汰）+ `skill_attribution`（MetaLedger 教训→工具技能倒排→置信度≥0.7 归因，全确定性）→ `skill_consolidator`（umbrella/结构/语义三计划源 + fail-closed 自动 commit 预检）+ `skill_lifecycle`（active→stale→archived 纯时间戳状态机）+ `skill_encapsulation`（AutoSkillBuilder 模式→技能模板，min_occurrences=3+成功率≥0.7+独立源≥3）+ `skill_review_gate`（三臂产物默认待审，env 默认开）。
- **遗传引擎**（genetic_engine.py:96）：模式序列→基因型种群（精英保留+交叉 0.7+变异 0.3）→ fitness≥0.8 注册为技能；**种群不持久化**（重启归零，靠下轮 pattern_mining 重播种）——登记为缺口。
- **统一成败取票口**：`objective_evidence.resolve_ticket_evidence`(:134)——服务端票据（creation_evidence.sequence_results）覆盖一切自述，失败粘性；查无票据降为旁路（unevidenced），查不了报 unreadable，绝不静默。结晶/经验反哺/EKB 三方共用。

**臂四：提案生命周期（`evolution/proposal_lifecycle.py` + `rsi/self_improvement_proposer.py`）**

- `ProposalStatus` 状态机（PENDING → APPLIED → 可选 ROLLED_BACK；PENDING → REJECTED），两臂（文本进化/RSI）已收口为单一事实源。
- `SelfImprovementProposer`（self_improvement_proposer.py:342）：
  - 提案类型：`SKILL_MANIFEST` / `ACTION_DEFINITION` / **`PR_PATCH`**（propose_pr_patch:508，unified diff，默认高风险）；
  - 沙箱校验 `validate_proposal`(:540)：路径穿越（禁 `..`/绝对路径）、系统文件前缀黑名单（_FORBIDDEN_TARGET_PREFIXES:183）、PR patch 目标白名单（仅 `neurova/ tests/ NeurUI/ scripts/ config/`）、危险模式检测、命名规范；
  - 人工审批 `approve_and_apply`(:669)：双 gate（人类评审主 gate + 部署阶段 gate：low 任意相位 / medium 需 phase≥3 / high 需 phase≥4）→ 应用前快照（rollback_manager.create_snapshot）→ 激活 → APPLIED；
  - **关键缺口**：`_plan_activation`(:965) 目前**只放行 SKILL_MANIFEST**，PR_PATCH 等类型返回 `not_supported`（"批准它只会留下一次文件写入；不如实说「不生效」就不算批准"）——即 **L2 代码级提案有"提案-校验-审批-快照"骨架，但没有生效通道**。
  - 两臂提案**持久化分叉未收口**（第二轮调研确认）：文本臂 `proposals.json`（单文件数组、tmp+replace 原子写、有界 50）vs RSI 臂 `proposals/<id>.json`（逐文件、**非原子 write_text**、无界增长）；API 面分居 `text_evolution_api` 与 `governance`——`proposal_lifecycle` 只统一了状态机语义，存储与路由仍两套。

**臂五：行为规则自改进（`cognitive_layers/dreaming.py`，默认开）**

- 夜间 clue→candidate→active 三层：自主行为与其后反馈是"线索"，同 kind 累计到门槛合并为候选规则（用户显式点名单次即候选）；`dreamSweep` 夜间把候选升格 active；判定面只读 active 规则、读不到 clue（判定不建立在未证实的单次观察上）。
- 转正闸复用 `memory_admission.screenMemoryContent`（敏感模式族 fail-closed，候选留置等人工处置）；SQLite 落 `data/dreaming_rules.db`（WAL+版本化迁移）；`NEUROVA_DREAMING` 默认开。
- 这是此前未登记的第五条演化臂：**演化对象是行为规则**（proactive/审批提示/回复策略），与参数/文本/技能/代码四臂互补。

### 1.2 已有纪律件（直接复用，不重造）

| 件 | 位置 | 语义 |
|---|---|---|
| `GateVerdict` 三态 | rsi/gate_verdict.py:31 | passed / failed / **unevidenced**；`__bool__` 仅 passed 为真——"没证据"永不冒充"通过"。全仓晋升判据共享词汇 |
| 渐进部署 5 相位 | rsi/deployment_controller.py:17 | PHASE_0 观察 → PHASE_4 全自动；风险→最低自动档 low:2/medium:3/high:4；`evaluate_phase_transition` 三态判据（§8 四前置硬否决） |
| 全自动前置探针 | rsi/automation_prerequisites.py | 四条"无人监督全自动"前置，各带可红探针（假旗标会说谎，探针不会） |
| 回滚管理器 | rsi/rollback_manager.py:41 | `create_snapshot` / `should_rollback`（发散/ROI<0/CI 上界<0/例级回归）/ `execute_rollback` / `days_since_last_rollback`（晋升判据唯一真源） |
| 改进器版本台账 | rsi/candidate_policy.py:288 | I_0 冻结基线逐值复刻；ImproverVersionLedger 版本登记（同号异摘要拒、无 measured 探针拒入账） |
| 负债账本 | rsi/debt_ledger.py | 候选寻优的负债语义唯一事实源；余额>0 不放行 |
| 评测判据集 | rsi/eval_harness.py | 决策档 6 例 + 密封档 3 例（9 例×4 族），全回退 setpoint 时报 measurement_blind |
| 审计预定表 | rsi/audit_schedule.py | 防选点污染的时点封存 |
| 任务流/标尺 | rsi/task_stream.py、task_yardstick.py | 与挖掘源不相交的固定任务流、重放对齐分 |
| 提案状态机 | evolution/proposal_lifecycle.py | 两臂统一转移合法性（仅 PENDING 可决定；仅 APPLIED 可回滚） |
| 检查点服务 | checkpoints/service.py | git 裸仓库后端（每 agent 一库，plumbing 不 checkout）；`snapshot` / `restore_with_rollback`(:208，事务化+pre-restore 留档) / `diff_snapshots`；scope 化 API `captureScope`/`rollbackScope`(:347/:399，带 isolation_check) **齐备但当前无生产写入方（仅测试）——本详案接上写入链** |
| 候选 CAS 合并板 | agent/candidate_merge.py:105 | `CandidateMergeBoard.mergeCandidate`(:182) CAS 合入，冲突双保留升级人工；swarm 成员结果回传已走此链 |
| swarm 审批链 | agent/approval_chain.py:44 | L0 自动留痕 / L1 交互或 auto / **L2 强制人工**；grant 记忆式放行永不覆盖 L2；`decideSwarmApproval`(:833) 三入口单源+租户校验 |
| 客观证据取票口 | evolution/objective_evidence.py:134 | 服务端票据覆盖自述、失败粘性、三态（evidenced/absent/unreadable）——结晶/经验反哺/EKB 的统一成败来源 |
| 进化作业队列 | evolution/job_queue.py:90 | SQLite WAL + 幂等键 + 租约 + 重试；默认接管 post_chat 进化步（2026-09-15 拍板翻转默认） |
| 持久化底盘 | evolution/persistence.py:23 | PersistedStateMixin（10s 节流 + tmp/replace 原子写 + 损坏回退空态）；`bootstrap_evolution_persistence`(closed_loop.py:817) 统一挂载六件 + 关停 flush |
| suite_eval case 纪律 | benchmark/suite_eval.py | `EvalCase`（subject_id + source 强制登记）、`validateCaseFirst`(:208，改动面必须被已注册 case 覆盖)、`assertCaseRedGreen`(:231，旧 FAIL 新 PASS)；**器械完整但全仓生产零立案、零调用（见 §1.4）** |
| 文本进化评测件 | evolution/eval/ | bench_gate 三态诚实门（neutral_reason 如实标注）、leak_critic（评测前拦背题）、blind_selection（near-tie 盲选证据）、calibration 噪声带、constraints 尺寸/增长/语义 |
| 元认知信号件 | cognitive_layers/meta_cognition_layer/ | `growth_log`（ReflectionLogEntry 六型五态生命周期，借道 MemoryManager 落盘，注入即 mark applied）；`self_model` 五确定性算子产 lesson 落 MetaLedger（SQLite）；`ledger.tool_success_rates` 已被 fold_trigger 消费 |

### 1.3 观测与治理面

- `RSIOrchestrator.get_status()`(:1844) 是全包读数总线，30 键出街（收敛/相位/负债/评测结果/密封证据/配对探针/成本向量/代理参考相关/覆盖/迁移/质量曲线/审计/参数活性/升级/经验通道/呈现漏斗/能力缺口/元奖励守卫等）；治理端点 `GET /v1/governance/rsi/status` 是唯一生产读口。
- 治理端点全景（governance.py，1283 行，挂 `/v1/governance`，均 admin 门）：白名单、HITL 审批流（pending/approve/reject + 指纹复核）、指挥资格台账、技能回滚面、运行限制（agent-limits）、执行档位（exec-profiles）、任务档位、评测核选（eval-coreset）、实验开关（eval-experiments）、检索配方、工具溢出阈值、治理设置本体、LLM 重试、桌面审计、profile 附身授权、RSI 面（status/提案/换版批准）。
- `security/governance_settings.py`：单 JSON（data/governance_settings.json）键集全景——`rsi_phase`（当前实测=4 顶格）+ `rsi_phase_overrides`（agent 级覆写，`resolveRsiPhaseFor` 单源）、`metacog_gate_enabled`（当前 false）、`crystallization_llm_gate_enabled`（当前 true）、`skill_auto_retire_enabled`、`approval_continuation_enabled`、`guarded_syntax_gate_enabled` 等 17 键；优先级口径单源 `resolve_flag/resolve_seconds`（env > 治理设置 > 默认）。**演化开关的现成挂点就在这里**。

### 1.4 运行数据实证（2026-11-21 实测 data/ 痕迹）★本节是第一期定位的核心依据

| 回路 | 实测数据 | 判定 |
|---|---|---|
| RSI 参数优化 | `rsi_summaries.jsonl` 共 **1018 条**迭代记录：`applied_count>0` 的 **0 条**；113 条 insufficient_data，gain 全 0/None，measure_state=not_attempted；`rsi_phase=4` 顶格（"已处于最高阶段 4，不再晋升"），参数族全部 no_candidate/placeholder_host；`rsi_rollback.json` history **0 条**且其持久化**默认关**（env `NEUROVA_EVOLUTION_ROLLBACK` 未设即零 IO——晋升判据"距上次回滚天数"的数据源在生产默认不产出） | **空转**：机制完整但从未应用过一次优化 |
| 工具权重/生命周期 | tool_weights 真实计数（如 web_fetch 32 成功/3 失败）；生命周期 16 active/8 degraded/4 archived；模式序列 41 条 | **真活** |
| 技能/经验臂 | skill_experiences 8 条、skill_improvements 5 条、experience_feedback 2 条 | 轻度运行 |
| 结晶/反思/质量/dreaming | crystallizer_state、metacognition.db(143KB)、conversation_quality.db(417KB)、dreaming_rules.db 均有实文件 | 真活 |
| EvalCase case-first | 器械完整，**全仓生产零注册、`validateCaseFirst` 零调用**（仅测试自检 ~30 处） | **空转** |
| multi_agent 评测 | harness 完整（solo/swarm 双模式+报告原子落盘），但 `runAllWithReport` **生产零调用**（跑批无 API 入口），`data/benchmark/` 目录不存在 | **空转** |
| metacog V3 调控门 | 基础设施在位（tool_executor.py:844 读活跃 avoid_tool 教训），`metacog_gate_enabled=false` | 待启用 |
| benchmark 单跑 | `_RUNS_STORE` 进程内 dict，重启即失 | 断点 |

**结论**：与 2026-11-18 四域审计"机制先行、消费滞后"一致且更具体——**不是缺机制，而是多数机制从未真正咬合**。第一期的主线因此修正为：**让已建成的机制第一次跑通完整闭环（RSI 出现第一个被应用的优化、EvalCase 出现第一批生产立案、multi_agent 出现第一份基线报告），同时把五臂收口到统一治理框架**。

### 1.5 测试面（回归底盘雄厚）

- `tests/unit/evolution/` 约 113 文件（闭环接线/工具权重/技能治理/提案部署/单源纪律/回归修补六簇）；
- `tests/unit/evolution/rsi/` 42 文件（几乎每文件对应一张审计工单判据：三态判据/相位覆写/审计选点/自动化前置/密封档隔离/ROI 真值/回滚证据/经验质量/双增益/跨轮回放闸/参数单源）；
- `tests/unit/evolution/eval/` 59 文件（判据闸/证据链/成本）；`tests/unit/evolution/experience/` 22 文件（结晶/肌肉记忆/三态成败）；
- `tests/unit/api/test_rsi_approval_endpoints.py`（提案审批三连 + 相位自动评估接线）、`test_governance_settings.py`（回滚天数真值/设置持久化/422）。
- **含义**：一期改动有厚回归网；A/B 自证以"零新增失败"为门槛完全可行。

### 1.6 待接线点与闲置件

待接线（实现完整、缺生产消费方）：

- `rsi/strategy_comparison.py`（compareStrategies）、`rsi/deployment_amortization.py`（deploymentAmortization）——策略对比/成本摊销读数现成；
- `PR_PATCH` 提案类型——校验/审批/快照骨架齐备，唯缺生效通道；
- suite_eval EvalCase / multi_agent 评测 / metacog V3 门——见 §1.4 空转三项。

闲置（零生产调用方，登记处置而非急删）：

- `EvolutionFacade` 的单例对 `get/reset_evolution_facade` 与 `select_tools/add_tool_sequence/synthesize_tools` 方法、`EvolutionResult`（实际只有 3 个方法被 3 处临时构造使用）；
- `GeneticConfig`（genetic_engine.py:85，死数据类）；
- `NLToolSynthesizer`（每 agent 实例化但主链未调用，facade 走 PatternBasedToolSynthesizer）；
- `soul.json` 结构化配置无消费方（soul 实际走 soul.md 文本）。

### 1.7 关键缺口（第一期要补的事，按三类重组）

**A 类·让已建成的机制第一次真正咬合（本轮调研实证的最高优先级）**：

1. **RSI 闭环咬合**：1018 次迭代 0 次应用的根因链 = 参数族候选枯竭（no_candidate/placeholder_host）+ 测量面未跑（measure_state=not_attempted）+ 回滚持久化默认关。需要：扩展可演化参数面/信号面让候选重新产生、接通测量前置、激活 `NEUROVA_EVOLUTION_ROLLBACK` 持久化（否则晋升判据"距上次回滚天数"永远 unevidenced）。
2. **EvalCase 纪律落地**：器械完整但零生产立案——首批 case 立案 + 把 `validateCaseFirst` 接进"模型可见文本改动流程"（AGENTS.md §4 测试纪律的机制化）。
3. **multi_agent 评测跑批入口**：补生产触发 API（现只有只读报告端点），产出第一份基线报告落 `data/benchmark/`。
4. **metacog V3 调控门启用评估**：基础设施在位（教训拦截工具执行），默认关——是否启用、灰度范围待拍板。
5. **RSI 相位与证据脱节**：`rsi_phase=4` 顶格（全自动档），但实测 0 应用/0 回滚/测量未跑——信任未挣得、权限已拉满；且回滚持久化默认关，判据数据源未开。需要：相位回调 + 晋升判据补"实做次数"门槛 + 回滚持久化参数化常开（→ R5/R6）。

**B 类·统一治理框架（原"六件事"）**：

5. **TargetRegistry**：可演化对象无统一注册表；禁改内核仅以零散黑名单（_FORBIDDEN_TARGET_PREFIXES）与 PR patch 目录白名单存在，无"对象→作用域→判据→门禁级别"的单一事实源。
6. **GenerationLedger**：五臂各有持久化，但无跨臂世代谱系——"第 N 代由第 N-1 代哪些变更组成"不可整体追溯。
7. **SurvivalProbe**：无应用级存活门禁。现有判据全是"参数/文本效果级"，没有"改完之后系统还能不能起来"的硬闸。
8. **GateChain**：G0-G4 分层门禁未统一编排；RSI 晋升判据、文本进化八道门、提案部署 gate 是三套并行语义。
9. **ShadowVerify**：无标准化影子验证环境（隔离数据根 + 完整启动 + 判据套件）。eval 管线有留出集对比，但没有"整应用冒烟"这一层。
10. **L2 生效通道 + 外部执行体**：PR_PATCH 无生效通道；neuacp 外部编码 agent 未接入为候选生成器。

**C 类·收口与清理**：

11. **两臂提案持久化收口**：文本臂（数组/原子写/有界）vs RSI 臂（逐文件/**非原子写**/无界）——存储与 API 路由统一到单一事实源；
12. **遗传引擎种群持久化**：现重启归零靠 pattern_mining 重播种——入 bootstrap 六件或明确豁免并记录；
13. **闲置件处置**：EvolutionFacade 单例对与三个闲置方法、EvolutionResult、GeneticConfig、NLToolSynthesizer、soul.json——按教义第 5/6 条逐一判定（接线或退役），不静默遗留。

相邻事实登记：`error_logs` 当前为空（本部署无错误上报记录），失败信号主通道以 agent_run_ledger 为准；benchmark 单跑结果仅存进程内 dict（`api/endpoints/benchmark.py:90`），落盘列为 P1 前置小卡。

---

## 2. 总体设计

### 2.0 总体纲要：进化全程自动进行，跑不通自动回滚

**北极星：演化全程无人值守自动进行——信号立案 → 候选生成 → 影子验证 → 门禁裁决 → 晋升部署 → 运行观测；任一环"跑不通"都自动处置（影子失败→候选自动淘汰、门禁不过→世代自动拒绝、部署后异常→自动回滚上一好代），不等待人工救援。**

落地口径（与既有安全设计的咬合，避免"自动"被误读为"越权"）：

- **自动化的主体是循环，不是边界**：自动执行严格发生在 TargetRegistry 登记的对象与 GateChain 判据之内；裁判件、禁改内核、held-out 划分不在自动化范围（原则 3 不变）。
- **分级解锁，自动权限是挣来的**：L1 参数/文本/技能对象在相位达标后全程自动；L2 代码级候选 phase≥4 后自动、未达标走人工审批；相位由实做次数+判据逐级晋升（R6），不是配置拍板。
- **回滚永远全自动**：回滚是恢复安全态，不允许排队等人——影子失败自动淘汰（不落基线，无需回滚）；部署后健康越界由 `rollback_manager.should_rollback` 自动判据 + CheckpointService 恢复自动执行并留痕。
- **人工保留点收敛为三处**：裁判件/禁改清单变更、L2 高危候选在相位未达标时的放行、相位的初始信任设定。其余环节全部自动。

### 2.1 三原则（不可妥协）

1. **内核先于演化**：可演化集合由 TargetRegistry 显式圈定；核心运行时从一开始就是 `forbidden`，"agent 跑不起来"这一事故类别从结构上排除。
2. **候选永不直改基线**：一切变更先成为 Generation 候选，在影子环境过门禁链；生产基线只接受全绿世代的晋升。
3. **裁判在演化集合之外**：TargetRegistry 自身、SurvivalProbe 判据、GateChain 阈值、held-out 划分，一律 `forbidden`——自动演化碰不到评分标准与准入规则。

### 2.2 架构总图

```
                ┌─────────────────────────────────────────────┐
                │              SignalBus 信号层                 │
                │ 教训台账 · eval 失败 · 用户反馈 · 守卫发现 · 金丝雀观测 │
                └──────────────────┬──────────────────────────┘
                                   ▼
┌──────────────┐   ┌─────────────────────────────────┐   ┌──────────────┐
│TargetRegistry │◄─►│  GenerationOrchestrator 世代编排器   │◄─►│EvolutionPolicy│
│ (含禁改内核)   │   │ 提案→影子验证→门禁链→裁决→金丝雀→晋升  │   │ (L3 元层参数)  │
└──────────────┘   └───────┬──────────────┬──────────┘   └──────────────┘
                           ▼              ▼
                ┌──────────────────┐  ┌──────────────────────┐
                │ ShadowVerify      │  │ 候选生成器（三来源）      │
                │ 隔离数据根+完整启动  │  │ L1: RSIOrchestrator    │
                │ G0存活→G1契约→G2业务│  │     (参数候选，已有)     │
                │ →G3回归→G4教义     │  │ L1.5: evolution/eval   │
                └────────┬─────────┘  │     (文本/技能，已有)    │
                         ▼ 全绿        │ L2: neuacp 编码 agent   │
                ┌──────────────────┐  │     (PR_PATCH，新增通道) │
                │ Canary 金丝雀      │  └──────────────────────┘
                │ 影子流量对比       │
                └────────┬─────────┘   ┌─────────────────────┐
                         ▼ 晋升         │ Rollback 回滚         │
                ┌──────────────────┐   │ CheckpointService    │
                │ 生产基线 = 第 N+1 代│──►│ + RSIRollbackManager │
                └──────────────────┘   └─────────────────────┘
```

### 2.3 世代模型（时间递归的载体）

```python
@dataclass
class EvolutionGeneration:
    generationNo: int                 # 世代序号（谱系主键）
    parentNo: Optional[int]           # 父代 = 回滚目标
    basisCommit: str                  # 基线 commit（可复现冻结）
    createdAt: str
    signals: list[SignalRef]          # 为什么改（教训/评测失败/反馈/守卫）
    changes: list[ChangeRef]          # 改了什么（targetId + patchRef/paramRef + rationale）
    verdicts: dict[str, GateVerdict]  # g0..g4 各门禁三态结论
    decision: DecisionRef             # auto / approval(approver) / rejected(reason)
    deployment: DeploymentRef         # canary 观测窗口结论 / promotedAt / rolledBackTo
    status: str                       # proposed→shadowTesting→gated→canary→deployed
                                      #              ↘ rejected / rolledBack（终态留档）
```

世代账本落盘持久化（沿 `result_summary`/`ImproverVersionLedger` 的 env 开关范式：`NEUROVA_EVOLUTION_GENERATIONS`，未配置不做 IO，避免测试状态污染）。**每代部署前经 CheckpointService 打应用级快照**；上一好代永远可指认、可恢复。

---

## 3. 核心新建件设计（全部落 `neurova/evolution/rsi/`）

### 3.1 target_registry.py —— 演化对象注册表（单一事实源）

```python
@dataclass(frozen=True)
class EvolutionTarget:
    targetId: str                    # 稳定 ID，如 "prompt.chatSystem"
    layer: str                       # "L1" 配置态 / "L2" 代码态 / "L3" 元层
    kind: str                        # promptTemplate|agentDef|toolWeight|skillCard|module|policyParam
    locator: str                     # 物理定位（路径/参数路径/技能ID）
    scope: str                       # "global" | "tenant" | "agent" —— 作用域（见 §10）
    gateLevel: str                   # "auto" | "approval" | "forbidden"
    survivalCritical: bool           # 是否计入 G0 判据面
    fallbackRef: Optional[str]       # 降级兜底（L1 必填：默认值出处）
    verdictSuite: str                # 绑定的判据套件名（如 "rsi.eval.decision" / "suite_eval.chat"）

class EvolutionTargetRegistry:
    def register(target: EvolutionTarget) -> None: ...
    def get(targetId: str) -> EvolutionTarget: ...
    def listByLayer(layer: str) -> list[EvolutionTarget]: ...
    def assertMutable(targetId: str) -> None: ...   # forbidden 即抛错（fail-closed）
    def forbiddenTargets() -> list[EvolutionTarget]: ...  # 供守卫测试逐条钉死
```

- **禁改内核首批清单**（`forbidden`，守卫测试逐条断言存在且 forbidden）：`neurova/agent_core.py`、`neurova/tool_executor.py`、`neurova/llm_client.py`、`neurova/context_pool.py`、`neurova/core/identity_context.py`、`neurova/core/db_migration.py`、`neurova/evolution/rsi/target_registry.py`（自身）、`neurova/evolution/rsi/survival_probe.py`（自身）、`tests/unit/guards/` 全目录、评测判据定义与 held-out 划分。
- 注册表内容变更 = 改规则：只走人工 PR + 守卫测试红绿，不进任何自动通道。
- 首批可演化对象按"已有判据宿主"优先登记：
  - **L1 参数**（`approval` 档起步）：RSI 11 参数（integration_manager.OPTIMIZABLE_PARAMETERS 五族：sleep/emotion/experience/tool_memory/context——判据宿主 = eval_harness 决策档）；工具权重（closed_loop，判据宿主 = 工具选择端到端标尺 task_yardstick）；swarm 编排参数（MAX_ACTIVE_CHILDREN、max_subagent_depth 等，单源在 agent_limits_settings）；
  - **L1.5 模型可见文本**（走 evolution/eval 管线，`text_evolution` 已开）：soul.md、constitution、behavior_rules、rules_sections、技能 SKILL.md——判据宿主 = suite_eval 的 `EvalCase`（`subject_id` 字段即为"被守卫的模型可见文本"设计，`validateCaseFirst` 强制改动面被 case 覆盖，`assertCaseRedGreen` 红绿自检）；
  - **L2 代码**：首批白名单见 §6 P2-3。
- 与现有收口：`_FORBIDDEN_TARGET_PREFIXES` 与 PR patch 目录白名单**收编进注册表**（self_improvement_proposer 改读注册表，黑名单数据不搬双份）。

### 3.2 generation_ledger.py —— 世代账本

```python
class GenerationLedger:
    def openGeneration(parentNo, signals, changes) -> EvolutionGeneration: ...
    def recordVerdicts(generationNo, verdicts: dict[str, GateVerdict]) -> None: ...
    def recordDecision(generationNo, decision: DecisionRef) -> None: ...
    def markDeployed(generationNo, deployment: DeploymentRef) -> None: ...
    def markRejected(generationNo, reason: str) -> None: ...
    def markRolledBack(generationNo, restoredTo: int) -> None: ...
    def currentBaseline() -> EvolutionGeneration: ...      # 当前生产基线代
    def lineage(generationNo) -> list[EvolutionGeneration]: ...  # 谱系回溯
```

- 状态转移合法性沿用 proposal_lifecycle 的纪律风格：非法转移抛错，不静默。
- 与 RSI 现有持久化的关系：RSI 的回执/指标/摘要继续各司其职，世代账本只记**跨臂的代际因果**（哪代包含哪次 RSI 迭代/哪个提案/哪个 pr_patch），不复制它们的数据。

### 3.3 survival_probe.py —— G0 存活探针（"跑不跑得起来"的唯一判据源）

```python
class SurvivalProbe:
    def probe(workspace: Path, dataRoot: Path) -> list[GateVerdict]:
        """在给定工作区+隔离数据根上执行五项存活判据，逐项返回三态结论。"""
```

五项判据（任一 failed → 该世代没资格参评业务判据）：

1. **构建**：`create_app()`（neurova/api/app.py:1715，进程内单例——探针在独立子进程中运行，单例无碍）可构建，关键路由注册齐全（含 `/v1/providers`）；
2. **健康**：`/health`（app.py:797）返回 ok；`/health/detailed`（app.py:806）无降级告警；
3. **启动**：测试启动日志 `[ERROR]` 计数为 0 且出现 "Neurova API Server started successfully"（app.py:1454；AGENTS.md §0 同款判据）；
4. **最小对话**：桩模型下走通一个最小对话回合，agent 返回非空回复；
5. **工具执行**：ToolExecutor 成功执行至少一个内建只读工具；
6. **守卫子集**：架构守卫测试子集全绿（身份单通道、迁移表、尺寸棘轮、本注册表守卫）。

设计约束：

- 探针**不读任何被演化对象的内容**，只测行为——防止判据被改动内容绕过；
- 探针自身与判据阈值 `forbidden`（进 TargetRegistry 禁改清单）；
- 判据失败必须逐项点名（unevidenced 与 failed 分开报，沿用 GateVerdict 语义）。

### 3.4 gate_chain.py —— 门禁链编排

```python
class GateChain:
    def run(shadow: ShadowRunResult) -> dict[str, GateVerdict]:
        """按序执行 G0→G4，返回各门禁三态结论；G0 失败短路（后续不跑）。"""
```

| 门禁 | 内容 | 数据来源 | 失败语义 |
|---|---|---|---|
| G0 存活 | SurvivalProbe 五项 | survival_probe | 没资格参评，短路 |
| G1 契约 | 既有架构守卫子集 | tests/unit 守卫 | 红线，一票否决 |
| G2 业务 | 绑定 verdictSuite 的判据集：L1 参数用 rsi/eval_harness 决策档；L1.5 文本/技能用 evolution/eval 留出集 + suite_eval EvalCase（subject_id 对齐"模型可见文本先 case 后修"纪律） | 既有评测面 | 分数不升不拒，显著回退拒 |
| G3 回归 | 与父代基线 A/B，零新增失败 | A/B 自证流程（patch 法） | 不退步 |
| G4 教义 | 先红后绿证据 + live-verify 证据（仅 L2 代码态） | 候选附带的证据包 | 仓纪律 |

- 裁决映射：`auto` = G0-G3 全绿自动进金丝雀（仅限注册表 auto 档对象）；`approval` = 全绿后进治理审批（复用 governance 端点 + proposal_lifecycle 状态机）；G4 是 L2 的附加必要条件。
- 与现有收口：RSI 已有的晋升判据（相位转换三态）与提案部署 gate（风险→相位）**保留**，GateChain 在其外层做跨臂统一——不推翻，做编排。

### 3.5 shadow_verify.py —— 影子验证执行器

```python
class ShadowVerify:
    def verify(generation: EvolutionGeneration) -> ShadowRunResult:
        """在隔离环境应用候选变更并跑完整门禁链。"""
```

- 隔离机制：**独立子进程 + `NEUROVA_DATA_DIR` 注入**（core/data_root.py:37 是数据根唯一注入口，调用时解析、非法值当场 ValueError）——影子进程指向临时数据根，与生产数据根物理隔离；不借用 neuacp 的租户隔离机制（那是池键租户段 + run 级凭据，语义不同）；
- L1 候选：在隔离根上以参数覆盖方式应用（不动源码），跑 G0-G3；
- L2 候选：在隔离 git 工作区 apply patch（`git apply --check` 先行），跑 G0-G4；
- 验证产物（日志、判据读数、diff）随世代归档，作为 G4 证据包与审计材料；
- 测试同构：单测复用 conftest 既有模式（导入期 env 注入 + autouse fixtures），不另造隔离法。

### 3.6 L2 生效通道（补 `_plan_activation` 的 PR_PATCH 分支）

现挂点：`self_improvement_proposer._plan_activation`(:965) 对非 SKILL_MANIFEST 返回 `not_supported`。本详案**不改动该诚实拒绝的默认行为**，而是新增显式生效路径：

```python
# 新增 rsi/pr_patch_channel.py
class PrPatchChannel:
    def plan(proposal) -> PatchPlan | str:        # 仅接受 PR_PATCH 且过注册表 assertMutable
    def verify(proposal, plan) -> dict[str, GateVerdict]:  # 影子工作区 apply + G0-G4
    def apply(proposal, plan, approver) -> ApplyResult:    # 基线工作区 apply + CheckpointService 快照
    def rollback(proposal) -> RollbackResult:              # 反向 patch / 恢复快照
```

- **合入链复用 swarm 既有闸门，不新造**：patch 产出到落地的完整链 = 候选提交（CandidateMergeBoard.submitCandidate，同基准冲突双保留）→ 审批（approval_chain 分级，代码修改按高危分类；grant 记忆式放行对 L2 永不生效的红线直接继承）→ CAS 合入（mergeCandidate，baseRevision 不一致即升级人工）→ run 结算。self_improvement_proposer 的双 gate（人类评审 + 部署阶段）作为提案准入层叠加在其前；
- 生成端接 neuacp：swarm 团队成员（executor=acp）产出的代码修改，经 `propose_pr_patch(target_file, patch_content, description, risk_level="high")` 进提案通道——复用现有沙箱校验（路径穿越/系统文件前缀/目录白名单/危险模式），**不新建审批面**；
- `approve_and_apply` 的部署 gate 对 PR_PATCH 保持 high→phase≥4（即只有系统跑到"有条件自动/全自动"相位才可能生效），起步阶段全部走人工；
- 应用级快照接 CheckpointService **scope 化 API**（captureScope/rollbackScope 现成但无生产写入方——本通道即写入方；scope_id=世代 ID，ordinal=尝试序号），isolation_check 复用其"活跃 run 共享工作区则只做会话级回退"语义；
- neuacp 侧约束沿既有红线：进程池键租户段首位（跨租户不共享进程）、run 级凭据 HMAC 绑定、API-key 不得配置外部成员、派活走租户校验。

### 3.7 policy.py + meta_evaluator.py —— 元层（L3）

- `EvolutionPolicy`（可版本化，沿 ImproverVersionLedger 范式）：候选来源权重（RSI/eval/neuacp）、每代预算上限（token/时长）、并发度、金丝雀观测窗与回滚阈值（在注册表允许区间内取值）；
- `MetaEvaluator`：按各来源候选的**存活率、门禁通过率、金丝雀期表现**在允许区间内调参；调参本身作为 L3 世代入账本；
- **区间边界与评估规则 `forbidden`**——策略可以在边界内自我调整，边界本身只能人工改；
- 与现成件收口：`strategy_comparison.py`（已实现未接线）接入为 MetaEvaluator 的策略对比读数；`deployment_amortization.py` 接入为成本摊销读数——两件从"仅测试消费"转正。

### 3.8 signal_bus.py —— 信号层（轻量）

- 汇聚四路**已在写**的信号源，逐路落实：
  1. 教训/反思台账：`cognitive_layers/meta_cognition_layer/growth_log.py` 的 `ReflectionLogEntry`（type=error/improvement/pattern/insight/strategy；status=pending/applied/validated/rejected 生命周期现成）——借道 MemoryManager 落盘（category="reflection"）；
  2. 评测失败：suite_eval `EvalCase` 失败例 + rsi/eval_harness 例级回归（C1 判据已产）；
  3. 质量信号：`quality/outcome_store.py` ConversationQualityStore（SQLite，turn_outcome / human_takeover 事件——渠道人工接管即"不满意硬信号"，channels/manager.py:504 已写入）；
  4. 运行失败：`core/agent_run_ledger.py`（SQLite data/agent_runs.db）终态分类 + `error_logger` JSONL；
  5. **跨租户共性聚类**：对带 tenantId 的信号按模式签名（失败类别/工具序列/判据 ID）做跨租户计数——**≥3 租户同模式（N=3，2026-11-21 拍板）**升格为 global 世代候选（统一进化，见 §10.6），未达标保持 tenant 级；聚类只在脱敏签名层进行，原始证据不跨租户；
- 输出：`SignalRef`（type/id/digest/severity），供世代 openGeneration 引用（"为什么改"可追溯）；
- 不新增采集机制——本件只做**引用登记与去重**；高严重度信号（如 validated 的 error 反思、human_takeover）可按 evolution_settings 节流触发世代提案。

### 3.9 各类对象的回滚机制（总纲"跑不通自动回滚"的逐类落点）

自动回滚不是单一机制——五类对象的"恢复安全态"路径不同，必须逐类钉死（否则总纲在非参数对象上是空话）：

| 对象 | 回滚机制 | 触发 | 现状 |
|---|---|---|---|
| L1 参数（RSI 四族） | `_snapshot_optimizable`/`_restore_optimizable` 参数快照 + `rollback_manager.create_snapshot/execute_rollback` 留痕 | `should_rollback` 五条件自动判据（发散/负ROI/CI上界<0/e2e<0/例级退化） | **已有，全自动** |
| L1 工具权重/生命周期 | tool_weights.json / tool_lifecycle.json 的 mixin 快照恢复 | 待接：权重异常（如大面积降级）告警触发恢复 | 部分有（持久化在，自动回滚判据无） |
| L1.5 文本（soul/constitution/技能正文） | `update_auto_skill` 的 revisions 快照弹回 / `skill_experience.rollback_skill` 归档恢复 / journal.git 反向 commit | **待建**：部署后质量观测（suite_eval 周期复跑 or 质量事件阈值）→ 自动调 rollback | 有人工回滚，无自动触发（P1-6 补） |
| L2 代码 | PrPatchChannel 反向 patch；CheckpointService `rollbackScope`（isolation_check） | 同上观测判据 + CAS/审批记录回溯 | 待建（P2-1） |
| L5 行为规则（dreaming） | active 规则降回 candidate + 审计留痕（判定面立即失去该规则） | 转正后反馈恶化（dreaming_feedback 已采回合反馈） | 部分有（反馈采集在，自动降级无） |
| 世代级（跨对象打包） | CheckpointService scope 快照 `restoreScope`（isolation_check 防误伤活跃 run） | 世代任一 change 的对象级回滚条件命中，或世代整体健康越界 | API 在位，写入方待接（P1-4/P1-6） |

**设计约束**：所有回滚动作必须（a）留痕世代账本（rolledBackTo + 原因）；(b) 回滚后该世代终止、下一代以恢复后的基线为父；(c) 回滚本身不需要人工确认——人工只做事后复盘。

---

## 4. 与既有件的收口关系（教义第 6/7 条）

| 既有件 | 处置 |
|---|---|
| RSIOrchestrator 及其全链 | **保留为主力 L1 引擎**；GateChain 编排其判据，不推翻 |
| GateVerdict 三态 | 全链沿用，GateChain 的统一词汇 |
| deployment_controller 5 相位 | 保留；GateChain 裁决映射到相位语义（auto/approval 即相位门槛） |
| rollback_manager | 保留为回滚判据唯一真源；新增的 CheckpointService 快照是应用级兜底，二者互补不重叠 |
| self_improvement_proposer | 保留为提案/审批/快照骨架；_FORBIDDEN_TARGET_PREFIXES 收编进 TargetRegistry；PR_PATCH 生效通道由 pr_patch_channel 补齐 |
| evolution/eval 管线 | 保留为 L1.5 文本/技能判据面；GateChain G2 直接复用其留出集结论 |
| closed_loop 工具权重 | 保留；工具权重对象登记进 TargetRegistry |
| proposal_lifecycle | 世代状态机沿用其纪律风格；提案状态机不动 |
| strategy_comparison / deployment_amortization | 接线转正（MetaEvaluator 消费） |
| checkpoints/service | 应用级快照与恢复（L5 兜底） |
| neuacp | L2 候选生成执行体（沿租户隔离红线） |

**不新建**：审批系统、评测系统、回滚系统、部署相位——全部复用。

---

## 5. 安全红线（回应"万一改坏了跑不起来"）

七层防线，前三层是结构性的：

1. **L0 禁改内核**：TargetRegistry forbidden 清单 + 守卫测试逐条钉死（内核文件、身份通道、迁移表、注册表自身、探针自身、守卫目录、判据与 held-out）；
2. **L1 候选隔离**：候选只存在于世代（影子环境/隔离数据根/隔离工作区），生产基线只接受晋升；
3. **L2 存活门禁**：SurvivalProbe G0 一票否决且短路——业务分再高，起不来就没资格；
4. **L3 裁决分级**：auto 仅限低风险 L1；L2 一律人工（high→phase≥4）；审批走既有双 gate；
5. **L4 金丝雀**：全绿世代先影子流量对比，观测窗通过才切；
6. **L5 回滚**：RSIRollbackManager（判据）+ CheckpointService（应用级快照）双兜底；回滚后世代标 rolledBack，事故进教训台账成为下一轮信号；
7. **L6 降级**：L1 对象必须有 fallbackRef（默认值兜底）；单个技能/agent 定义坏 → 隔离跳过，平台继续运行。

**裁判保护**：判据逻辑、阈值、held-out 划分、注册表内容 = 规则；改规则只能人工 PR + 守卫红绿，任何自动通道不可达。

---

## 6. 分期实施计划

**路线总纲（两期战略）**：

- **第一期——本仓递归自进化现状的修补与优化**（R 批 + P0–P3）：不动大架构。先做 **R 批（机制咬合/修补）**——让已建成但空转的机制第一次跑通完整闭环（§1.4/§1.7 A 类）；再做 **P 批（统一治理/优化）**——把既有五臂收口到统一治理框架下，补齐安全地基（禁改内核/存活探针/世代账本）与门禁链，L2 白名单试点，元层起步。产出是一个**可信、可控、可回滚**的自演化操作系统。
- **第二期——Neurova Harness 框架的递归自进化，内部代号 Harness^N**（P4 起，另立设计文档）：以第一期交付的治理框架为地基，把 Neurova 整体作为可演化 harness，追求"演化能力本身逐代增强"的递归形态。n 的三重含义工程化为三个机制：无限演化可能→世代链无终点、可演化面随代际扩展；能力几何式增强→复合增益（上代成果进入下代基线，演化工具链自身也在被演化）；n=Neurova→自指演化，Neurova 演化 Neurova。详见 §6.5。

### R 批：机制咬合（最先行——先让已有机制跑通，再谈统一治理）

> **实施顺序硬约束：R6 的相位回调必须先于 R1 的候选激活落地。** 当前 `rsi_phase=4` 为全自动档——若先修复候选枯竭（R1）而后回调相位（R6），重新出现的第一个候选将直接以全自动档执行未验证变更。顺序：R6（回调+门槛）→ R1/R2/R3 并行 → R4 评估 → R5 随时。

| 卡 | 内容 | 主要落点 | 验收判据（红→绿） |
|---|---|---|---|
| R1 | **RSI 咬合修复**：激活回滚持久化（生产配置 `NEUROVA_EVOLUTION_ROLLBACK`）；扩展可演化参数/信号面使候选重新产生（现 5 族 11 参数全部 no_candidate/placeholder_host）；测量前置接通（measure_state 不再恒 not_attempted） | rsi/orchestrator、integration_manager、部署配置 | 红灯：现状跑一轮 applied_count=0；绿灯：出现第一个**被应用且实测**的优化（applied_count≥1 且 gain_evidenced），回滚历史可写 |
| R2 | **EvalCase 首批生产立案**：为最常改的模型可见文本面（soul/constitution/behavior_rules/rules_sections）各立≥1 个 EvalCase（subject_id 对齐），并把 `validateCaseFirst` 接入文本改动流程 | benchmark/suite_eval、文本进化链路 | 红灯：无 case 时改动文本无拦截；绿灯：立案后 `validateCaseFirst` 对未覆盖改动报 missing、对已覆盖改动放行 |
| R3 | **multi_agent 评测跑批入口**：补生产触发 API（现仅只读报告端点），首跑产出基线报告落 `data/benchmark/` | api/endpoints/benchmark、multi_agent/report | 红灯：跑批无入口；绿灯：API 触发→报告落盘可读回 |
| R4 | **metacog V3 调控门全局启用**（**已拍板 2026-11-21：直接全局开启**）：`metacog_gate_enabled=true`，教训拦截工具执行上线；上线首周重点观测误拦率，异常经治理面关闸回退 | governance_settings、tool_executor.py:844 | 红灯：门开后再现历史误拦形态（如有）；绿灯：门开且 avoid_tool 教训真实拦截生效、关闸回退演练通过、误拦率周报出街 |
| R5 | **回滚持久化参数化 + 设置面暴露**：`resolve_rollback_state_path()` 的 env-only 门控升级为「env > 设置键 > 默认」三级（新设置键 `rsi_rollback_persistence_enabled`，挂 evolution_settings 的 rsi 参数族，默认值翻转为**开**——审计数据源不应默认缺席）；落盘路径走 data_root 派生（测试环境随 conftest 临时数据根自动隔离，不污染仓库）；前端在既有 `RsiGovernancePage` 增设"回滚持久化"开关（i18n 11 语言） | rsi/rollback_manager.py:30、rsi/orchestrator.py:315-326、evolution_settings、NeurUI RsiGovernancePage | 红灯：默认配置下回滚历史零写入（现状）；绿灯：开启后 create_snapshot/execute_rollback 落盘可读回、关闭时零 IO、测试不写仓库根 |
| R6 | **相位顶格修正（phase=4 与证据脱节）**：① 立即将 `rsi_phase` 回调至 1（手动档，**已拍板 2026-11-21**）；② `evaluate_phase_transition` 增补**实做次数门槛**（**已拍板：2→3 需 ≥3 次、3→4 需 ≥10 次**真实应用）——堵住"空转也能升顶"的结构性漏洞；③ agent 级灰度沿 `resolveRsiPhaseFor` overrides 逐个放开，全局默认收紧 | deployment_controller.py:171-260、governance_settings、rsi/orchestrator.py:1215-1266 | 红灯：0 应用的现状下晋升判据仍可通过（可复现）；绿灯：回调后 phase=1、未达实做次数时晋升判据 failed（点名缺什么）、真实数据达标后才可逐级晋升 |
| R7 | **RSI 面板参数化**：把演化运行参数统一做成可设置项，暴露到既有 `RsiGovernancePage`（新增参数区）——① 金丝雀观测窗 `rsi_canary_window` 与回滚阈值族 `rsi_canary_rollback_thresholds`（新键，P1-4 金丝雀实现读取）；② `metacog_gate_enabled`（已有键，面板暴露开关）；③ `rsi_phase` 读写（已有键；**写入口从 SettingPage 治理卡片收敛到 RSI 面板单点**，消除"两处可改迟早漂移"——RsiGovernancePage:9 注释已预警）；④ 实做次数门槛 `rsi_phase_min_applied`（R6 新判据的参数，默认 {2:3, 3:10}）。全部沿「env > 设置文件 > 默认」既有优先级范式；**面板可调的是参数值，判据结构与禁改清单不进面板**（裁判件边界不变） | governance_settings、deployment_controller、NeurUI RsiGovernancePage（i18n 11 语言） | 红灯：参数写死无法调整（现状）；绿灯：面板改值→后端读数随之变化（如窗长改短在金丝雀演练中可观测）、metacog 开关即时生效、phase 面板写入口唯一、越界值 422 |

### P0 安全地基（先行，独立可验收）

| 卡 | 内容 | 主要文件 | 验收判据（红→绿） |
|---|---|---|---|
| P0-1 | TargetRegistry + 禁改内核清单 + 注册表守卫测试 | rsi/target_registry.py、tests/unit/evolution/rsi/test_targetRegistry.py | 红灯：对内核文件构造变更请求被拒；绿灯：forbidden 清单逐条断言、assertMutable fail-closed |
| P0-2 | SurvivalProbe 五判据 + 探针自检 | rsi/survival_probe.py、tests/.../test_survivalProbe.py | 红灯：注入"起不来"的桩环境探针报 failed；绿灯：健康环境全 passed、逐项可点名 |
| P0-3 | GenerationLedger + 状态机守卫 | rsi/generation_ledger.py、tests/.../test_generationLedger.py | 红灯：非法转移被拒；绿灯：谱系回溯/基线指认可用；env 未配置不 IO |

### P1 L1 闭环（参数/文本/技能走通全链）

| 卡 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| P1-0 | suite_eval run 结果落盘（补 _RUNS_STORE 进程内断点，落 data/benchmark/） | 无 | 重启后 run 历史可读回；G2 选 suite_eval 面的前置 |
| P1-1 | GateChain 编排（G0-G3，L1 范围） | P0 | 门禁链单测：G0 失败短路、G2 用 eval_harness 决策档 |
| P1-2 | ShadowVerify 隔离执行器（独立子进程 + NEUROVA_DATA_DIR 注入） | P0-3 | 影子环境完整启动+判据；与生产数据根隔离证明 |
| P1-3 | 世代编排器接线（RSI 迭代产出到世代；信号源接 signal_bus 四路） | P1-1/2 | 一次 RSI 迭代形成完整世代记录（信号/变更/判据/裁决） |
| P1-4 | 金丝雀 + 回滚演练 | P1-3 | 影子对比→晋升；注入异常→自动回滚父代并留档 |
| P1-5 | 治理端点扩展（世代查询/人工裁决入口） | P1-3 | GET 世代谱系；approval 裁决经既有 governance 权限面 |
| P1-6 | **全自动闭环贯通（总纲验收）**：信号立案→候选→影子验证→门禁→晋升/拒绝→部署观测→自动回滚，全链无人值守跑通；文本/代码代的"部署后自动回滚"通道补齐（现仅参数臂有 should_rollback 自动判据，文本臂只有人工 rollback） | P1-1/2/3/4 | 演练一：低风险对象从信号到晋升零人工；演练二：注入部署后故障→自动回滚上一好代并留痕；全程台账完整 |
| P1-7 | **quality/swarm 事件补 tenant 段**（§10.4 两缺口，已拍板并入 P1）：两库表结构加 tenant_id（随 run/session 上下文写入），历史行归档不迁移；SignalBus 全局代信号的租户分布校验只认带租户段信号 | P1-3 | 两事件库写入带租户、跨租户计数只采信带段信号；A/B 零新增失败 |
| P1-8 | **前端 UI 与移动端按需适配**：后端每交付一个用户可见面，前端同步适配——① NeurUI：`RsiGovernancePage` 扩展世代谱系/门禁链结果（G0–G4 三态）/回滚历史读面（接 P1-5 端点），R5/R7 参数区照卡落地；② 移动端（harmony/android-native）管理员域**按需只读适配**：演化状态、当前基线世代、门禁结果摘要卡，接同一批端点，无既有页面的做最小只读呈现，操作类（审批/参数修改）以 PC 端为主；③ i18n：NeurUI 11 语言、移动端按各自 locale 纪律；④ 范围纪律：**根据改动内容的需要进行适配**——不做与演化能力无关的 UI 改动，每项呈现对应一个已上线的后端读面 | P1-3/P1-5 + R5/R7 | PC 端可查看世代谱系与门禁结果；移动端管理员可只读查看演化状态；vitest+vue-tsc 绿、移动端对应测试绿；i18n 键齐 |

### P2 L2 代码级试点

| 卡 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| P2-1 | PrPatchChannel 生效通道（verify/apply/rollback；合入走候选 CAS 板+审批链；快照接 scope 化检查点写入链） | P1 | not_supported 移除仅对 PR_PATCH；apply 前必过 G0-G4；CAS 冲突升级人工；快照/回滚演练 |
| P2-2 | neuacp 候选生成接入 | P2-1 | swarm 外部成员产出 → propose_pr_patch 入提案通道（沙箱校验+双 gate 不变） |
| P2-3 | 首批 L2 白名单（建议：prompt 编译器、技能卡目录） | P2-1 | 注册表登记 + 守卫；白名单外 patch 一律拒 |
| P2-4 | 两臂提案持久化收口（§1.7-11：RSI 臂改原子写+有界；存储格式与 API 路由统一单源） | P1 | 两臂提案读写走同一契约；非原子写消除；A/B 零新增失败 |

### P3 元层递归

| 卡 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| P3-1 | EvolutionPolicy 参数化 + 版本台账 | P1 | 策略调参入世代账本；越界被拒 |
| P3-2 | MetaEvaluator + strategy_comparison/deployment_amortization 接线 | P3-1 | 按存活率/通过率在区间内调参；两件空转件转正有消费方 |
| P3-3 | 评测棘轮自动化（失败沉淀 EvalCase，判据逻辑仍人工） | P1 | 失败案例自动入册；判据定义变更仍走人工门 |
| P3-4 | 遗传种群持久化 + 闲置件处置（§1.7-12/13：遗传种群入 bootstrap 或明确豁免留痕；facade 单例对/GeneticConfig/NLToolSynthesizer/soul.json 逐一接线或退役） | P1 | 重启后种群不归零（或豁免有据）；闲置件逐件有结论（接线/退役），零静默遗留 |

### 6.5 第二期（P4 起）：Harness^N —— Neurova harness 框架的递归自进化

> 内部代号 **Harness^N**（harness 的 n 次方；代码标识符建议 `HarnessN`/`harnessN`，模块落 `neurova/evolution/harnessn/`）。
> n 的三重含义：**无限演化可能**（世代链无终点、可演化面随代际扩展）、**一次演化后能力几何式增强**（复合增益）、**n = Neurova**（自指：Neurova 演化 Neurova）。
> **独立设计文档：[2026-11-21-harness-nth-power-design.md](2026-11-21-harness-nth-power-design.md)——二期机制、卡位与待拍板项以该文档为准，本节仅留概要。**

**与第一期的关系**：第一期交付的六件套（TargetRegistry / GenerationLedger / SurvivalProbe / GateChain / ShadowVerify / PrPatchChannel）+ 元层（Policy/MetaEvaluator）就是 Harness^N 的运行时底座。第二期**不另起炉灶**，在同一框架内做三件事：扩大演化面、加深递归、拉长自主性。

**二期核心扩展（卡位草案，待独立设计文档细化）**：

| 方向 | 一期状态 | 二期目标 |
|---|---|---|
| 演化面 | L2 白名单 2 个模块试点 | 注册表治理下的大范围代码面（内核 forbidden 红线不变），L1/L1.5/L2/L3 全层常态运转 |
| 递归深度 | MetaEvaluator 区间内调参、判据人工守护 | 改进器版本自动升级闭环（ImproverVersionLedger + 配对探针 Γ 判据转全自动档）；判据辅助进化（人工终审）；**演化工具链自身入注册表成为可演化对象**（递归的递归） |
| 多臂协同 | 各臂独立世代 | 同一世代可打包多臂变更（参数+文本+技能+代码），门禁链统一验证，谱系归一 |
| 执行体 | neuacp 单成员串行产候选 | 多外部编码 agent 并行产候选，候选 CAS 板统一合并 |
| 自主性 | 手动触发一轮 / 定时一轮 | 信号驱动持续演化（高严重度信号实时立案），仍受预算门/审批门/相位门约束 |
| 增益度量 | 单代 gain/ROI | **复合增益曲线**：候选存活率、门禁通过率、单位预算增益、改进器版本 Γ 的代际趋势——"几何式增强"必须有可测口径，防口号化 |

**二期立项前置条件（一期验收门）**：P0–P3 全部完成 + 存活不变式演练通过 + 至少 3 个完整世代（含 1 次回滚演练）+ L2 白名单试点产生首个被采纳的代码级改进。

**预期校准（诚实声明）**：LLM 驱动的自演化，实际增益受评价器质量与任务分布约束，代际增益通常是线性或阶跃，"几何倍增强"应作为**方向性愿景**而非承诺指标；工程上以复合增益曲线如实记录、按数据说话。

---

## 7. 全局验收判据

1. **存活不变式**：任意世代流程（含回滚、拒绝、金丝雀失败）之后，SurvivalProbe 五判据必须全绿——这是反复演练的回归主判据；
2. **谱系完整**：任一生产行为可回溯到"第几代引入"，任一世代可回溯到信号与父代；
3. **零基线污染**：影子/金丝雀/回滚全程，生产数据根无写入；
4. **裁判不可达**：自动演化通道对 forbidden 对象的任何变更请求全部被拒（守卫测试钉死）；
5. **既有面零回归**：RSI 既有测试、提案审批测试、eval 管线测试 A/B 零新增失败；
6. **全自动闭环（总纲验收）**：对任一低风险对象，从信号立案到晋升/拒绝/回滚的全流程可在**零人工介入**下完成并全程留痕；注入部署后故障时自动回滚到上一好代；人工仅出现在三处保留点（裁判件变更、禁改清单变更、相位未达标的高危 L2 放行）。

### 一期完成定义（DoD）

- [ ] R 批六卡全部验收通过（R6 相位回调先行；R1 产出第一个被应用且实测的优化；R2 首批 EvalCase 生产立案；R3 首份 multi_agent 基线报告落盘；R5 回滚持久化默认开且入设置面板）；
- [ ] P0–P3 全部卡验收通过（注册表+守卫、存活探针、世代账本、门禁链、影子验证、金丝雀、L2 通道与首个被采纳的代码级改进、提案收口、元层起步）；
- [ ] 前端 UI 与移动端按需适配完成（P1-8）：PC 端世代谱系/门禁结果读面、移动端管理员只读状态卡、i18n 键齐；
- [ ] §7 六条全局判据全部满足，且在连续 10 个世代（含至少 1 次真实回滚）中保持；
- [ ] 闲置件处置完毕（逐件接线或退役，零静默遗留）；
- [ ] 两份文档（本详案 + Harness^N）与代码实况一致，0-index 已登记。

---

## 8. 待拍板项

1. **L1 自动化程度**：**已拍板（2026-11-21）：直接开 auto**——低风险对象 G0-G3 全绿即自动晋升金丝雀，中高危仍走审批；落地时须写明与旧 `rsi_phase` 门的边界（新世代管线 auto 晋升的变更落地仍受目标宿主既有安全门约束：参数边界夹紧+回执、prompt 落技能评审闸）；
2. **禁改内核清单范围**：**已拍板（2026-11-21）：维持首批 9 项**（agent_core/tool_executor/llm_client/context_pool/identity_context/db_migration/注册表自身/探针自身/guards 目录）——宁窄勿宽，先少后加；
3. **首批 L2 白名单**：**已拍板（2026-11-21）：prompt 编译器 + 技能卡目录**——两者都有现成测试面且不在启动链路上；
4. **金丝雀观测窗与回滚阈值**：**已拍板（2026-11-21）：保守起步**——短观测窗 + 敏感回滚阈值，先保证不出事，再按实测数据放宽；**已参数化**（R7：`rsi_canary_window` / `rsi_canary_rollback_thresholds` 进 RSI 面板，保守值为默认）；
5. **多租户灰度策略**：**已拍板（2026-11-21）：金丝雀只做影子评测对比 + 人工晋升，永不碰生产流量**——生产租户零暴露；"指定内部租户先行切流"能力不建；
6. **信号租户段补齐顺序**：**已拍板（2026-11-21）：并入一期 P1**（新增 P1-7 卡）——quality/swarm 事件的 tenant 列随 P1 一并补齐，作为 SignalBus 全局代信号分布校验的前提。
7. **metacog V3 调控门是否启用**（R4）：**已拍板（2026-11-21）：直接全局开启**（`metacog_gate_enabled=true`）——出问题靠治理面关闸回退；上线首周重点观测误拦率；**已参数化**（R7：开关进 RSI 面板，随时可关闸）；
8. **RSI 参数面扩展方向**（R1 的候选枯竭对策）：**已拍板（2026-11-21）：先扩信号**——接通更多反馈信号源让现有 11 参数有据可调（成本低、不动参数宿主）；参数面扩展随 TargetRegistry 登记逐步放开。
9. **相位回调目标值**（R6 立即动作）：**已拍板（2026-11-21）：回调到 1（手动档）**——与"0 应用/0 回滚/测量未跑"的证据严格匹配；R 批产出真实数据后按判据（含实做次数门槛）逐级重升；**已参数化**（R7：`rsi_phase` 读写进 RSI 面板单点，实做门槛 `rsi_phase_min_applied` 同面板）；
10. **实做次数门槛 K 值**（R6 判据增补）：**已拍板（2026-11-21）：2→3 需 ≥3 次、3→4 需 ≥10 次**真实应用（applied_count>0 的迭代计数）；上线后按实测数据复核校准。
11. **共性聚类阈值与签名规范**（§10.6）：~~跨租户升格 global 的租户数阈值 N~~ **已拍板：N=3（2026-11-21）**；**仍待细化**：模式签名规范（失败类别/工具序列/判据 ID 的粒度）——签名过粗会误并异因问题，过细则聚类失效；建议先人工复核前若干例再固化自动阈值。

---

## 9. 风险登记

| 风险 | 对策 |
|---|---|
| 评价者被收买（改判据刷分） | 判据/阈值/held-out 全部 forbidden；改规则走人工；unevidenced 三态防"没数据冒充通过" |
| 级联污染（坏代被继承） | 世代 parentNo + 基线冻结 + 回滚后禁直接续代（须先归因） |
| 成本失控 | EvolutionPolicy 预算上限 + 每代成本向量（复用 E1/E2 资源记账）+ 手动触发默认 |
| 影子环境与生产漂移 | 影子环境用同一 create_app 装配与同一判据套件；G0 即"真启动" |
| 外部 agent（neuacp）供应链风险 | 进程池键租户段首位（跨租户不共享进程）+ run 级 HMAC 凭据 + PR patch 沙箱校验 + 候选 CAS 板冲突升级人工 + 审批链 L2 强制人工（grant 永不预授权）+ phase≥4 |
| 定时驱动假成功 | 世代编排的定时触发走 `get_scheduler().addSystemJob`（未 start 已自愈先 start，scheduler.py:796）；不新造第二台调度器 |
| **实施顺序风险**：R1 先于 R6 落地会让新候选以 phase 4 全自动执行未验证变更 | 硬顺序约束写入 R 批（R6 相位回调先行）；在 R6 合入前，R1 的验收环境锁定 phase≤1 |
| 回滚持久化默认开后的测试污染 | 落盘路径走 data_root 派生（conftest 临时数据根自动隔离）；守卫沿用"仓库根污染"判据（test_repo_root_pollution_guard） |
| 与在途会话冲突 | 新模块全部落独立文件；对 self_improvement_proposer 的修改最小化（仅 _plan_activation 分支与黑名单收编） |

---

## 10. 多租户影响面与对策

问题：Neurova 是多租户架构（JWT 租户 = 部门根），框架演化改的大多是**全局共享面**（代码、全局参数、系统提示词组成面、工具权重初值），会不会影响各租户的使用体验？

结论：**会有影响，但可以设计成"可审计、可回滚、可按租户退出、不被单一租户的信号带偏"**。关键是把"作用域"作为演化对象的一等维度（TargetRegistry.scope），并给信号与判据补租户视角。

### 10.1 四条影响路径与对策

| 影响路径 | 具体表现 | 对策 |
|---|---|---|
| 共享面改动波及全体 | 全局 prompt/参数/代码的变更同时作用于所有租户 | scope 分级：global 对象的世代判据必须覆盖多租户样本；tenant/agent 对象走租户内世代，只影响自己 |
| 信号偏差（大租户绑架演化） | 某活跃租户的失败信号驱动全局演化，可能伤害其他租户 | SignalRef 带 tenantId；global 世代的信号集登记租户分布，**禁止单一租户信号占比超阈**（默认 >70% 拒绝立案，转 tenant 级提案） |
| 验证环境不代表租户分布 | 影子判据只用单租户任务，晋升后他租体验回退 | G2 判据集与 held-out 按租户形态分层采样；global 世代 G2 必须含跨租户样本 |
| 资源挤占 | 影子验证/金丝雀跑评测抢占生产算力 | 影子进程独立数据根 + 独立进程（已设计）+ EvolutionPolicy 预算上限 + 可配维护窗口 |

### 10.2 金丝雀的租户纪律（重要）

- **默认不切生产流量**：金丝雀只在影子评测层面对比（模拟用户/评测任务包），生产流量切换默认关闭，晋升一律走审批链人工放行——生产租户永远不做实验品；
- 若未来开"按租户灰度切流"，只能是**admin 显式指定的自愿租户/内部测试租户**先行，且该租户可随时 opt-out 回父代；
- 仓内既有范式直接沿用：RSI 部署相位本就支持"agent 覆写 > 全局"（`governance_settings.resolveRsiPhaseFor`，deployment_controller.py:309）——演化相位的租户/agent 级覆盖走同一模式。

### 10.3 回滚的租户语义

- global 代回滚：恢复所有租户到上一好代——这是保护动作，不区分租户；
- tenant/agent 级对象异常：只回退该租户/该 agent 的覆盖值（fallbackRef 兜底），不动全局基线；
- 回滚动作本身走审批留痕，世代账本记 rolledBackTo。

### 10.4 信号面的两个既有缺口（需补租户段）

- `quality/outcome_store.py`（质量事件：turn_outcome / human_takeover）当前**无租户字段**；
- `agent/swarm_event_store.py`（swarm 事件）当前**无租户字段**；
- `core/agent_run_ledger.py:362` 已带 tenantId（A9 收口成果），失败信号有租户归属。
→ SignalBus 落地时，前两者要么补 tenant 列（随 run/session 上下文写入），要么在 SignalBus 层做"信号→租户"关联登记；在补齐之前，global 世代的信号只采信 run-ledger 系（有租户段）与 eval 失败（按任务包归属）。

### 10.5 租户可见性

- 世代谱系（改了什么、依据什么信号、影响哪些 scope）进 admin 审计面（沿 governance 端点扩展，P1-5）；
- 涉及 global 对象的晋升，审批人须能看到信号租户分布与判据覆盖面——影响面可见是审批的前提。

### 10.6 共性问题：聚类比对后统一进化

多租户共性问题的处理路径——**聚类比对，达标统一进化；不达标保持租户内演化**：

- **三层分流**：单租户问题 → tenant/agent 级世代（只影响自己）；**≥N 个租户出现同模式信号 → 聚类升格为 global 世代统一进化**（一次修复、所有报告租户受益，避免 N 份平行补丁——同一问题的 N 份修复正是教义第 6 条反对的平行体系）；先天全局性问题（内核/公共链路缺陷）→ 直接 global 世代。
- **聚类判定双闸**：① 模式签名跨租户计数达标（同失败类别/同工具序列签名/同判据失败；**阈值 N=3，2026-11-21 拍板**）；② 根因归并确认——表象相似不等于根因相同，由 Architect 式归并复核，防"伪共性扩散"伤及个别租户。
- **隐私红线**：跨租户比对只在**脱敏签名层**进行（失败类别、工具名、判据 ID、digest 计数）；原始会话内容与证据**永不跨租户可见**——聚类分析不得成为数据出境通道。
- **统一进化的额外验收**：global 修复的 G2 判据集必须包含**每个报告租户**的代表性样本——证明"解决了共性，且不伤任何报告方"。
- 落点：SignalBus 增加跨租户聚类步骤（§3.8 已同步）；聚类阈值与签名规范待拍板（§8-11）。

---

## 11. 执行记录与偏离说明（2026-11-22 实施完毕）

一期 25 卡 + 1 项待办清偿全部完成，在多会话并发开发环境下实施（期间其他会话并行落了 LLM 路由批、多代理协作修复批、reference_ad 计划等提交）。

### 11.1 实施波次与提交

| 波 | 卡 → commit |
|---|---|
| 文档 | 详案+二期设计入库 `621efb95f`；P1-8 卡补充 `ce6da5aa0` |
| 一 | R6 `a81e7e2bd`（phase 4→1+实做门槛）/ R2 `54b0abd3a` / R3 `bfff86e23` / P0-1 `9b4c7ec17` / P0-3 `7dae832b7` |
| 二 | R5 `dd3047de1`（回滚持久化默认开）/ R7 `a15f7c914`（RSI 面板参数化+写入口单点）/ P0-2 `e76ff8142`（存活探针六判据） |
| 三 | **R1 `cf99ec4e5`（第一个被应用且实测的优化）** / P1-0 `1dc0890cf` / P1-1 `60abde70f` / P1-2 `c44cb0d5c` |
| 四 | P1-3 `2725a3715`（世代编排接线，live-verify 世代 deployed）/ P1-7 `05121035c`（租户段）/ R4（metacog 门全局开，纯配置） |
| 五 | P1-4 `ce32d6dc1`（金丝雀+自动回滚演练）/ P1-5 `aa77eb3e6`（世代治理读面） |
| 六 | P1-6 `e3a57aaf4`（**全自动闭环三段演练全过**）/ P1-8 `ddf6b6e9a`+`422a5f2d4`+`dc4e06190`（NeurUI/鸿蒙/安卓） |
| 七 | P2-1 `08670e114`（PR_PATCH 生效通道）/ P2-3 `7ec463597`（L2 白名单）/ P2-4 `68aadb12d`（提案收口）/ P3-4 `bbab739db`+`cd7f6f30a`（遗传持久化+闲置件处置） |
| 八 | P2-2 `6bd9ec3d9`（neuacp 桥接层）/ P3-1 `8262d4d4d`（EvolutionPolicy）/ P3-3 `8db54e4d3`（评测棘轮） |
| 九 | P3-2 `4653fe1d1`（MetaEvaluator+两空转件转正） |
| 清偿 | swarm.py 接线 `ecac8ea46`（外部成员补丁→演化提案通道，禁碰件解冻后） |

### 11.2 与设计的偏离（均如实说明）

1. **独立 `signal_bus.py` 未建**：信号汇聚由 `generation_orchestrator` 的信号收集承担（功能等价、少一个模块）；跨租户聚类的 `tenantDistribution` 落在 quality/swarm 两库（P1-7）。
2. **L1.5 文本面登记为 layer=L1**：TargetRegistry 的 layer 枚举不私扩，文本四 subject 以 kind=promptTemplate + verdictSuite=suite_eval 体现分档。
3. **soul 演化定位修正**：注册表 locator 指向真实载体 soul.md（agent_core.py:1327），非 soul.json（半闲置）；P3-4 顺势退役 soul.json 结构化读写。
4. **R1 增补人工批准应用端点**：phase 1 手动档语义下"第一个被应用的优化"经 `POST /v1/governance/rsi/optimizations/apply` 人工批准达成（这正是相位设计的本义）；自动应用仍由相位门+世代门禁双闸把守。
5. **P2-4 两臂落盘格式未迁移**（爆炸面考量）：先收口读（`collectProposals` 聚合）+ RSI 臂原子写+有界归档；格式统一留待后续。
6. **NLToolSynthesizer"闲置"结论被推翻**：P3-4 核实其已经由 agent_core→chat_pipeline Step 0.5 真实消费，保留未处置。

### 11.3 实施期事故（均已恢复）

- 第七、八波首次派发的后台代理**静默未启动**（派发返回成功但代理目录从未出现）——经用户质疑发现，重派并建立"派发后存在性复核"流程；
- P1-5 提交时 `--only` 整文件收录卷入 P1-4 在途改动 → `reset --soft`+`update-index` 重建为干净提交；
- P3-4 首笔提交被并行会话 `commit --amend`+`reset` 孤儿化 → 确认工作树改动俱在后重新落库，内容零丢失。

### 11.4 验收终态

- 终验回归（evolution 全目录+guards+治理/审批/世代端点+evals+benchmark）：**2345 passed / 1 failed**——唯一失败为 `test_wiring_signatures_alive[tool_executor-signatures19]` 预存红（他会在途禁碰件，历次 A/B 均记录），**零新增失败**；
- 全自动闭环三段演练全过（零人工晋升/自动回滚/失败淘汰）；swarm 外部成员补丁接线清偿（`ecac8ea46`）；
- 闲置件 8 件处置完毕（退役或接线，零静默遗留）；双文档与 0-index 已入库。

### 11.5 移交二期（Harness^N）与后续

- swarm.py 内 P2-2 接线点已清偿；`nl_synthesizer.get/reset` 单例对零调用（P3-4 登记的相邻观察）可在二期顺手处置；
- 二期立项前置（一期验收门）已满足：P0–P3 完成 + 全自动闭环演练通过 + 世代机制运转；
- Harness^N 设计文档（2026-11-21-harness-nth-power-design.md）随本批一并入库，待拍板项见其 §6。
