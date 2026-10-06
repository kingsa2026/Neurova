# Neurova RSI 与 RSIAgent 代码级对比(2026-10-06)

> **性质声明**:本文属 INDEX.md §2.4「竞品/外部对标」——**研究参考,仅作背景,不可作为本仓设计的事实源或对齐依据**(AGENTS.md 协作红线:外部项目只作功能依赖或背景登记,不引入其设计标准)。文中任何"习得点"若要落地,一律按本仓修复教义独立立项(先红后绿),本文不构成对齐承诺。
>
> **对比对象**:AetherLabsAI/RSIAgent(Apache-2.0,shallow clone @ commit `4d7ef43`,2026-10-06 抓取)。
> **方法**:两侧独立代码细读,证据一律 `文件:行号`;Neurova 侧引用仓库相对路径,RSIAgent 侧引用其 clone 相对路径。评分为加权主观评定,依据逐条附后。
> **阅读对象**:`neurova/evolution/`(rsi、eval、closed_loop)的维护者。

---

## 0. 结论摘要

- **综合评分:Neurova 7.9 / 10,RSIAgent 6.7 / 10**(十维加权,权重与依据见 §4)。
- **一句话画像**:RSIAgent 的真实技术密度在**隔离与协议工程**(验证器 mount-namespace 物理隔离、字节级候选快照重放、8-gram 泄漏围栏、fail-closed 恢复边界),而其叙事中的"智能探索与蒸馏"层在代码里就是**持久对话 prompt + 自由格式文件树 + 单模型判决**,没有任何量化学习机制;Neurova 的技术密度在**治理与契约工程**(证据三态、五阶段部署门禁、债务反向闸、回滚留痕、收敛六态分析),短板是参数级 gain 缺端到端标尺(自认于 `neurova/evolution/rsi/eval_harness.py:5-6`)。
- **值得习得 5 点**(P1×2 + P2×3,见 §5):机械 n-gram 泄漏前置闸、端到端任务成功率标尺、验证器证据视图白名单、完成边界 fail-closed 恢复、LLM 传输诚实计时与截断修复。
- **明确不建议引入 7 点**(见 §5.7):自由文件树记忆、模型硬编码、无成本上限、单判决无仲裁等——多数恰是 Neurova 已有更强替代的方面。

---

## 1. 公平性前提:两者不是同一个问题

对比前必须先钉住问题域差异,否则评分必然失真。

| | Neurova RSI | RSIAgent |
|---|---|---|
| 问题域 | **生产常驻的自调优**:对话驱动,在线改自己的参数/技能文本/工具权重,有人类用户在环 | **离线基准环境的能力习得**:脚本驱动,在一次性 VM 沙箱里练"软件操作能力",以 benchmark 分数为产出 |
| 改什么 | 自身四族运行参数、技能文本、工具权重(不产代码) | 只改**记忆文件树**(模型权重全程冻结,代码不自称改自己) |
| 执行面 | 进程内,不执行外部代码(高风险 `pr_patch` 提案通道显式 `not_supported`,`rsi/self_improvement_proposer.py:125,957`) | Actor/Verifier 在 VM 里跑任意 python/bash,故物理隔离是必需品 |
| 判据 | 内部确定性评测 + 留出集 + 治理门禁 | OSWorld 2.0 / Agents' Last Exam 真实任务成功率 |

两者"RSI"的公共交集只有一条:**不更新权重,靠记忆与反馈闭环自我改进**。因此本文评分口径是:**每一维按"该维度对各自问题域的完成质量"评定,不为对方问题域里不存在的需求扣分**(例如不给 RSIAgent 缺"生产治理层"重罚——它没有生产影响面;也不给 Neurova 缺"VM 级物理隔离"扣分——它不执行不受信代码)。跨域可迁移的部分单独放 §5。

## 2. 总体架构对照

### 2.1 Neurova:常驻服务,三层闭环

装配:`agent_core.py:1462-1500` 每 Agent 构造 `RSIOrchestrator`,注入四大闭环系统(sleep_consolidation / emotion / experience_feedback / tool_memory,缺席用声明式占位 `_NullSystem`),并注入 `EvolutionOrchestrator` 单例。触发是**对话内后台任务 + 事件节流**:`post_chat_pipeline.py:824,3077-3085`(`iteration_cadence()`,backoff 时每 20 轮巡检,`asyncio.to_thread`)、`closed_loop.py:594,609-651`(60 秒节流,`:376-377`)。

一次迭代(`rsi/orchestrator.py:297-541` `run_iteration`):**收集反馈(:315)→ 收敛分析六态(:318,`convergence_analyzer.py:17-31`)→ 生成候选+棘轮剪枝(:321)→ 债务反向闸(:337-357)+ 部署阶段闸(:359)→ 应用前快照→应用→前后实测→回滚判定(:359-400)→ 收敛记账(:406-418)→ 规范指标(:437-452)→ 自动通道失效则升级人工提案(:457-459)→ 阶段晋升评估(:466-520)**。

三层实现(合计约 1.6 万行):
- 参数级 RSI:`neurova/evolution/rsi/`(约 4700 行);
- 文本级进化(GEPA 式闭环):`neurova/evolution/eval/`(约 3600 行);
- 工具/技能级闭环:`neurova/evolution/` 根目录(约 7900 行)。

### 2.2 RSIAgent:脚本驱动,三段式进程隔离

**不是常驻服务**。`run_osworld.py:82-95` 为每个 task 生成 3 条子进程,依次跑 `--phase phase1/phase2/phase3`;`pipeline.py:333-342` 强制 phase 目录不得回跳,`:746-748` 要求 `--execute RUN-RECURSIVE-IMPROVEMENT-PHASE1` 确认串才执行。

"三大 Agent"不是三个类,而是**三组 prompt charter + 三份角色 YAML**:`explore/charter.py`(`:242` curriculum、`:590` actor、`:1060` verifier),`config/roles/{curriculum,actor,practice_verifier}.yaml` 钉死模型与采样。Actor 的运行时本体是 `core/actor.py:19-209` 的 system prompt(EPISTEMIC_CORE E1-E6 + 10 条 code-as-policy 方法)加 `core/loop.py:546` `run_attempt` 的文本 JSON 动作循环(`{"program"/"look"/"done"}`,`actor.py:161-180`),无 function-calling。

一次 practice 迭代(`explore/practice_loop.py:1385-1775` `evolve_practice`):持久 Curriculum 在"新鲜 VM + 只读记忆副本"上发 `DECISION: PROJECT|CONVERGED|SATURATED|STALLED`(`:1397-1435`)→ Curriculum 亲手在 guest 上制作 fixtures,字节捕获重放到新 VM(`:1448-1477`)→ **全新上下文 Actor** 工作后 `STATUS: SUBMIT`(`:1482-1513`)→ **全新上下文 Verifier** 在重放候选的 VM 上给唯一一次 `VERDICT: PASS|FAIL`(`:1570-1645`)→ **同一个 Actor 上下文**进入 memory distillation + reconciliation 两个自由阶段提交记忆(`:1678-1711`)→ 循环直到 SATURATED/预算耗尽。Phase 1 并行波用 `ThreadPoolExecutor`(`phase1_wave.py:705-719`),所有分支读同一份 pre-wave 记忆快照(`:684-686`),全部完成后按 authored 顺序串行提交记忆(`:755-798`)。

## 3. 逐维度代码级对比

### 3.1 核心循环形态

**Neurova**:闭环全链有接线证据——四大闭环反馈真实收集(`integration_manager.collect_feedback_signals`)、增益只在"真被量出来"时记(`orchestrator.py:406-418`)、回滚必须留痕到 rollback_manager(`:388-395`,注释记录了"只改内存不记账导致 phase 1→2 永不可达"的修复史)。默认 `rsi_phase=0`(`security/governance_settings.py:39`)意味着默认配置下只产信号与提案、不自动改参数——这是治理选择而非断链。

**RSIAgent**:探索→验证→记忆→复用的闭环**真实跑通**(phase3 冻结记忆逐任务复用,`task.py:205-225`;冻结树 sha256 校验"评测期间记忆只进不出",`pipeline.py:587-589`)。但"探索"环节的智能完全押在 Curriculum 的持久对话自我判断上,无程序化收敛分析;进程级恢复只认"完成边界",未完成的 segment/episode 一律丢弃(`phase1_wave.py:479-488`),粒度是整个 project 而非 turn 级。

**判定**:两者闭环均真实。Neurova 胜在每一步有契约与记账;RSIAgent 胜在端到端跑通了真实基准(这是 Neurova 缺的,见 §3.10)。

### 3.2 探索与任务选择

**Neurova**:参数级用多幅度候选(朝 setpoint 5%/10%/15%/20% 步进,`orchestrator.py:788-860`)+ `RecursiveRatchetPruner` 三轮 [50,10,3] 粗/中/细筛(`recursive_ratchet_pruner.py:76`);文本级用反射式变异器 `ReflectiveMutator`(`eval/mutator.py:44`,把上一轮最低分用例的 (task, output, judge feedback) 定向喂入)+ 探索方向指令(`eval/history_ledger.py:198-215`:连续 5 轮无候选被接受时强制换未用过的变异轴;已证伪假设禁止重画,`:142-172`)。弱点:广度窄(`variants_per_round` 默认 1,`eval/config.py:30`),棘轮参数硬编码(`orchestrator.py:158-161`),可优化面仅四族参数。

**RSIAgent**:这是它**最薄的一层**。全仓 grep 不到任何 informativeness 数值、打分函数或 reward 模型——"informative"是纯 prompt 修辞(`charter.py:526-532` "Treat each project as an experiment...";`charter.py:433-443` FAIL 后优先能区分能力假设的练习)。broad→deep 切换无自动阈值,靠三重判据:Curriculum 自宣 `SATURATED`(语义契约 `charter.py:312-323`)+ 外部预算(默认 8 个 project,`phase1.py:192`)+ phase 门禁(`pipeline.py:437`)。亮点是 Curriculum **亲手在 VM 上制作 fixtures** 并字节重放(`practice_loop.py:1448-1477`)——任务生成是实打实的工程动作,不是 prompt 空转。

**判定**:Neurova 明显更强(量化、方向控制、证伪台账);RSIAgent 的任务物化(fixture 制作+重放)是唯一可借鉴的形态。

### 3.3 记忆蒸馏与复用

**Neurova**:四条蒸馏链,主链 EKB 是 **SQLite + schema**(`skills/experience_knowledge_base.py:102-127`):`success` 可空三态(NULL=未测量,`:144`)、`evidence_state` 一等列(`:212`)、`adoption_outcome` 采纳后回写(`:204-210`)、人工处置分列(`:216`);结晶走 LLM 裁决闸(`cognitive_layers/memory_layer/pattern_crystallizer.py:428`,闸开关 `governance_settings.py:42`);**复用有接线**——每轮检索注入上下文(`context/injector.py:734-747`,注释记录了"每轮写入却永不复用"断链的修复),工具权重直接参与下一轮排序(`closed_loop.py:413-455`)。

**RSIAgent**:记忆 = guest `~/.memory` 的**任意文件树,无 schema**(`dict[str, bytes]`),无向量库、无程序化去重。蒸馏是两次 LLM 自由阶段(distillation + reconciliation,`charter.py:1164-1229`,"add, revise, reorganize, delete... no required schema"),去重/冲突处理就是这个 prompt 层,唯一程序化过滤是剔除 `__pycache__`(`commit.py:113-114`)。复用注入只给**文件名+大小清单**(`practice_loop.py:393-395`;`charter.py:10-36` "you decide what to retrieve"),内容靠 Actor 自己 ls/grep/cat——记忆膨胀会直接吃上下文,无机制约束。工程亮点:tar.gz+base64 分块传输(`commit.py:24-62`)、原子安装带恢复回退(`practice_loop.py:339-382`)、每 episode journal 快照(`commit.py:139-153`)。

**判定**:Neurova 全面占优。schema 化记忆 + 证据三态 + 采纳回写,对"错误规则残留"这一 RSIAgent 自认无解的失败模式(README:134-135;reconciliation 只是 prompt 祈祷)是结构性优势。

### 3.4 验证独立性与防自我奖励

**Neurova(契约层防御)**:统一度量 `rsi/eval_harness.py:1-21`(确定性、零 LLM,用例驱动四族参数的**真实子系统代码路径**);`GateVerdict` 三态契约 `passed/failed/unevidenced` 禁止把"没证据"折叠成 0(`rsi/gate_verdict.py`);占位替身防御——`_NullSystem` 必须类级声明 `rsi_placeholder=True`、不出参数表、拒绝写入(`integration_manager.py:175-181,111-131,348-351`,防"棘轮奖励自己编辑空对象");holdout 只做验收证据永不参与判定(`eval/config.py:78-81`);bench 是 GATE 不是 fitness(`eval/runner.py:5`);泄漏审查 LeakCritic(LLM 审查,`eval/leak_critic.py`);噪声地板(`eval/config.py:63-71`);成本规则 ΔC≤β0+β1·ΔS(`:50-56`);归因核验(`eval/history_ledger.py:175-195` 检查候选声称要修的任务是否真被提升)。

**RSIAgent(物理层防御,做得非常实)**:
- Verifier 在 fresh VM + 字节重放的候选快照上工作,结束后整台 VM 丢弃(`practice_loop.py:1657-1659`);
- **藏记忆**:Verifier 的 mount namespace 里 `~/.memory` 挂成 mode=000(`verifier_runtime.py:1046-1060`),Look 路径校验拒绝私有路径(`:320-335`);
- **只给证据视图**:Verifier 起新对话(`history=[]`),charter 明文"Actor 的自我检查与结论刻意不披露"(`charter.py:1106-1110`),只给 sha256 manifest 校验过的 program/trace/look(`_build_actor_execution_evidence`,`practice_loop.py:797-881,884-952`);
- `effect_isolated` 执行边界:`unshare --mount --pid --net --ipc --uts` + 全盘只读重挂 + 逐挂载校验 + drop 全部 capabilities,**隔离不可用即 infra_fail,绝不回退非隔离执行**(`verifier_runtime.py:998-1151,345-349`);
- 防评分自污染:Verifier 结束后字节校验 live candidate 与快照一致(`practice_loop.py:1645`),Phase 2 强制 `official_evaluator_calls == 0`(`pipeline.py:474-477`);agentic 模式 `uv_accept_ok` 恒 False(`loop.py:527-543`);pass 前强制至少一次内容读取探针的 `verifier_content_guard`(`settings.py:391-395`,不满足则 pass 降级 unverified)。

**判定**:RSIAgent 9 : Neurova 8。物理隔离那套不适用于 Neurova 的问题域,但"**验证者拿不到被验证者的自我叙述,只拿得到经哈希校验的产物视图**"这一契约完全可迁移(§5.3);Neurova 的三态契约与占位防御在各自域里同样是硬通货。

### 3.5 失败处理与回滚

**Neurova**:`RSIRollbackManager`(`rsi/rollback_manager.py:41,119`)判据唯一事实源;应用前快照→有害恢复→留痕→债务结清(`orchestrator.py:380-400`);持久化 env `NEUROVA_EVOLUTION_ROLLBACK`(`start_server.py:107-114` 强制绝对路径);五阶段部署控制器,晋升需"7/7/30 天无回滚"+白名单收敛态(`rsi/deployment_controller.py:83-114`);技能级改进深拷贝+hash 落 revisions 可回退(`skill_improver.py:559-592`);债务账本未清→本轮禁止寻优(`rsi/debt_ledger.py:111`,`orchestrator.py:337-357`)。

**RSIAgent**:QEMU `savevm/loadvm` 整机事务化回滚,rollback 失败会抛错阻止评分(`env/qemu_rollback.py:252-298,1338-1346`);记忆原子换入带备份;journal 逐 episode 快照;checkpoint 在 project 边界存整树+manifest+sha256(`practice_loop.py:1234-1269`);**恢复只认完成边界**——逐 episode 校验 outcome 哈希与文本一致性、拒绝半开状态、fail-closed 不重写未信任状态(`practice_loop.py:1044-1165,1315-1331`)。但**错误规则残留记忆只有 prompt 层手段**(reconciliation)+人工回滚,无自动剪枝/遗忘/置信度淘汰。

**判定**:Neurova 9(机制+治理分层完整);RSIAgent 6.5(执行层回滚很硬,但记忆质量的安全网薄,恰是其自认三大失败模式之一)。

### 3.6 可观测性与审计

**Neurova**:7 个规范指标刻意不预置 0 以区分"缺席"与"0"(`rsi/metrics.py:68-75`);`get_status()` 全状态面(`orchestrator.py:1102-1161`,注释"只写不读的字段是断点");逐动作回执 `rsi_receipts.jsonl`(`:138-140`);文本进化逐 run 落盘 `data/agents/<id>/evolution/runs/*.json`(`eval/service.py:8`)。弱点:响应摘要与指标是**进程内存态,重启即空、无时序导出**(`rsi/result_summary.py:29-30`)。

**RSIAgent**:每 lineage 一个 `events.jsonl` 逐行 fsync、只记哈希/token 不记内容(`phase1.py:74-86`);逐 turn 工件全量落盘(`core/trace.py:28-130`);batch status.json(`run_osworld.py:169-182`);ALE 报表显式区分 `mean_available_score` vs `complete_cohort_mean_score` 与 missing/67、拒绝同一 attempt 重复评分、标明 "without best-of selection"(`benchmarks/ale/report.py:64-79,40-45,1`)。

**判定**:RSIAgent 8 : Neurova 7.5。RSIAgent 的工件化更彻底(turn 级、跨进程可审计),报表口径字段更诚实;Neurova 的指标契约设计更讲究但持久化弱。

### 3.7 工程质量与测试

**Neurova**:`tests/unit/evolution/` 94 个测试文件、约 140 个 test 函数;根因驱动——如 `test_rsi_ratchet_effectiveness.py:1-18` 文件头明列三个要杀的根因,`:71-116` 断言无效候选必须 0 分;`test_runner_holdout.py:63-65` 断言拒绝原因与基线保留;conftest 注明"私赋阶段会绕过晋升判据,把缺陷洗成绿色"。瑕疵:两套提案仓并存(`eval/service.py:102` vs `self_improvement_proposer.py:56`)、`skills/evolution_engine.py:224-242` 存在与真系统同名的模拟占位实现(`metrics*1.1` 假提升)。

**RSIAgent**:54 个测试文件、562 个 test 函数,行数 tests 14,390(全仓约 42k 行,测试占 1/3);**AST 级架构守卫**——`test_no_leakage.py:39-64` 断言 agent 包不得 import benchmark 管线、prompt 字面文件对 blocklist 逐词扫描、`task.py` 恰好调用一次 `.evaluate(`;`test_verifier_isolation.py` 36 个测试解码生成的 shell 脚本断言隔离语义。瑕疵:测试大量依赖 prompt 字面字节(改 prompt 即碎,属变更检测器);legacy 与 agentic 双轨 Verifier 长期共存(`verifier.py` 1650 行双路径);大量 A/B 实验开关以"built but never shipped ON"注释形态残留(`settings.py:214-289`);git 历史仅 1 个 squash commit,`charter.py:6` 引用的 `docs/PROMPTLOG.md` 在本仓库不存在。

**判定**:Neurova 8.5 : RSIAgent 8。测试策略两侧都是真断言;Neurova 的守卫网与提交纪律更完整,RSIAgent 的 AST 级守卫手法值得借鉴(§5.6)。

### 3.8 LLM 交互与成本控制

**Neurova**:judge_model/optimizer_model 可配置(`evolution_settings.py:32-44`);成本规则把膨胀与增益绑定(`eval/config.py:50-56`);棘轮细筛天然省评测。无 token 级预算(问题域里量级小)。

**RSIAgent**:`llm/client.py` 502 行单 OpenRouter 客户端,无 fallback 抽象;4 次线性退避(`:334-371`),错误按状态码分类可恢复性(`:230-249`);**诚实计时**:可恢复故障时无限 pause 重试,并把暂停时长从工作时钟中扣除(嵌套调用也回传,`core/loop.py:500-524,478,810-818`);**截断修复**:finish_reason=length + 括号平衡检测 → 一次双倍预算重试(`client.py:474-478`);**几乎没有成本控制**——无 token 预算、无费用上限,只有 max_iters=2000 与 wall 86400s 看门狗;模型硬编码 Actor=GLM-5.3、Verifier/Curriculum=Kimi K3(`phase1.py:161-177`,换模型要改代码)。

**判定**:Neurova 7 : RSIAgent 3.5。RSIAgent 的传输层工程细节(pause 扣钟、截断修复)是精品,但整体无成本意识 + 模型锁死。

### 3.9 配置与可移植性

**Neurova**:五键配置 + env 重定位 + API 读写(`evolution_settings.py`、`text_evolution_api.py:46-68`);SQLite/JSON 双介质;Windows 开发环境可用(本仓即证)。

**RSIAgent**:130+ 字段的 settings dataclass + YAML overlay 白名单覆盖(`settings.py:5-509`);`baseline.lock.json` 锁 release/模型/配置哈希并强校验漂移(`pipeline.py:345-387`,含 `actor.model != "z-ai/glm-5.3"` 即拒);硬依赖 Linux 宿主机 + /dev/kvm + Docker,单基准镜像 157–167 GiB;模型组合硬编码不可换。

**判定**:Neurova 7.5 : RSIAgent 4。

### 3.10 评测口径诚实度

**Neurova**:`eval_harness.py:5-6` **自认**"RSI 棘轮的 gain 来自 setpoint 梯度的信号估算——参数贴近度满分不代表行为正确,棘轮缺少整个 agent 是否变好的端到端标尺"——诚实但确实缺;失明轮 gain 不进增益史(`convergence_analyzer.py:72-89`);setpoint 回退自报 `evidenced=False`。

**RSIAgent**:报表字段诚实(§3.6),但其主结果表的口径在自家 `docs/PAPER.md:66-78` 承认:"uses 41 reported non-diagnostic RSI scores, including regressions and recorded retries... Selected runs, checkpoints, budgets, and evaluation scopes are not fully matched"——即主表是**选择性聚合的已记录 run/checkpoint,非 matched protocol 重跑**;报告工具(`report.py`)只能合并已有 result.json,无法防"挑 run"。

**判定**:Neurova 7 : RSIAgent 6。RSIAgent 有真基准覆盖(这是 Neurova 要学的方向,§5.2),但头条数字的实验纪律弱于其工程纪律。

## 4. 综合评分

### 4.1 权重依据

权重反映"对 RSI 系统长期可信度的边际贡献":验证独立性与记忆质量是 RSI 不自我欺骗的根基(各 15%);闭环完整性决定系统是否真实在改进(15%);探索、安全回滚、观测、工程质量各 10%;评测口径、可移植性、成本各 5%。

### 4.2 评分表

| # | 维度 | 权重 | Neurova | RSIAgent | 判定一句话 |
|---|------|-----|---------|----------|-----------|
| 1 | RSI 闭环完整性 | 15% | **8.0** | 7.0 | 两侧闭环都真实;Neurova 有契约记账,RSIAgent 端到端跑通真基准但恢复粒度粗 |
| 2 | 验证独立性与防自我奖励 | 15% | 8.0 | **9.0** | RSIAgent 物理隔离+证据视图做得最彻底;Neurova 三态契约+占位防御在域内同样硬 |
| 3 | 记忆蒸馏与复用 | 15% | **8.0** | 5.5 | schema+三态+采纳回写 vs 自由文件树+prompt 蒸馏,无程序化去重 |
| 4 | 探索与任务选择 | 10% | **7.0** | 5.0 | 反射变异+方向指令+证伪台账 vs 纯 prompt 自宣 SATURATED |
| 5 | 安全、回滚与失败处理 | 10% | **9.0** | 6.5 | 五阶段门禁+债务闸+留痕回滚 vs VM 回滚硬但记忆安全网薄 |
| 6 | 可观测性与审计 | 10% | 7.5 | **8.0** | RSIAgent turn 级工件+诚实报表;Neurova 指标讲究但不持久 |
| 7 | 工程质量与测试 | 10% | **8.5** | 8.0 | 两侧真断言;Neurova 守卫网完整,RSIAgent 有 AST 守卫但双轨+死配置 |
| 8 | 评测口径诚实度 | 5% | **7.0** | 6.0 | 一个自认缺端到端标尺,一个自认主表非 matched protocol |
| 9 | 可配置性与可移植性 | 5% | **7.5** | 4.0 | 模型硬编码+kvm+157GiB 镜像 vs 可配置可重定位 |
| 10 | 成本与效率控制 | 5% | **7.0** | 3.5 | 成本规则+棘轮省评测 vs 无预算无上限 |
| | **加权合计** | | **7.9** | **6.7** | |

### 4.3 敏感性说明

若按 RSIAgent 的问题域(离线能力习得)重新赋权——隔离/恢复/协议工程提到 25%+——它会反超;反之按生产自调优赋权差距拉大。**结论是"各自把自家问题域做得如何",不是谁绝对更强**。跨域真正值得搬运的东西收敛在 §5。

## 5. 值得习得点

> 落地纪律提醒:以下均为研究参考的形态启示,任何立项按本仓修复教义执行(先红后绿、净 LOC 约束、单点收口),不构成对齐承诺。

### P1-1 机械 n-gram 泄漏前置闸(零 LLM 成本,直接补 LeakCritic)

**对方做法**:`silent_audit` 对每份记忆文件做 8-gram shingle 与任务指令语料求交,命中即剔除并写 host 侧拒绝日志、**从不反馈给 Agent**;语料本身带 provenance 校验(manifest/sha256,`commit.py:196-268`);任何剔除导致整个 candidate 拒绝而非部分改写(`practice_loop.py:1696-1705`)。

**本仓现状**:`eval/leak_critic.py` 是 LLM 审查 + holdout 隔离(`eval/config.py:78-81`)。LLM 审查对高相似度机械泄漏既贵又可能漏。

**习得形态**:在 LeakCritic **之前**加一层确定性 shingle 闸(候选文本/结晶经验条目 vs 评测集任务文本求交,零 token 成本、可单测),LLM 审查只处理低相似度语义泄漏;命中处理沿用本仓"诚实暴露"教义(拒绝原因落台账),不静默。落点:`neurova/evolution/eval/leak_critic.py` 前置;`pattern_crystallizer` 的 LLM 裁决闸入口同样适用。

### P1-2 端到端任务成功率标尺(补 eval_harness 自认缺口)

**对方做法**:phase3 形态——冻结记忆 → 逐真实任务评测 → 成功率,报表显式区分 available/complete 两口径(`report.py:64-79`)。

**本仓现状**:`eval_harness.py:5-6` 自认 gain 是 setpoint 梯度估算,缺"整个 agent 是否变好"的端到端标尺;评测集三级回退里已有会话挖掘(`eval/miner.py`,`eval/service.py:133-150`)。

**习得形态**:把 miner 挖掘的真实任务集升级为参数级 RSI 的**端到端回归标尺**——每轮迭代(或抽样轮)重放固定任务子集,增益从"参数贴近度"向"任务成功率增量"校准;与现有 gain 并列呈报而非替换。落点:`neurova/evolution/rsi/eval_harness.py` 旁路新增(遵守 agent_core 尺寸棘轮,不回填)。

### P2-3 验证器证据视图白名单

**对方做法**:Verifier 只见 sha256 manifest 校验过的 program/trace/look,不见 Actor 的自我检查与结论(`practice_loop.py:797-952`;`charter.py:1106-1110`)。

**习得形态**:文本进化 judge(`eval/runner.py:45-47` 已 Protocol 化)消费的候选证据定窄契约——产物 + 执行 trace,不含候选的"自我评价"字段,防自我叙述带偏评分。落点:`neurova/evolution/eval/runner.py` 的 `_JudgeLike` 输入契约。

### P2-4 长任务完成边界恢复(fail-closed resume)

**对方做法**:`--resume-completed-boundary` 逐 episode 校验 outcome 哈希与文本一致性、拒绝半开的下一集、不重写未信任状态、校验失败整段丢弃(`practice_loop.py:1044-1165,1315-1331`)。

**习得形态**:evolution 队列(`evolution/job_queue.py:40-58` 已有 WAL+租约+幂等键)增加"已完成边界"恢复语义——崩溃后只续跑已持久闭合的边界,半开一律丢弃重做;与 `PersistedStateMixin` 的原子写(`persistence.py:23`)拼成完整恢复链。落点:`neurova/evolution/job_queue.py`。

### P2-5 LLM 传输诚实计时与截断修复

**对方做法**:infra pause 时长从工作时钟扣除(嵌套调用回传,`core/loop.py:478,500-524,810-818`);finish_reason=length + 括号平衡检测 → 一次双倍预算重试(`client.py:474-478`)。

**习得形态**:llm_router 侧两个独立小改进——(a) 看门狗/预算计时把可恢复重试的等待排除在外(诚实计量);(b) JSON 输出截断时按括号平衡检测触发一次加预算重试。落点:`neurova/core/` llm 路由层(现状盘点先行)。

### P3 记录备查(暂不动)

- **AST 级架构守卫手法**(`test_no_leakage.py:39-64`):对新增敏感面(如未来若启用代码提案通道)可用"prompt 字面 blocklist 扫描 + 关键入口恰好一次调用"的静态断言;本仓守卫网已密,手法登记备查。
- **infra 永不折算语义结论**(`practice_loop.py:1785-1797` 三分类):与 Neurova `unevidenced`/`measurement_blind` 已等价,方向一致,无需动作。

### 5.7 明确不建议引入

| 不学什么 | 为什么 |
|---|---|
| 自由文件树记忆(无 schema/去重/冲突处理) | "错误规则残留"是其自认无解失败模式;本仓 EKB 证据三态+采纳回写是结构性优势 |
| 模型硬编码 + lock 强校验锁死模型组合(`phase1.py:161-177`) | 与本仓"管理员可调"配置哲学相反 |
| 无成本上限、无 token 预算 | RSI 是长期循环,无预算护栏不可持续 |
| 单 Verifier 判决无仲裁(默认 doubt_escalation=False,`settings.py:376-388`) | 验证质量押在单上下文上;本仓 judge+holdout+归因核验已多层 |
| 主表"挑 run"式聚合(PAPER.md:66-78 自认) | 违反本仓 live-verify 与诚实呈报教义 |
| 双轨 Verifier 长期共存、A/B 死开关滞留生产配置 | 恰是修复教义第 6/7 条要收口退役的形态 |
| squash 单 commit、引用不存在的 PROMPTLOG.md | 与本仓提交纪律相反 |

## 6. 对比过程中确认的 Neurova 自身待修点(与外部无关)

探索本仓 RSI 实现时确认的独立缺陷,登记在此防静默遗留(均不因外部对比而产生):

1. `neurova/skills/evolution_engine.py:224-242` 模拟占位实现与真进化系统同名共存(假提升 `metrics*1.1`),生产零调用——修复教义第 7 条退役候选。
2. 两套提案仓并存(文本进化 `eval/service.py:102` vs RSI `rsi/self_improvement_proposer.py:56`),格式与审批 API 均不同——第 6 条单一事实源候选。
3. 探索参数硬编码(棘轮 `orchestrator.py:158-161`、backoff `post_chat_pipeline.py:88`、节流 `closed_loop.py:377`),与 evolution_settings 可调哲学不一致。
4. 观测面非持久:`rsi/result_summary.py:29-30` 与 `RSIMetrics` 均进程内存态,重启即空,无时序导出。
5. `AutoSkillImprover.apply_improvement` 走自动应用而非审批应用(`post_chat_pipeline.py:228-240`),不在 `skill_review_gate.py:7-11` 覆盖清单内——C10"改行为默认待审"存在缝隙。
6. `rsi_phase` 进程级全局、多 agent 写者胜(`orchestrator.py:552-555`,代码内明示"本单明确不做")——已知接受项,登记即可。

## 附录 A. 证据来源

- Neurova 侧:本仓工作树实测(2026-10-06),`neurova/evolution/**`、`neurova/agent_core.py`、`neurova/post_chat_pipeline.py`、`neurova/context/injector.py`、`tests/unit/evolution/**`;测试规模由 `find + wc` 实测。
- RSIAgent 侧:shallow clone @ `4d7ef43`(临时目录,用后即弃,勿入仓);行数与关键断言(8-gram 审计、模型硬编码、`eval_harness.py:5-6` 自认缺口)已由二次亲读复核。

---

## 附录 B. 自我更正与落地记录(2026-10-06,首轮升级/修复)

> 沿用 [`zcode_vs_neurova_tool_loop_comparison_2026-09-26.md`](zcode_vs_neurova_tool_loop_comparison_2026-09-26.md) 的先例:对比文档交付后按实施结果自我更正,更正不回写原文,就地留痕。

### B.1 §5 P1-1 的更正:确定性前置闸并非缺口,真实缺陷在标记契约

原文把 LeakCritic 概括为"LLM 审查"——**不准确**。实测 `leak_critic.py:120-129` 内部已有确定性第一层(标记预检必开、零 LLM),LLM 层默认关。首轮实施因此改为修真实缺陷(`leak_critic.py` 标记契约):

1. **误杀面(新发现,比原文问题更重)**:旧契约把 expected_behavior 的英数字**整词≥5** 收为标记——rubric 里的常见词(markdown/summary/result)全成"判别标记",合法候选一提即被拒为背题,"宁漏勿误杀"被反转。修法:字母文本改收 **8 词组切片**(区分性短语才成标记),与外部框架的 word-8 shingle 同判据。
2. **漏放面(原文方向正确)**:task_input 的字母文本原先**零确定性标记**,英文题干回填在默认配置(llm_review=False)下畅通。修法:task_input 与 expected_behavior 统一收 8 词组。
3. 匹配改大小写不敏感(标记 casefold 存储,review 端 casefold 比较)。

先红后绿:3 条新测试实测红(英文题干零标记漏放×2、常见词误杀×1),修后 `tests/unit/evolution/` 1412 过(唯一失败为预存环境项,A/B 自证)。钉住旧契约的 `test_build_markers_scope` 按新契约更新,理由如上。

### B.2 §5 P1-1 的"结晶入库闸"子项:**2026-10-07 已落地**

原登记的层序受阻(结晶器在 cognitive_layers 低层,评测语料无持久工件)以两个动作解除:

1. **语料工件**:`neurova/evolution/eval/eval_corpus.py`——eval service 每次物化评测集(golden/挖掘/合成)经 `build_dataset` 统一出口合并去重落盘(`data/agents/<id>/evolution/eval_corpus.json`,env `NEUROVA_EVOLUTION_EVAL_CORPUS` 重定位,有界 256 条)。
2. **注入式闸**:判定逻辑与语料留在 evolution 层(`deterministic_leak_check` 单一事实源,从 leak_critic 抽出、`review` 与结晶闸同源复用,教义第 7 条),经 `attach_ingestion_gate` 注入结晶器——cognitive_layers 零反向依赖。咽喉 `_store_candidate`(LLM 裁决后与治理直写两条路径唯一共同落点)改判返回值,拦截计数 `gate_rejected`,`confirm_pending` 账目单列 `gate_rejected`。挂载点在 post_chat 复盘通道(agent_id 在手,幂等);检查对象是会原文入库的 `sample_context`。
3. 诚实边界:无语料=无围栏(宁漏勿误杀);闸故障告警后放行;已知窗口=治理显式关闸(`crystallization_llm_gate_enabled=false`)且首评之前的直写候选不过闸。
4. 红绿实测 10 用例;evolution 套件 1447 过 0 失败(cognitive 套件 11 失败与 evolution 5 error 经 stash A/B 双向自证为预存,与本批无关)。

### B.3 §6 各项落地状态

- **§6-1 已退役**:`neurova/skills/evolution_engine.py`(模拟占位,假提升 `metrics*1.1`,单例生产零调用)按教义第 7 条退役——弱者无不可替代部分;同批删净其测试(`test_skills_evolution_engine.py` 全文件、`test_meta_skill_integration.py` 的 mock 套 Mock 用例)、`skills/__init__.py` 登记、三处对照注释、`agent_core.py:796` 零读取的 `evolution_engine` 别名。`tests/unit/skills/` 1026 过(2 失败为预存,A/B 自证);真后端启动装配零错误。
- **§6-3 已收口**:三处硬编码(棘轮 `[50,10,3]`、backoff 20 轮、节流 60s)入 `EvolutionSettings`(`rsi_ratchet_candidates`/`rsi_backoff_every_turns`/`rsi_event_throttle_seconds`),默认值与原字面量逐字一致(零行为漂移);`load_settings` 统一类型收敛(坏值回默认);三个消费点改读配置并有契约测试钉死"真被消费"(含派发层端到端用例落配置文件验证)。9 条新测试红→绿。
- **§6-5 更正为非缺陷**:`AutoSkillImprover.apply_improvement` 本身只写审计元数据(revisions/版本位);真正改模型可见行为的通道是它记入 `SkillExperienceStore` 的经验,而该臂**已被 C10 闸覆盖**(`skill_experience.py:125-127`:improver/attribution 来源闸开时强制 pending,审批面 `list_pending_experiences`/approve/reject 既有)。原文"不在闸覆盖清单里"基于不完整读取,撤回。
- **§6-2(两套提案仓)、§6-4(观测面非持久)**:未动,维持登记。

### B.4 第二轮落地记录(2026-10-06 续)

**P1-2 端到端任务成功率标尺 — 已落地**(`neurova/evolution/rsi/task_yardstick.py`,9 测试红→绿):
- 形态:把 `AdaptiveToolWeights` 滑动窗口里的**真实结局流**(逐工具 `(ts, ok)`,本就随 tool_weights.json 持久化——单一事实源,不新增数据文件)按时间归并,在候选参数下经**真实排名代码路径**(`get_effective_weight`)重放,量"结局与权重排名的对齐度"(中位秩百分位,成败对称,全并列恰 0.5)。这是 RSIAgent phase3"冻结任务集测成功率"在参数自调优域的同构物:重放流 = 冻结样本,对齐分 = 任务成功率读数。
- 诚实边界(模块文档钉明):重放评估假设平稳性;`decay_rate` 在快重放中不可观测(其遗忘带宽由 eval_harness 专用用例把守);**并列呈报不参与 gain 判定与回滚**——它是观测面不是判据。
- 装配:`_measure_performance` 读数面并列携带 `e2e`;`run_iteration` 结果新增 `e2e_gain`(任一侧未量出即 None,不折算 0,与 gain 证据门同口径)。
- 顺手修复潜伏崩溃:候选过闸但 `applied_count==0` 时 `eval_after`/返回体未初始化路径的 NameError(随本标尺同批红绿钉住)。

**§6-4 观测面持久化 — 已落地**(`result_summary.py` + bootstrap 装配,8 测试红→绿):
- 摘要随 `record_rsi_summary` 追加进 jsonl 审计流(`data/evolution/rsi_summaries.jsonl`,env `NEUROVA_EVOLUTION_RSI_SUMMARIES` 重定位);`attach_persistence` 启动时按 (agent, session) 恢复最新摘要——**重启后到下一次迭代前响应面不再为空**。
- 每轮迭代的规范指标快照追加进同一审计流(时序留痕);文件有界(attach 时 >2000 行压实到 1000);未挂载零 IO;落盘失败 soft(内存读数不受影响)。
- live-verify:真后端启动日志出现"RSI 观测面审计流已挂载",`/health` 200,零装配错误。

**P2-3 验证器证据边界 — 契约钉死**(`test_runner_evidence_boundary.py`):读码证实 judge 输入面恰为六 kwargs(task_input/expected_behavior/output/skill_text/artifact_size/max_size),执行器返回值即产物、推理无通道进评分面——本臂结构上已满足;钉死契约防未来执行器富化时无声拓宽。钉的过程中顺带验证了 eval 目录 LLM 出站闸的真实性(未注入离线变异器时被正确拦截)。

**P2-4 更正为已实现**:细读 `job_queue.py` 证实——`recover_stale` 把超时租约作业重置 `failed_retryable`(半开丢弃重做)、`attempts` 列 + `fail()` 的 max_attempts 终态(毒作业有界)、`BEGIN IMMEDIATE` 原子领取 + idempotency_key 去重。对比文档设想的"完成边界恢复"主体**全部已存在**,原文"是否有边界恢复未见"基于不完整读取,撤回。

**P2-5 更正为无消费方**:`finish_reason` 仅在响应实体与个别 adapter 透传,无截断处理;agent 侧无会被重试等待污染的预算时钟。两个习得细节(诚实计时、截断修复)**在本仓没有落地消费面**,按"不注册无消费者模块"纪律登记不实施。触发再评估条件:文本进化执行器接真 LLM 并引入墙钟预算,或引入 JSON 动作循环。

**§6-2 评估结论(登记,不执行)**:两套提案仓(text evolution `proposals.json` vs RSI `proposals/<id>.json`)的重叠在**审批生命周期壳**(pending/approve/reject/rollback),payload 与审批面本就异构(文本变体 vs manifest/action/patch 三型)。整体收口 = 统一提案生命周期契约 + 迁移两套 API + 前端配合,属多日重构且当前无消费者拉力。分阶段方案登记:①先统一状态机与审批语义的单一事实源(共享契约模块);②再迁移持久层;③最后合并 API 面。触发条件:任一侧需要新提案类型时优先走统一壳。
