# reference_af（Agent-S）vs Neurova：计算机使用与接口进化专项评测

- **日期**：2026-11-24
- **对象**：[simular-ai/Agent-S](https://github.com/simular-ai/Agent-S)（main 分支 tarball 快照，2026-11-24 拉取；Apache-2.0）
- **方法**：全量源码静态精读（Agent-S 侧 259 个 Python 文件约 5.5 万行；本仓侧按能力面对照取证），不跑对方基准、不改对方代码。评分为当日静态读数，非实测复评。
- **结论先行**：Agent-S 是**聚焦计算机使用（computer use）的研究型框架**，四代迭代（S1→S4）。其 S3 以「扁平单循环 + 行为最优 N 选择」在 OSWorld 达 72.6%（超人类线）；其 S4 以「进化式接口自生成」（岛群进化 + 外部基准适应度）成为 OSWorld V2 开源 SOTA。**总分对比：Neurova 85.0 vs Agent-S 73.0**——本仓以产品宽度、编排、记忆、安全治理取胜；Agent-S 在**感知接地、以外部基准为适应度的进化纪律、评测卫生**三处领先，是本报告最主要的借鉴来源。

---

## 1. 对象画像

| 项 | Agent-S | Neurova（本仓） |
|---|---|---|
| 定位 | 计算机使用 agent 研究框架（GUI 自动化 + 接口进化） | 通用个人 AI 助理全栈产品 |
| 规模 | 259 个 .py，约 5.5 万行 | 约 46.9 万行 .py（另有前端/移动端） |
| 代际 | S1（层级规划）→ S2/S2.5（扁平化）→ S3（单循环+BBoN）→ S4（接口进化） | 单主干持续演进 |
| 交付形态 | pip 包 `gui-agents`/`agent-s4` + macOS App + Simular 商业 API | Web UI + 后端 API + 鸿蒙/安卓端 + 渠道接入 |
| 目录要点 | `gui_agents/s1..s3`、`agent_s4/`（进化系统）、`osworld_setup/`、`scienceboard_setup/`、`app/macos` | `neurova/` 80+ 子包（agent/evolution/computer_use/skills/memory/cognitive_layers 等） |

两代主力代码分布：S3 约 3.8K 行（`gui_agents/s3/`），S4 约 1.7 万行（`agent_s4/`，含 harness/eval/vm/operators）。外围另有：`integrations/openclaw/`（把 Agent-S 包成 OpenClaw 技能）、`app/macos/`（原生 Swift/SwiftPM 桌面端，Virtualization.framework 跑 Linux VM）。

## 2. Agent S3 精读：扁平单循环 + 行为最优 N

**循环**（`gui_agents/s3/agents/worker.py:178-353`）：截图 → 每步反思（独立反思会话，三分类：偏离/正常/已完成，重点检测动作死循环，`procedural_memory.py:120-143`）→ 拼接文本缓冲与 code agent 结果 → 单次生成「上步验证→截图分析→下一步→Grounded Action 代码块」→ 两道格式闸门（`SINGLE_ACTION_FORMATTER` + `CODE_VALID_FORMATTER`，`formatters.py`）→ `eval` 执行 pyautogui 代码。无 Manager/DAG 层级（`agent_s.py:49` 自述 "no hierarchy for less inference time"）。

**接地**：规划模型只写符号调用（如 `agent.click("右上角菜单")`），ACI 方法内部调指向模型（UI-TARS 式，输出坐标正则解析）解算坐标；文本定位走 pytesseract OCR 词表 + LLM 选词 id（`grounding.py:230-344`）。**不是 Set-of-Mark 路线**。

**Code agent 通道**（`code_agent.py`）：表格计算/数据处理/批量操作强制走代码执行（20 步预算），图表/透视表强制走 GUI；**code agent 改完文件后必须用 GUI 动作重开应用核验才能 `done()`**（`procedural_memory.py:51-54`）。

**BBoN（Behavior Best-of-N）**：N 条 rollout 先由 BehaviorNarrator 把每步「before/after 截图 + 动作」转成事实清单（在 before 图画点击/移动/拖拽标记、对 after 图按动作点 4× 放大裁剪，`bbon/behavior_narrator.py:36-168`），再由 ComparativeJudge 依据硬性准则（核对计算、保持表格格式、清理现场等）从 N 条中选优（`bbon/comparative_judge.py:62-149`）。OSWorld 66% → 72.6% 的增量即来自此（`s3/README.md:21`）。属推理时扩展，不涉训练。

**上下文裁剪**：长上下文模型只删旧截图保留全部文本；小模型按轮丢弃（`worker.py:98-123`）。

**弱点**（代码实证）：`eval(code)` 裸执行模型输出（`common_utils.py:31`）；DONE/FAIL 靠子串误判（`cli_app.py:186-201`）；坐标解析 `re.findall(r"\d+")` 取前两数无重试（`grounding.py:244-246`）；反思每步固定开销；OSWorld 专属内容（sudo 密码等）硬编码进提示；S3 丢失了 S1 的跨任务知识库，记忆仅限单回合 notes。

## 3. Agent S4 精读：进化式接口自生成（本报告重点）

**核心思想**：agent 能力上限受制于人给的工具接口。S4 让一个 **Builder agent** 从任务轨迹中持续改写一个 Python 工具库（**shadow interface**），另一个 **task agent** 用该接口在全新 VM 上跑基准，得分作为该接口变体的**适应度**，再由岛群进化（锦标赛选择/交叉/变异/迁移/淘汰/再评估）驱动接口演化。

**一次 run 的生命周期**（`orchestrator.py:786-863` → `driver.py:283-304`）：
1. Bootstrap：校验 pin 的 Prime Agent runtime 与 benchmark 划分（train/val/test 与 release pin 的 SHA256 绑定 + 泄漏检查，`orchestrator.py:76-129`）；每岛克隆模板、部署种子接口、打 tag `evol/<岛>/seed`；并行评种子。
2. Driver 每步按调度器选一个算子（cadence：migration=5 / crossover=6 / elimination=10，冲突取最稀有，否则 mutation；`config/scheduler.py:28-74`），用 ProcessPoolExecutor 扇出到所有岛并行并 barrier。
3. mutation：锦标赛选父 → Builder 读父代 train 轨迹（**不含成功标签的合成任务 + 真任务轨迹**）→ 在 Landlock 沙箱内改 `shadow_interface/`（只许写该目录 + `notebook.jsonl`，`builder_sandbox.py:214-217`）→ 子代在 50 train + 25 val（每任务一台 VM）上评测 → 回写 score/val_score（`operators/mutation.py:155-469`）。
4. crossover 融合两父代；migration 两阶段跨岛迁移（原子 transit + 接收方重评）；elimination 淘汰末位（**删前整库快照**，`elimination.py:33-65`）；reevaluation 对 top-k 重复测 val 取均值。
5. SQLite 是唯一状态源（variants/eval_results/history/cost_events/dispatch_log），代码态在各岛 git tag（`evol/<岛>/if-NNN`）；max_steps/max_cost 停机。

**执行基座**：两个可插拔 harness（`harness/base.py` 注册表二选一）。prime = 钉扎外部 CLI（`prime-agent --mode json`，版本/哈希双重校验，`harness/prime/source.py:34`），S4 只做 JSONL 事件中继与进程组监督（步数上限、空闲看门狗、模型请求硬预算、`runner_state.json` 原子落盘）；opencode = 自研 supervisor 驱动 OpenCode CLI（session 续接 + 配置哈希校验）。两者共用同一份可进化的 `context_compaction.json`（种子默认 window 131072 / reserve 16384 / keep 20000 / summary 4000），由各自适配层翻译成原生压缩配置；overflow 补丁让 vLLM 类长度报错走原生 compact-and-retry。任务 agent 跑在 AWS + OSWorld DesktopEnv 的全新 VM 上（Owner 标签防孤儿实例）；episode 级超时（exit 124）仍正常计分，而 eval 基建超时按基础设施失败抛错——两级超时语义分明。任务文本经 base64 文件传递而非 argv，避免 `pkill -f` 误杀自身。

**种子接口形态**（`osworld_setup/s4/seeds/combined/`，接口进化起点）：CLI 入口 `python3 -m shadow_interface capabilities|doc|call`，helpers 自动发现；4 模块 14 个公开函数——gui（截图/指向模型调坐标/点击/按键/活动窗口）、browser（CDP 9222 标签页操作）、cli_ops（gsettings/OOXML 结构读取）、atree（AT-SPI 无障碍树/窗口列表/焦点元素），外加 `context_compaction.json` 策略文件。

**关键设计纪律**（对本仓最有价值的部分）：
- **适应度外部锚定**：选择信号默认 `val_score`（留出集），Builder 永远看不到 val 证据（`utils.py:74-152` 单一证据边界；`crossover.py:243-247` 注释明示）；resume 时校验 val 集未变（`db.py:588-610`）。
- **防奖励作弊**：合成训练任务用恒 0 假评分器并显式告知 Builder「零分不是失败、禁止优化该数字」（`prompts/synthetic_trajectories.md`；`synthetic_tasks.py:43-51`）。
- **基础设施失败 ≠ 零分**：评测产物缺失/非法/超时一律 raise，拒绝把基建故障记成任务失败（`tournament.py:67-77`、`mutation.py:383-386`）。
- **崩溃恢复协议**：dispatch log + 孤儿变体/tag 回收（`driver.py:214-269`）+ 预插入崩溃复用已 tag 子代避免重复 Builder 花费（`mutation.py:82-146`）+ migration transit 幂等。
- **接口可发现性**：task agent 用 `python3 -m shadow_interface capabilities` / `doc <name>` 自发现工具，docstring 即检索面；Builder 提示词明确要求「可发现性」（无 docstring 的工具会被 agent 略过）。
- **连上下文压缩策略也可进化**：`shadow_interface/context_compaction.json`（窗口/保留/keep-recent/摘要预算）是 Builder 可改的演进对象之一。

**弱点**：强单机假设（cwd 布局/本地 SQLite/进程池=岛数）；硬编码路径与默认 VM 密码；算子异常穿透 barrier 终止整个 run（无 per-island 容错，只能靠 resume）；25 题 binary val 区分度低、锦标赛大量随机破平；Landlock 仅 Linux。

## 4. 与本仓逐维对照与评分

评分口径：十维 × 10 分，中立 harness 视角；证据为双方当日代码读数。Neurova 侧关键事实源：`neurova/evolution/`（RSI 编排、工具基因引擎、技能封装/改进）、`neurova/computer_use/`（UIA 语义树 + SOM）、`neurova/benchmark/suite_eval.py`、`neurova/agent/`（swarm/审批链）、`neurova/skills/`。

| # | 维度 | Neurova | Agent-S | 判定要点 |
|---|---|---|---|---|
| 1 | 任务规划与执行循环 | **9.0** | 8.0 | 本仓 loop_manager/loop_gates_compiler/goal_verifier/acceptance_gate/plan_mode 链条完整；S3 扁平循环+每步反思+BBoN 简洁有效但无长程规划层 |
| 2 | 感知与接地 | 7.5 | **8.5** | Agent-S 有专用指向模型通道（UI-TARS 式）+ OCR 选词，OSWorld 实证；本仓 UIA 五级递降 + SOM 启发式扎实，但 VLM 接地模型只有 detector 协议留位未接真模型 |
| 3 | 工具与接口体系 | **9.0** | 8.0 | 本仓 tool_executor 统一管道 + MCP 双向 + skill 体系 + 沙箱，工具面远宽；S4 的 ACI 自描述（capabilities/doc）与「接口可进化」是亮点 |
| 4 | 记忆体系 | **9.0** | 5.5 | Agent-S 记忆是其最弱项：S3 仅静态程序性提示 + 单回合 notes；S1 知识库未延续；S4 仅 notebook.jsonl 进化观察。本仓 mem_core + 分层 + 睡眠整合 + 纪律准入 |
| 5 | 自我进化 | 8.0 | **9.5** | S4 = 以外部基准留出分为适应度的岛群进化 + 防作弊 + 防过拟合，**硬度**最高；本仓 evolution 包机制面更广（RSI 门链/影子验证/回滚/基因引擎/技能生命周期）但适应度多靠内部判据 |
| 6 | 多 agent 编排 | **9.0** | 4.5 | Agent-S 无多 agent 编排（S1 层级已弃，S4 仅 builder/task 两角色）；本仓 swarm/teams/rooms/审批链/neuacp 外部 agent 接入 |
| 7 | 评测与质量门 | 7.0 | **9.5** | Agent-S 接五个公共基准 + 严格二值判分 + split 泄漏检查 + SHA256 钉扎 + 基建失败≠零分；本仓 suite_eval 诚实纪律 + EvalCase 红绿 + 棘轮，但无公共 CUA 基准锚定 |
| 8 | 工程可靠性 | 8.5 | 8.5 | 平手：Agent-S 的断点续跑协议/淘汰前备份/成本封顶在研究代码中罕见；本仓 checkpoints/recovery/WAL 迁移注册表/压缩纪律属生产级 |
| 9 | 产品化与部署 | **9.0** | 5.0 | 本仓多端多渠道多租户；Agent-S 单用户研究框架 + macOS App + 商业 API |
| 10 | 安全与治理 | **9.0** | 6.0 | Agent-S 有 Landlock 沙箱与网络守卫，但 `eval()` 裸执行 + sudo 密码进提示是硬伤；本仓鉴权/租户隔离/审批/车道互斥/审计 |
| | **合计** | **85.0** | **73.0** | |

## 5. 借鉴清单

**P0（建议尽快吸收）**
1. **进化适应度外部锚定**：把本仓已有评测核心（如 `neurova/benchmark/recall_quality.py` / D7 调参评测）接为 evolution/RSI 的适应度来源，进化决策以留出集真实得分为准，替代/校准内部自评判据。落点：`neurova/evolution/eval/fitness.py`、`rsi/task_yardstick.py`。
2. **「基础设施失败 ≠ 零分」纪律**：本仓评测/进化链路中，评测器异常、超时、产物缺失应显式抛错并标记 `infra_failure`，不计入任务失败集合。落点：`neurova/benchmark/suite_eval.py` 的失败分类、`evolution/eval/runner.py`。
3. **进化任务断点续跑协议**：dispatch 日志 + 孤儿产物回收 + 幂等重放（对照 S4 `driver.py:214-269`、`mutation.py:82-146`）。落点：`neurova/evolution/rsi/generation_orchestrator.py`、`job_queue.py`。

**P1**
4. **多候选行为归一化选择（BBoN 思路）**：swarm 多候选合并（`agent/candidate_merge.py`）在裁决前可加「逐步事实化 caption + 比较裁决」层，降低自由文本裁决的漂移。
5. **代码执行车道 + 强制 GUI 核验**：computer_use 对数据类任务开放受控代码通道（经沙箱），并强制「代码改完必须 UIA/SOM 复核才可 done」。落点：`neurova/computer_use/actions.py`、`guardrail.py`。
6. **上下文分级裁剪**：S6 压缩纪律补充「图像先于文本丢弃」与「长上下文模型只裁旧图」分档。落点：context 压缩模块。
7. **工具可发现性自检**：工具描述按「agent 用 capabilities/doc 方式检索」标准做静态自检（docstring/签名完整性），纳入 CI 判据单测。

**P2**
8. **无标签合成轨迹防作弊**：进化/训练素材可引入「无验证器合成任务 + 显式告知不计分」的素材池，降低对带标签数据的依赖与过拟合。
9. **淘汰/清理前快照**：本仓进化库清理与技能退役前做 SQLite 快照留底（对照 `elimination.py:33-65`）。

**不学清单**：`eval()` 裸执行模型输出；DONE/FAIL 子串误判；坐标正则取数无重试；sudo 密码硬编码进提示词；为降时延放弃跨任务记忆。

## 6. 局限与复核注记

- 本报告为**静态代码读数**，未复跑 OSWorld/WAA 等基准；Agent-S 的公开分数（OSWorld 72.6%、OSWorld V2 21.3%）引自其 README 与论文，未独立验证。
- 评分反映「框架能力面」而非「同一任务同一模型下的实测胜负」；Agent-S 在其专注域（桌面/浏览器任务自动化）的单点强度高于本仓，本仓优势在域外。
- 对象快照为 2026-11-24 main 分支；S4 仍在活跃演进，引用其结论时建议先核对上游版本。
- 本仓侧证据均为当日实测读数（目录/文件行数与头部注释），未发现与既往台账冲突之处。
