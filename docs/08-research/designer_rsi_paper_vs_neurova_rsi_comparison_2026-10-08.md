# Neurova RSI 与 Designer-RSI 论文对照（2026-10-08）

> **性质声明**：本文属研究参考——论文只作**背景与形态启示，不可作为本仓设计的事实源或对齐依据**
> （AGENTS.md 协作红线：外部产出只作功能依赖或背景登记，不引入其设计标准，不搬运其命名与结构）。
> 文中任何"习得点"若要落地，一律按本仓修复教义独立立项（先红后绿、净 LOC 约束、单点收口），
> 本文**不构成对齐承诺**。所有关于本仓的断言均以工作树实测的 `文件:行号` 为证，与论文表述分列。
>
> **对照对象**：*Designer-RSI: Evolving Procedural Memory from User Traffic for Agentic Graphic Design*，
> arXiv:2609.22086（cs.AI / cs.CV，2026-09-18 提交，9 页 7 图；署名 Hongyang Du、Lan Yan、
> Christian Flores、Asim Kadav；机构未见于 arXiv 摘要页，二手报道称 Adobe 与布朗大学，未证实）。
> **阅读对象**：`neurova/evolution/`（rsi、eval、closed_loop）、`neurova/skills/`、
> `neurova/cognitive_layers/memory_layer/` 的维护者。
> **前作**：[`rsiagent_vs_neurova_rsi_comparison_2026-10-06.md`](rsiagent_vs_neurova_rsi_comparison_2026-10-06.md)
> 的方法（问题域先钉、逐维取证、习得点分 P 级、附"明确不学"清单）本文沿用。

---

## 0. 结论摘要

- **一句话画像**：论文的真实贡献是**在无人工标签下，把"例级成对回放闸 + 双向维护"跑成正**——
  冻结模型只读不动，全部改进落在外部自然语言技能库上，靠"新旧同题对跑、不许既有胜例丢失"做准入。
  本仓 RSI 的技术密度在**治理与证据契约**（三态判据、债务反向闸、五阶段门禁、人工评审主防御），
  短板有两条：**技能准入是集级均值比较**（`eval/runner.py:578`），以及**文本臂从未跑过真实 agent 轨迹**
  （默认执行器把技能文本原样回显 `eval/runner.py:146-154`，生产装配的是单轮 LLM 模拟体
  `eval/service.py:58-89`）。
- **最值得学的 3 条**（P1，落点见 §4，前置条件态见 §8）：① 例级"不许既有用例退化"准入闸——
  本仓缺的是**留出侧的例级读数**（`runner.py:553` 的 `holdout_after` 走 `_evaluate_avg`，
  per-task 分数被当场丢弃），不是缺一套 A/B；② 深化通道要引入**成功/失败对照**
  （本仓两条改写臂都只喂失败样本，论文消融给出二者合取才超可加的数字论据）；
  ③ 把**真 agent 轨迹**接进双臂核验面（当前审批人看到的对照跑的是单轮 LLM 模拟体）。
- **本轮实探对本报告首轮判断的三处更正记于附录 B**（`ab_library` 语义错配、
  `make_agent_ab_executor` 签名不可注入、judge 不可用洞已闭环）——阅读 §3.4/§3.9 时以更正后表述为准。
- **明确不学 7 条**（§5）：无人监督全自动、单一 VLM 评分器作唯一奖励源、纯词面检索、
  库容量自然增长无预算、技能=文档文件而非 schema 化记录、以胜率代替留出不退化证据、模型/工具集硬绑定。
- **对照过程复核出的本仓独立待修 10 条**（§6，均不因论文而产生；其中第 4、5 条已随前置 3 落地闭环，
  第 9、10 条是前置 1 落地时新登记的"写了没人读"，见 §6-9/§6-10）。
  未闭环项里最刺眼的一条是**死旋钮**：RSI 参数表里的 `context.experience_knowledge`
  在仓内没有任何消费点，棘轮在调一个没人读的预算格。
- **"能不能撤掉人在环"这个问题已落成 §8 四条前置条件**。截至 2026-10-08 落地后：**前置 1、3、4 已满足，
  仅前置 2 未满足**。剩下的那一条正是**判据执行面的真实性**（真 agent 轨迹），无一条在治理层；
  核实后的对照结论变化记于 §9（§3.4 差距上修、§3.9 论据撤回、剩余唯一结构性差距是执行面真实性）。

---

## 1. 论文机制（事实层，只记可核实的）

论文要解决的问题：专业图形设计是长程 agentic 任务，产出**没有可靠的程序化 oracle**。
方案是持续适配框架——冻结的前沿模型经 230+ 工具操作专业设计软件，**权重全程不动**，
外部程序性记忆（自然语言技能库）从经验中累积并修订可复用的设计流程。

| 机制 | 论文表述（要点） | 出处 |
|---|---|---|
| 记忆载体 | "A skill is a single Markdown file (SKILL.md) with YAML front matter"；按 `app_mode` 分三个子库：raster / vector / page_layout | App. C.1 |
| 运行时 | "skill retrieval may inject a playbook and reduced tool set into the model context" | §2 |
| 拓宽 | 从**反复出现但未覆盖**的子任务铸造新技能；缺口登记后需复发若干次才成草案 | §3.1 |
| 深化 | "hardening skills that already exist"，对本技能自己的成功与失败执行做对照；按错误频次选靶 | §3.2 |
| 失败计票 | "a trajectory scoring below the success threshold counts as a failure against every skill it retrieved"（阈值 τ=0.6） | §3.2 |
| 改写升级 | "when repeated targeted rewrites of the same skill have failed the gate, it escalates to a major rewrite of the whole skill" | §3.2 |
| 准入闸 | 采样触发该技能的 prompt，每题生成**多个上下文**（各带不同检索资产与上游状态），新旧技能条件**成对判、顺序随机**；准入条件 `(∄ prompt lost) ∧ (∃ prompt won)` | §3.3 |
| 学习约束 | "with no weight updates and no human labels" | 摘要 / §4 |

实验规模与结果（论文自述数字，未复核）：5 轮，1406 条真实用户 brief、1869 条自动评分轨迹；
库从 76 条文档派生技能长到 139 条，其间剔除 66 条（合并/弃用）。
GenEval2 执行成功率 Claude-Sonnet-4 从 **72.7% → 99.3%**（生成质量 +11.99）；
四个专业设计基准上对"无技能 agent"的胜率 61.8%（Sonnet-4）/ 67.6%（Opus-4.6）。
消融（Table 3）：基线完成度 69.08；仅冷启动 76 条 68.62；仅深化 69.02（胜 48.6）；
仅拓宽 139 条 69.79（胜 49.4）；**拓宽+深化 74.04（胜 58.5，p=0.025）**——论文称二者"超可加"。

论文自承的局限：语言指令难以压过模型固化默认；空间精度受感知瓶颈与代理验证限制；
长指令在连续步骤上衰减；**准入闸是局部的，抽样用例上的稳定不等于全局鲁棒**。
二手报道另记三条：99.3% 说明执行更稳、不等于设计判断完美；偶然成功被总结成通用规则会让错误重复；
技能库增长带来的检索成本——条目越多并不必然更好。

---

## 2. 公平性前提：两者不是同一个问题

| | Neurova RSI | Designer-RSI |
|---|---|---|
| 问题域 | **生产常驻 agent 的自调优**：在线改运行参数、技能文本、工具权重，有真实用户在环 | **设计任务上的外部记忆持续适配**：批量简报离线迭代，模型与工具都不动，只改技能文档 |
| 改什么 | 五族参数（`rsi/integration_manager.py:33-67`）+ 技能正文 + 工具权重 | 只改 `SKILL.md` 文件树 |
| 反馈源 | **服务端票据 > 本轮客观回执 > 自述/关键词**（分层，`evolution/objective_evidence.py`），三态可空 | 单一多模态 grader 的标量分（阈值 τ=0.6），无人工标签 |
| 执行面 | 进程内，不执行外部代码（高风险 `pr_patch` 通道显式 `not_supported`） | 真软件工具链（230+），产出图像工件 |
| 判据形态 | 确定性评测集 + 留出/真留出双集 + 治理门禁（集级均值） | **例级成对回放**（新旧同上下文对跑） |
| 自动化程度 | 默认 `rsi_phase=0`、文本进化默认关、C10 评审闸默认开——**人工批准是主防御** | 无人监督，只有一道统计过滤器 |

公共交集只有一条：**不更新权重，靠外部记忆与反馈闭环自我改进。**
因此下面的对照**不比较谁的分数高**（问题域不同、口径不可通约），只比"同一类机制在两侧分别怎么实装、
哪一侧的判据更咬合"。跨域可迁移的部分收敛在 §4。

---

## 3. 逐维度对照

### 3.1 程序性记忆的载体与 schema

**论文**：一条技能 = 一个 `SKILL.md`（YAML 头 + 自然语言正文），按 `app_mode` 分三个子库。
形态上"介于原子命令与完整执行链之间"。无 schema 校验、无证据字段。

**本仓**：三套载体并存，且都比论文多了质量轴——
① 技能定义是 dataclass `Skill` 序列化的 per-skill `manifest.json`
（字段 `id/name/version/description/author/source/enabled/metadata/config/created_at/updated_at/permissions`，
`neurova/skills/models.py:132-149`）；② 经验行是 SQLite `experience_records`，四条正交质量轴
（`success` 三态、`evidence_state`、`adoption_outcome`、`operator_disposition`，另加逐字可核
`verifiability_state`，`skills/experience_knowledge_base.py:60-77`）；③ 结晶模式是
`UnifiedMemoryNode(MemoryType.PATTERN)`，正文一行中文句子 + metadata（`pattern_crystallizer.py:365-385`），
模式键由最多 8 个去停用词关键词拼成（`:612-633`）。

**判定**：schema 化与证据轴本仓明显更强——论文自承的"偶然成功被固化成通用规则"这一失败模式，
本仓有结构性解药（票据分级 + 人工处置分列 + 采纳回写）。但对照暴露出一个本仓自身的**形状不咬合**：
结晶的 LLM 裁决闸要求"可复用的结晶只承载『适用条件 + 核心过程 + 常见失败模式』"
（`pattern_crystallizer.py:475-485`），**而产物本身没有承载这三段的字段**——只有一行
"模式: '关键词串' 类任务用 X 成功率 NN%"。闸的判据与产物的 schema 不咬合，闸只能判"这条像不像规律"，
判不了"这条有没有写成可执行流程"。这是论文形态（每条技能都是流程文档）反过来照出的我方缺口，见 §4 P2-E。

### 3.2 从流量到技能的触发阈值

**论文**：未覆盖子任务先进缺口登记，**复发到一定次数**才由 LLM 合成为草案；草案过闸才入活跃库。

**本仓**：阈值这一族比论文更密，且已收进 RSI 可调参数表——
`min_observations=3` / `min_success_rate=0.6`（`pattern_crystallizer.py:107-108`）、
`pattern_min_support=2`（`pattern_miner.py:48`）、
`AutoSkillBuilder` 是**三条件合取**：出现次数 ≥3、成功率 ≥0.7、**独立成功源 ≥3**
（`skill_encapsulation.py:140-148, 320-343`，第三条注释点名病灶"同一任务反复跑出的成功会自我强化"）。

**判定**：本仓更强，且"独立证据源"这一轴是论文没有的。缺口侧同样有对应物：
`agent/capability_gap.py` 的三值缺口（附件读不出 / 连续工具失败 ≥2 / 目录检索零命中），
投递点三处真实接线（`chat_pipeline.py:1595-1597`、`tool_executor.py:5871-5887`、
`context/tool_search.py:381-387`），且**不只是观测**——缺口直接驱动自主合成
（`chat_pipeline.py:1219-1252` → `NLToolSynthesizer` → 字母表闸 + 置信闸 + 注入扫描 → 注册）。
差异在射程：本仓合成的是**已注册原语的新编排**，不是新能力；论文也不造原语。这一维基本平手。

### 3.3 双向维护：拓宽与深化

**论文**：两条臂并列，且用消融证明**二者合取才超可加**（单独 49.4% / 48.6%，合取 58.5%）。
深化臂的输入是"同一技能自己的成功轨迹与失败轨迹的对照集"，输出是**定向小节编辑**，
反复失败才升级为整篇重写。

**本仓**：拓宽臂有三条且都真接线（遗传臂 `post_chat_pipeline.py:2192-2255`、
封装臂 `creation_governance.py:287-292`、NL 合成臂 `chat_pipeline.py:1252`）。
**深化臂只看失败**，两处：
- `AutoSkillImprover._analyze_failure_pattern` 只筛 `not r.success` 的记录，按错误消息关键词分桶，
  修复建议是**查字典**（`"timeout" → "增加超时时间或优化执行路径"`，`skill_improver.py:301-359`）；
  另有 `failure_threshold=0.3` 声明后全文件无读取（`:163, :174`）。
- 文本进化的 `ReflectiveMutator` 每轮取评分最低的 3 条失败用例喂 prompt，
  **成功样本从不进 prompt**（`runner.py:30, 421-429`；`mutator.py:89-107`）。成功面的唯一回流是台账里
  "已生效（勿做无谓回退）"的文本假设（`history_ledger.py:163-166`），不是任务-输出对。

**判定**：这是本仓的实质缺口，也是论文消融数字最直接的用处——只补失败侧、不与成功侧对照，
改写容易把"当初为什么成"的前置条件删掉。见 §4 P1-B。

### 3.4 变更准入闸（差异最大、可迁移度最高）

**论文**：matched replay gate 做的是**例级成对比较**——同一 prompt 生成多个上下文
（各带不同检索资产与上游状态），新旧技能条件在同一上下文里对跑、顺序随机，
准入条件 `(∄ prompt lost) ∧ (∃ prompt won)`：一条历史胜例都不许丢，且至少赢一条。

**本仓**：主判据是**集级均值**。留出回退看的是 `holdout_after <= holdout_before + accept_threshold + ε`
（`runner.py:578`），bench 回归门看聚合 gain 对容差（`:639-641`）。
**例级退化不拦**：`unpredicted_regressions`（预测集之外却掉分的任务）只入账、
只渲染归因命中率，"归因只进证据面，不改 accept/reject 判据"（`history_ledger.py:181-194`）。
即"3 条用例涨、2 条既有用例跌"，均值过阈值即可部署。
逐例成对只存在于两条**旁路**：`service.ab_compare` 的 `per_task` 双臂分数（`service.py:378-392`，
注释明写"只读评测——不产提案、不改技能、不入台账"）与 `attribution_hit_rate`。

更靠根因的一处（2026-10-08 实探补正）：**runner 的留出判据根本没有例级数据面**。
`runner.py:553` 的 `holdout_after` 走 `_evaluate_avg`，per-task 分数被当场丢弃；
带明细的 `_evaluate` 只用在 tune 集（`:478, 543`），而 tune 侧的逐例分数只喂归因证据面。
即"不许既有用例退化"这道门在本仓**不是缺一次比较，是缺那份读数**。
旁证：`service.ab_compare` 复用的正是 `runner._evaluate` 并产出 `per_task` 双臂分数
（`service.py:378-392`）——同一条评测路径出明细的先例已在仓内，禁止另写第二套打分。

另有一处**易踩的错配**（本轮实探纠正本报告首轮判断）：`eval/ab_library.py` 的 `run_cold_warm_ab`
虽然也输出 `fixed` / `broken` 双矩阵（`:172-173`）、纪律里也写"warm 退化不得被聚合数字吞掉"（`:10-15`），
但它的双臂语义是 **cold/warm = 技能库开与关**（唯一开关 `skills_enabled`，`:146`），
而 runner 准入闸要的是 **baseline/candidate = 旧正文与新正文**。两者不是同一件事，
把 `ab_library` 接进 runner 判定链是**错配接线**。`ab_library` 的真实归属是 §4 P1-C 的
真轨迹对照面；它在 `neurova/` 内零引用（只有 `tests/unit/evolution/test_skill_library_ab_p2_4.py`、
`tests/unit/skills/test_recall_semantic_ab_wave_e.py`、`tests/unit/skills/test_discover_seeds_wave_f.py` 消费），
计划文档 `docs/04-plans/2026-10-01-自我进化严谨性升级RRSI对齐实施方案.md:564` 已把它记成
"P1-7b 偏差：全删需迁移两个套件与协调路由，另立清理项"。

**判定**：本仓缺两件事——**留出侧的例级读数**（判据集上根本没有 per-task 分数）与**基于它的准入门**。
落点因此是"把 holdout 评测改走同一条 `_evaluate` 路径拿明细，再加门"，不是"找一套现成 A/B 来接"。
这是 §8 前置条件第 1 条，也是本报告最高优先级项（§4 P1-A）。

### 3.5 检索失败与信用分配

**论文**："低于阈值的轨迹算作对**它检索到的每一条技能**的失败"——粗，但确实是回写型信用。

**本仓**：闭环存在且比论文细。检索侧登记本轮注入的 EKB 条目 id
（`chat_pipeline.py:2084-2086`），回合末按客观结果回写 `adoption_outcome` 并递增 `injected_count`
（`post_chat_pipeline.py:1811-1815` → `experience_knowledge_base.py:473-509`），
下一轮检索时采纳证据直接进排序罚分（`:772-790`，success +0.15 / failure −0.25 /
unevidenced +0.03 / 无票 0.03 / 逐字不可核 −0.30 / 人工 demoted −0.45 / suppressed 出局）。

**判定**：本仓更强（三态、正交轴、降权不剔除）。缺口在两处：**注入的三条经验拿同一张票**
（一条好经验会因同轮另两条而挨打，论文同病，但本仓有 `injected_count` 可以做分离计数而没做）；
`skill_experience.usage_stats` 里 `times_presented` **声明了但无生产写入方**
（`skill_experience.py:8, 85, 275, 288`——只有 `times_used/positive/negative` 被 `record_usage` 累加），
即"呈现过但没被用"这一格是空的，而这正是论文"检索到即计票"想要的那一维。

### 3.6 检索算法与注入预算

**论文**：token overlap 词面打分，评测配置注入 k=3，并可在检索时**裁剪工具目录**；
按 `app_mode` 分库以压检索成本。

**本仓**：同样没有向量检索——EKB 是 CJK 2-gram + 拉丁分词的词面重叠（权重 0.6）加话题全等
（权重 0.3），相关性门槛 0.15（`experience_knowledge_base.py:115-140, 751-766`）；
结晶走 SQLite FTS5(BM25) + LIKE 回退并按 `temperature` 排序（`cognitive_storage_engine.py:454-523`）；
每轮注入条数：记忆 10、结晶 3、EKB 3（`chat_pipeline.py:1738-1754, 1961-1966, 2019-2024`）。

**判定**：检索形态基本等价（都是词面），本仓在条数上更克制。但对照暴露一条本仓的**断点**：
`TokenBudget.experience_knowledge = 1500`（`context/models.py:56`）在 injector 里**没有任何消费点**——
注入器实际只读 `max_total`(`:240, 395`)、`system_prompt`(`:278, 293`)、`memories`(`:586`)、
`conversation_history`(`:816`)、`reflection_log`(`:312`)；经验档只受条数 3 约束（`:725, 773`）。
而这一格已被列进 RSI 可优化参数表并给了 setpoint 与区间
（`rsi/integration_manager.py:65`、`rsi/system_performance.py:43`、`rsi/integration_manager.py:303`）——
**棘轮在优化一个没人读的旋钮**，与工单 018 修过的"棘轮奖励自己编辑空对象"同形（§6-1）。
另：论文的"检索时裁剪工具目录"本仓有相邻件（`context/tool_search.py` 的检索与
`tool_layers/capability_graph.py` 的控制工具名单）但**没有"按技能条件缩窄工具面"这条通道**。

### 3.7 人在环 vs 无人监督

**论文**：no human labels，唯一安全网是一道统计过滤器（缺净增益证据的更新被拦）。
**本仓**：人工评审是**主 gate**——C10 评审闸默认开（`skill_review_gate.py:29-35`，覆盖自动封装 /
遗传与合成注册 / 自动化来源经验三条臂）、文本进化总开关默认关且必须显式 opt-in
（`eval/config.py:95-112`，"属'改行为'的产物"）、提案四态需非空审批人
（`proposal_lifecycle.py` 的 `require_approver`）、`rsi_phase=0` 默认只产信号不自动改参数。

**判定**：**这一维不学**（§5）。但论文是一枚有用的反证：它说明"无人监督 + 例级准入"在批式离线迭代里
可以跑正。本仓因此暴露一个从未被测过的问题：**默认配置下 RSI 与文本臂实际不产生任何自改**，
"写入→读取→反馈→再写入"的闭环在默认部署里是半通状态（信号有、动作无）。
这不是缺陷，是治理选择，但它意味着本仓的进化判据强度**没有真轨迹上的经验证据**。列为待拍板 Q3（§7）。

### 3.8 参数级自调优（论文没有，本仓独有）

论文的改进全部落在文档层；本仓的 RSI 主干是**参数棘轮**：
反馈收集 → 收敛六态分析 → 朝 setpoint 步进的多幅度候选 + 粗/中/细三轮剪枝
（`rsi/recursive_ratchet_pruner.py`，`[50,10,3]` 已入配置）→ 负债反向闸 + 部署阶段闸 →
快照/应用/前后实测 → 有害回滚并留痕 → 规范指标供值 → 自动通道失效则升级人工提案 →
阶段晋升评估并落盘 `rsi_phase`（`rsi/orchestrator.py:342-596`）。
`task_yardstick.py` 另有一条重放历史工具真实结局流的 e2e 并列标尺（`:34-89`，明写"并列呈报，
不参与 gain 判定与回滚"）。

**判定**：论文无可比物。反向可学的只有一件记账小事：论文把"5 轮 / 1406 briefs / 1869 轨迹 /
76→139 条 / 剔除 66 条"作为**库容量-轮次曲线**显式记进摘要，本仓 `rsi_summaries.jsonl` 有每轮快照，
但没有"库规模 × 命中率 × 剔除数"这一族时序读数（§4 P2-F）。

### 3.9 评测口径诚实度

**论文**：头条是 GenEval2 的 **execution success**（72.7%→99.3%），不是设计质量；
质量维度是 +11.99 分与胜率。自承准入闸是局部的、抽样稳定不等于全局鲁棒。
**本仓**：`eval_harness.py:5-6` 自认参数级 gain 是 setpoint 梯度估算、缺端到端标尺（已由
`task_yardstick.py` 补一条并列读数）；更硬的一条诚实边界在模块头自己写着——
文本臂 runner 的默认执行器是"把技能文本作为输出回显"，"真实接线方应注入一个真正跑 agent 的执行器"
（`runner.py:146-154`），生产装配的 `SimulatedAgent` 也只是把技能当 system prompt 单轮调 LLM
（`service.py:58-89`）。**即本仓的留出分从未与真实 agent 轨迹同过一次域**。

**判定**：两侧的头条数字都不能直译成用户价值，但病灶不同——论文是"局部准入 vs 全局鲁棒"，
本仓是"判据跑在模拟执行面上"。真执行器包装确实已存在（`ab_library.py:117-139` 的
`make_agent_ab_executor` 真跑 `agent.process_message`，cold 臂用 turn 级 `skills_off` 让
tool schema 与技能目录同时缺席——这一手比论文的对照更干净），**但它的签名不收 `skill_text`**
（`(task_input, *, skills_enabled, seed)`），注不进 runner / `ab_compare` 所需的
`(skill_text, task_input)` 通道。所以 §4 P1-C 是"要新写一层包装"，不是"接一下就有"。

---

## 4. 值得习得点

> 落地纪律：以下是**形态启示**，不是实现搬运；本仓命名一律用自有词汇，
> 不引入论文的标识符命名。任何一条立项都按修复教义走（先红后绿、复核实状、单点收口、净 LOC 逐条列去向）。

### P1-A 例级成对回放准入闸（先补留出侧的例级读数）

- **对方形态**：新旧同上下文成对判、顺序随机，`(∄ lost) ∧ (∃ won)` 才准入（§3.3）。
- **本仓现状**：集级均值放行，例级退化只入账不拦（`runner.py:578`；`history_ledger.py:181-194`）；
  且**判据集上没有例级读数**——`runner.py:553` 用 `_evaluate_avg` 取 `holdout_after`，
  per-task 分数当场丢弃，明细只在 tune 集存在（`:478, 543`）。
- **习得动作（两步，次序固定）**：
  ① 把 holdout 侧的两次评测改走**同一条 `_evaluate` 路径**取明细（`service.ab_compare:378-379`
  已是此形态的先例），`_evaluate_avg` 若有其他消费方则随之收口，不留两套打分（教义第 6 条）；
  ② 在判定链 `runner.py:568-644` 中**紧随"留出回退"那一道之后**新增一道**例级不退化门**
  （与既有诸门同形态：拒绝即入账、`deployed_text` 复位基线），消费 ①新拿到的两侧 per-task 分数。
  **不动 `ab_library`**（它是 cold/warm 语义，与本题无关，其死码状态单独在 §6-2 处置）。
  判据三态沿用 `GateVerdict`：单例判分失败（`_score_example` 的 `failed=True` 那一路）
  不得折叠成"没丢"，要落 `unevidenced`。
- **默认值（已拍板，见 §7-Q1）**：默认开 + 有界容忍，容忍度 N 入 `EvolutionSettings` 单源
  （与本仓 `bench_tolerance` / `noise_band_delta` 同族），不新造布尔开关。
- **代价与风险**：候选通过率显著下降（均值放行 → 例级否决）；台账里"涨 3 跌 2"类历史候选
  将不可复现地被判拒，属预期行为不是回归。噪声放大风险：`noise_repeats` 默认 0（不自动校准），
  判分抖动会直接转成拒绝——落该门时应同时给出"先校准噪声带再启用"的操作提示。
- **红灯设想**：注入脚本化 judge/executor，构造"均值涨、1 条既有用例跌"的双臂输入，
  断言当前 runner 判 accept（红），门上线后判 `case_regression` 且 `deployed_text` 复位基线（绿）。

### P1-B 深化通道引入成功侧对照

- **对方形态**：改写输入是"该技能自己的成功与失败执行对照集"；定向小节编辑反复失败才整篇重写。
- **本仓现状**：两条改写臂都只看失败（`skill_improver.py:301-359` 按错误关键词查字典；
  `runner.py:421-429` + `mutator.py:89-107` 只喂最差 3 条）。
- **习得动作**：变异器 prompt 增加"同目标的成功轨迹"段（数据源现成——EKB 里 `success=1 且
  evidence_state=evidenced` 的行 + `tool_sequence`），让"为什么成"进入改写约束面；
  与已有的 `attribution_hit_rate` 拼成可证伪回路（候选声称修 A 类失败，则 A 必须涨且
  成功面不得跌）。顺手处置 `failure_threshold` 这个没人读的声明（§6-7）。
- **代价**：每轮多一段 prompt 的 token；不改判据，只改候选质量分布，风险低。

### P1-C 真 agent 轨迹进核验面（需新写一层包装，不是接现成的）

- **对方形态**：Solver 真跑 230+ 工具，grader 判真工件。
- **本仓现状**：`ab_compare` 的执行器默认 `SimulatedAgent`（`service.py:374`），
  `POST /skills/{agent_id}/ab` 端点调用时**不传 `agent`**（`text_evolution_api.py:253-256`），
  所以审批人看到的"双臂对照"跑的是单轮 LLM 模拟。现成的真执行器包装
  `ab_library.make_agent_ab_executor`（`:117-139`）签名是 `(task_input, *, skills_enabled, seed)`，
  **不收 `skill_text`**，与 runner / `ab_compare` 所需的 `(skill_text, task_input)` 通道不兼容。
- **习得动作**：新增一个"以给定正文为指令、真跑 `agent.process_message`"的执行器包装，
  作为 ab 端点的默认执行面（`ab_compare` 的 `agent` 形参已可注入，`service.py:353`，
  无需改签名）；包装归属与泄漏红线沿用 `ab_library` 既有纪律
  （`expected/verifier` 不得进执行面，`ab_library.py:10-15`）。
  真轨迹与 cold/warm 两语义**各自单点**，不合并成一个模块（教义第 6 条的反向要求：
  同一函数承担两种对照会各判各的，正确做法是分两个入口共一条评测路径）。
- **代价**：单次对照的 LLM 用量与墙钟数量级上升（真 agent 多轮 + 工具执行），
  须同时给预算边界与用例数上限；`ab_library` 的既有待办（§6-2）与本项分开处置，不互相搭车。
- **是否进每轮自动评测**：见 §7-Q2（本轮未拍板）。
- **红灯设想**：断言当前 ab 端点走模拟执行器（红），接线后断言 executor 为真 Agent 包装
  且 `expected` 未经由参数面进入执行器（绿）。

### P2-D 经验档预算收口（本仓独立待修，论文侧照出）

`context.experience_knowledge` 只有两个合法出口：**给 injector 接上真实消费点**，
或**从 RSI 参数表退役**（连同 setpoint 与区间，教义第 6 条"发现第二份定义时收口"）。
论文"条目越多并不必然越好"的检索成本论，把这条从"洁癖"升格为"有外部论据的实际问题"。
推荐后者先行（本仓经验档实际只受条数约束，接预算点等于新增行为面）。

### P2-E 程序性记忆的正文形状合一

三套载体（manifest 技能正文 / EKB 行 / 结晶节点句子）里，只有技能正文是"流程文档"。
把结晶产出物的字段补齐到裁决闸已经在要求的三段（适用条件 / 核心过程 / 常见失败模式），
并与经验行、技能正文收口到同一份读取面——**判据与产物 schema 必须同源**，否则闸判的是形状 A、
库里存的是形状 B。此项是本仓 §3.1 自查所得，论文只提供"程序性记忆 = 可执行流程文档"这个参照。

### P2-F 库规模-命中率-剔除数的时序读数

按论文的记账口径补一族时序读数（库容量、检索命中数、注入后采纳率、淘汰数），
写进既有 `rsi_summaries.jsonl` 与 `get_status()` 同一观测面，**不另起第二套通道**。
分域（论文的 app_mode 三子库）可作后续项：本仓可沿技能 `category`/工具域切分以降检索成本。

---

## 5. 明确不建议引入

| 不学什么 | 为什么 |
|---|---|
| 无人监督的全自动准入 | 本仓人工评审是主 gate（C10 + 五阶段 + 审批人非空），论文的统计过滤器强度不足以替代；改默认即改安全模型 |
| 单一 VLM grader 标量作唯一奖励源 | 本仓已有"服务端票据 > 客观回执 > 自述"分层与三态空值；折成单标量等于丢掉 `unevidenced` |
| 纯词面检索当作终态 | 两侧目前都是词面，不必为此辩护；本仓 EKB 已带质量罚分链，方向是加预算/条数纪律而非再叠一层词面 |
| 技能库容量自然增长、无预算上限 | 论文自承检索成本上升；本仓 `PENDING_QUEUE_BOUND=50`、有界语料 256 条这类上限是必需品 |
| 技能=无 schema 的 markdown 文件树 | "偶然成功被固化"是其自认失败模式之一；本仓证据轴是结构性优势 |
| 以胜率代替"不退化"证据 | 胜率是均值型指标，正好吞掉本仓要防的那类"新技能修好 A 却打坏 B" |
| 模型/工具集硬绑定 | 与本仓"管理员可调 + 单一事实源"配置哲学相反 |

---

## 6. 对照过程复核出的本仓独立待修（登记防静默遗留；均不因论文而产生）

1. **死旋钮**：`TokenBudget.experience_knowledge`（`context/models.py:56`）在 `context/injector.py`
   无任何消费点（该文件只读 `max_total/system_prompt/memories/conversation_history/reflection_log`），
   却已入 RSI 可优化参数表并带 setpoint（`rsi/integration_manager.py:65`、
   `rsi/system_performance.py:43`、区间 `:303`）——棘轮在调没人读的格。修法见 §4 P2-D，
   属教义第 6 条 + AGENTS.md §2 断点条款。
2. **死 harness（语义是 cold/warm，不是新旧正文对照）**：`eval/ab_library.py` 在 `neurova/` 内零引用，
   仅三个测试文件消费；计划文档已挂"P1-7b 偏差：全删需迁移两个套件与协调路由"待办。
   它**不是** §4 P1-A 的现成替代（双臂语义不同，见 §3.4 与附录 B.1），
   其归属是 §4 P1-C 所指的"真 agent 双臂对照"这一类能力——退役或接生产，须按教义第 7 条
   先比后合再定，不许顺手塞进 runner 判定链。
3. **断链**：`evolution_facade.synthesize_tools`（`evolution_facade.py:312`）→
   `closed_loop.PatternBasedToolSynthesizer.synthesize_from_patterns`（`closed_loop.py:369-373`）→
   `pattern_miner.to_skill_template_list` 这条"频繁模式 → 技能模板"出口**生产零调用方**
   （grep `synthesize_tools|synthesize_from_patterns|to_skill_template_list` 在 `neurova/` 仅命中定义与转发行，
   其余命中全在 `tests/` 与历史审计报告）；签名缺陷 C-05 已修而调用面未接（`docs/BUG_AUDIT_REPORT_2026-09-10.md:521`）。
   注意：`PatternMiner` 本身**是活的**（`post_chat_pipeline.py:2101-2103` 收序列并 `mine()`），
   断的只是 dict 出口那一条臂——判死码要区分"模块死"与"某条通道死"。
4. **写了没人读的计数（已闭环 `31817fd2`）**：`skill_experience.usage_stats.times_presented`
   （原 `skill_experience.py:8, 85, 275, 288`）只有初始化与读取，`record_usage`（`:270-282`）只累加
   `times_used/positive/negative`——"呈现但未采纳"这一维恒 0，且**三份技能账本都没有『呈现』这一格**。
   呈现的真落点是技能目录渲染
   （`context/orchestrator.py:2651-2718` → `skills/skill_injection.render_skill_catalog`），
   不是 `compose_effective_description`（那是写入侧重算描述，本报告首轮误判，留痕见附录 B.5）。
   处置形态：呈现级并入漏斗单源（`6a9e4e12..07356a84`），本字段整体退役，
   并由 `tests/unit/evolution/test_singlePresentationAccountGuard.py` 钉成会红的判据
   （全仓零命中 + 生产写入点数死为 1）。
5. **同一份 `unmerged` 两次取锁重算（已闭环 `31817fd2`）**：`apply_experience_to_skill:250-253` 先在锁内算一遍
   `unmerged`（只用于日志的条数），紧接着 `compose_effective_description:260-261` 再取一次锁算同一份。
   票面曾设想"改调 `pending_rebuild()` 打日志"——复算发现那**仍是两次扫描**（compose 一遍、
   pending_rebuild 一遍），没消掉重复；实作为组合只算一次、日志改报"较基线是否真的扩展了"，
   条数仍归 `pending_rebuild` 单源。与第 4 条同函数族，按教义第 5 条同批处理。
6. **索引漏登（本次已补）**：`docs/08-research/` 的 `rsiagent_vs_neurova_rsi_comparison_2026-10-06.md`
   此前未在 `docs/0-index/README.md` 的 08-research 小节登记（原 `:240-244` 只列三篇）。
   本次交付时把两份对比文档一并登记，索引已与之对齐。
7. **无人读的声明常量**（低优先，登记即可）：`skill_improver.failure_threshold`（`:163, :174` 只赋不读）、
   `GeneticConfig.max_generations`（`genetic_engine.py:85-93`，全仓零引用）、
   `capability_gap.METRIC_GAP_TOTAL`（`capability_gap.py:56`）、`PatternMiner` 的 `min_success_rate`
   （`pattern_miner.py:207` 注释自陈"暂未使用"）。
8. **技能采用/成败记账三份并存**（§8 前置 3 落地时新发现，教义第 6 条候选）：
   ① manifest 漏斗 `selections/applications/completions/fallbacks`——写入方是执行咽喉
   （`tool_executor.py:966, 1001, 1064, 1076` → `post_chat_pipeline.py:1878-1907` →
   `skill_service.record_skill_funnel:824-867`），读方是信任态/召回过滤/前端徽标；
   ② manifest 原始账 `use_count/success_count/last_used_at_ms`
   （`agent_core.py:1595` → `skill_service.record_skill_usage:789-822`，`:835-837` 自陈与漏斗"互不替代"）；
   ③ evolution `usage_stats.times_used/positive/negative`
   （`agent_core.py:1603` → `skill_experience.record_usage:270-282`），读方是淘汰候选
   （`skill_experience.py:485-506`）与剪枝（`evolution_yield_prune.py:62-64`）。
   ②③ 与 ① 在"被采用/成败"上语义重叠；『呈现』这一格原本三份都没有，现已补进 ①
   （`6a9e4e12..07356a84`，票面 [`docs/04-plans/2026-10-08-前置3-技能呈现账收口实施方案.md`](../04-plans/2026-10-08-前置3-技能呈现账收口实施方案.md)
   的「执行记录」），并退役 `times_presented` 这第二份定义；
   **②③ 的口径统一需改淘汰与剪枝判据输入，属生产行为变更，本批明确不做，在此登记**
   （教义第 5 条：命中点无法当场处理时登记，不许静默遗留）。
   注意本批之后 ① 已是"呈现→派发→执行→完成"四级账，②③ 仍只覆盖其中两格——
   三份并存的代价从"读不到第一节"变成"第一节只有一本账有"，收敛方向已定。
9. **进化运行审计面只写不读**（§8 前置 1 落地时新发现，§2 断点条款）：
   `data/agents/<id>/evolution/runs/*.json` 由 `service._persist_run:501-505` 写入，
   全仓（`neurova/` + `src/`）**零读方**——没有端点、没有自检、没有前端。要紧的是它与本门耦合：
   提案只在 `not result.rejected` 时产出（`service.py:287`），所以**例级门拒掉的那些运行**
   的读数（`case_gate`、`reject_reason='case_regression'`）目前只存在于这份没人读的文件里。
   补端点属新建通道（前置 1 票面 Task 4 明令禁止），故登记待另票：要么给审计面一个读口，
   要么让被门拒的候选也进提案列表的"已否决"分面，二者都需先定口径。

   **2026-10-09 前半已闭环（票面 [`2026-10-09-运行终态回写台账-例级门可见性实施方案.md`](../04-plans/2026-10-09-运行终态回写台账-例级门可见性实施方案.md)；
   提交 `a0ec975b` 修复 · `f3bd0b2e` 反向守卫 · `bcde3ed4` 下游三读方 · `cc52e7a7` 入受保护子集）**：
   复核时发现本条真正的问题不是"人看不见审计文件"，而是**台账在向反馈回路说谎**——
   胜者那行早在评测期写成 `accepted=is_winner`，六处终局拒绝各抄四行且都不回写它，
   于是被例级门拒掉的候选在台账里仍是 `accepted=True`，被三个既有读方按「已生效」理解：
   提示词段（`history_ledger.py:163-166`，实测渲染出"已生效（勿做无谓回退）"连续四条，
   而实际部署的自始至终是基线正文）、stall 换轴指令（`:207` 窗口内有一条假接受即不触发）、
   产出剪枝（`evolution_yield_prune.py:51` 见假接受即跳过）。
   修法是把六处拒绝收成一个 `rejectRun(reason)` 出口，同批把胜者行翻成
   `accepted=False` + `reject_reason`，并另开一格 `round_winner` 保留「本轮 tune 上是 argmax」——
   `accepted` 从此只表**被部署**（一格一义，教义第 6 条）。净 LOC 生产池 `runner.py +26/-28`（**负 2**）。
   后半（人怎么逐条看）仍在：`runs/*.json` 依旧零读方，票面选项 B（开 GET 端点）/
   C（并进 RSI 状态面）留作可选后续，等出现真要下钻的消费者再动——不为回填历史去新建通道。
10. **提案端点在服务层有消费方、在 UI 层零消费者**（前置 1 Task 4 顺带实探）：
    `GET .../proposals` 与 `GET .../proposals/{proposal_id}` 挂在 `text_evolution_api.py:266-303`，
    服务内部 `service.decide():427` 会读表，但 `src/` 全仓搜 `proposals` / `text_evolution`
    **无前端命中**。与 `AGENTS.md` §2 断点条款点名的"端点存在≠被消费"同一形态——本轮把 `case_gate`
    接到该端点，是让**已有**读口多带一格，不是新造通道；UI 侧是否要接，属产品口径，不在此定。

---

## 7. 待拍板问题（各选项的影响面与不可逆点）

**Q1 例级不退化门默认开还是关？** —— **已拍板（2026-10-08）：默认开 + 有界容忍入配置。**
- 开：`accept/reject` 立刻收紧，历史"均值涨但有单例跌"的候选形态全部转为拒绝，进化吞吐显著下降，
  留出集小的技能可能长期无候选被接受；影响 `eval/runner.py` 判定链与台账，不改治理阶段。
- 关（保持现状）：继续均值放行，单例退化只进证据面；风险是把 A 的修复成本转嫁给 B 的用户，
  与论文用 `(∄ lost)` 防的正是这一类。
- **选定：折中形态**——默认开 + **有界容忍**（允许 ≤N 条单例跌，N 入 `EvolutionSettings` 单源），
  与既有 bench 容差同族。理由：判据强度可调这一点本仓已有先例
  （`noise_band_delta`、`bench_tolerance`），不需要新开关体系。不可逆点：无（判据可回退）。
  落点与两步次序见 §4 P1-A；**本轮未动代码**，该决定待点单实施时生效。

**Q2 真 agent 轨迹是否进每轮自动评测？**
- 进：留出分与线上行为同域，评测口径最硬；但每候选一次真跑，LLM 成本与轮时延数量级上升，
  必须同时引入 token/费用预算闸与抽样轮次，且 `agent_core.py` 尺寸棘轮禁止回填装配代码。
- 不进（推荐）：只把真执行器接进人工审批前的 `POST /skills/{agent_id}/ab` 双臂试评
  （端点已在，`text_evolution_api.py:207, 253`），审批人看到真轨迹差，自动轮仍跑模拟面并**显式标注
  "该分数来自模拟执行器"**。代价：自动轮判据与线上行为仍解耦。不可逆点：无。

**已拍板（2026-10-09）：选"不进每轮自动"，但把真轨迹接进双臂试评，并同批修前置 2 的探针口径。**
票面 [`docs/04-plans/2026-10-09-双臂试评接真轨迹-前置2落地实施方案.md`](../04-plans/2026-10-09-双臂试评接真轨迹-前置2落地实施方案.md)。
拍板前复算出的**两处口径更正**，此后引用本节别再按原文理解：
1. **"每轮自动评测"这个前提今天不存在**：`closed_loop.py:654` 的自动闭环只做 RSI 度量与阶段判定，
   `rsi/orchestrator.py` 全文零 `evolve`/`EvolutionService` 命中；文本进化在生产只有 admin 端点
   `text_evolution_api.py:187` 一个入口。真实问法是"人工审批前的双臂试评跑不跑真轨迹"。
2. **成本量级实测换算**：双臂取 `dataset.heldout or evaluation_split(dataset)`（`service.py:367`），
   默认 `holdout_ratio=0.25` × `max_examples=50`（`miner.py:161`）≈ 12 例 × 2 臂 = **24 次真 turn**；
   若改走"进每轮自动"，按 `iterations=10` 与 `runner.py:525/532/597/608/687/743/745` 逐站点算
   ≈ **480 次执行 + 480 次判分**，且执行面全换成真回合。两者相差一个数量级，这是选"不进"的量化理由。
3. **Q2 的选项面其实还有一条硬阻塞**（原报告未察）：`ab_library.py:117 make_agent_ab_executor` 依赖
   `agent.process_message`，而该入口实测调一个已被移除的方法（`agent_core.py:1688` →
   `MessageRouter` 无 `create_message`），活体复现 `AttributeError`——**这就是那枚真 agent 适配器
   至今只有测试消费者的直接原因**。已单独立格登台账 §6-98 待裁；本批改走
   `Agent.chat(..., save_memory=False)`（其闸门覆盖面见台账 §6-98 末段）。

**Q3 默认配置下"进化实际不改任何东西"是否维持？**
- 维持（推荐）：`rsi_phase=0` + 文本进化默认关 + C10 默认开，治理最稳；代价是论文所验证的那类
  "自动化能否在自己判据上跑正"，本仓从未取得经验证据，且 §7-Q1 的判据强化正是推进的前置条件。
- 推进：需先落 §4 P1-A（例级准入）与 P1-C（真轨迹），否则是把自动改行为接到弱判据上。
  影响面：晋升判据 `deployment_controller.evaluate_phase_transition` 与治理设置落盘面，
  属可回退但会改变生产行为面。
- 推荐形态：维持默认，但把"判据强度"写进晋升前置（前置条件清单见 **§8**，四条已逐条实探核实态）——
  把治理从"默认保守"升级为"保守有理由且可核验"。

---

## 8. 采用"无人监督全自动"的四条前置条件（2026-10-08 逐条实探核实）

论文的"无人监督"不是勇气，是**资格**：它先把准入做成例级成对回放、把执行面做成真工具链，
才撤掉人在环。本仓若要朝该形态推进，次序必须一致——**先把判据做实，再谈自动化**。
四条前置条件逐条核实如下，**满足态以本轮工作树实测为准**（不是按报告首轮的转述）。

| # | 前置条件 | 满足态 | 判据（什么才算满足） |
|---|---|---|---|
| 1 | 留出侧有例级读数 + 例级不退化门咬合 | **已满足**（2026-10-08 落地 / 10-09 收口） | 同一 `_evaluate` 路径产出 holdout 两侧 per-task 分数，且单例退化能触发拒绝并复位基线 |
| 2 | 判据执行面与线上行为同域（真 agent 轨迹） | **未满足** | 双臂核验的 executor 真跑 `agent.process_message`，而非回显或单轮模拟 |
| 3 | 呈现与采纳可分离计数 | **已满足**（2026-10-08 落地） | 同一轮里"进了 prompt"与"被点名"是两格读数，且只有后者进派发链 |
| 4 | 缺证据时判据不产出可通过分数（fail-closed） | **已满足** | judge 不可用即早退，单例失败记 0 占分母而非中性分 |

**这张表不再是文档里的自查清单**：四行各自对应 `automation_prerequisites.py` 里一枚探针，
晋升 phase ∈ {2,3,4} 时由控制器现算现判，任一行不满足即 `failed` 并点名（详见本节末"前置条件
要落成判据"与台账 §6-97）。表里的"满足态"从此与"能不能升档"同源，不存在第二份口径。

### 前置 1 · 例级准入闸（**已满足**，2026-10-08 落地 / 10-09 Task 5 收口）

**落地前实状**（保留作原委）：拒绝发生在集级均值上（`runner.py:578` `holdout_after <= holdout_before + accept_threshold + ε`），
单例回归只入证据面（`history_ledger.py:181-194` 明写"不改 accept/reject"）。
**根因不在"缺一道门"，在"缺那份读数"**：`runner.py:553` 取 `holdout_after` 用的是 `_evaluate_avg`，
per-task 明细当场丢弃；带明细的 `_evaluate` 只在 tune 集用（`:478, 543`）。
落点与两步次序见 §4 P1-A；默认值已拍板（§7-Q1：默认开 + 有界容忍 N 入 `EvolutionSettings`）。

**票面**：落地方案见 [`docs/04-plans/2026-10-08-前置1-例级不退化门实施方案.md`](../04-plans/2026-10-08-前置1-例级不退化门实施方案.md)。
四笔提交逐笔红→绿 + 活体，均可达：`fc8a1b10 dc510888 d79baa8a 3ae10280`。

- 明细带上 `failed`（`runner.py:313-327`）：`_score_example` 早就算出单例失败，此前被 `_evaluate`
  丢掉——三态契约在集合层已折叠过一次，不许在单例层再折一次；
- 留出两次评测改走**同一条** `_evaluate`（`:525-531`、`:608-625`），评测次数不变
  （`_evaluate_avg` 本就转调它），例级读数落进 `EvolutionRunResult.holdout_case_scores`；
- 判定链新增**判定 2.1 例级不退化门**（`:652-667`，位于 `no_improvement` 之后、锚定地板之前），
  拒绝理由 `case_regression`，容忍度 `EvolutionConfig.case_regression_allowance`（默认 1）——
  撞坏数超过容忍度即拒并复位基线，未量出的单例两个方向都不记账；
- 读数外露：`caseGateReadout()` 作该格唯一构造点，同时进运行审计面（`to_dict`）与提案详情面
  （`EvolutionProposal.case_gate`，经既有 `GET .../proposals/{proposal_id}` 外露，未新建通道）。

**§7-Q1 拍板落点的一处修正**：原文写"N 入 `EvolutionSettings`"，实探发现那会造出判据旋钮的第二处
存放（同族的 `min_improvement` / `bench_tolerance` 全在 `EvolutionConfig`），且要生效还得新写一条
settings→config 灌入通道（今天不存在）——为一个小数扩大装配面不划算。故按拍板**本意**（默认开 +
有界容忍 + 单源可调）落 `EvolutionConfig`；若日后要管理员前端可调，那是独立改动（脏值收敛 +
灌入通道 + 前端读写面三件一起做）。

**活体读数**（真 `SkillEvolutionService.evolve` + 真提案详情端点 + 真 JWT，脚本化 judge/executor 零配额）：
容忍度 0 一臂 `reject_reason='case_regression'`、`regressions=['c']`、不出提案；容忍度 1 一臂
`reject_reason=''`（留出均值 0.5→0.575 过关、撞坏一条落在容忍度内被放行），但 `regressions=['c']`
仍随提案外露，端点回 `{"allowance": 1, "regressions": ["c"], "unevidenced": []}`；仓内 `data/`
未被探针写入（隔离数据根生效）。实测拒绝形态计数：本轮脚本化两臂，一臂被本门拦下——
这不是生产流量的拒绝率，只是"门确实在拦"的读数。

**同根因的下一环，登记不静默**：`runs/*.json` 审计面全仓无读方（§6-9），而本门**拒绝**的那一路
恰好不出提案（提案只在未拒时产出），故"门拦了谁"目前只落在那份没有读口的文件里；补端点属新建
通道，本批票面明确禁止，另票处置。

### 前置 2 · 真轨迹执行面（未满足）

runner 默认执行器回显技能文本（`runner.py:146-154`，模块头自陈"真实接线方应注入一个真正跑 agent 的执行器"），
`ab_compare` 默认 `SimulatedAgent`（`service.py:374`）且端点不传 `agent`（`text_evolution_api.py:253-256`）。
现成真 Agent 包装 `make_agent_ab_executor`（`ab_library.py:117-139`）**签名不收 `skill_text`**，
与判定链所需的 `(skill_text, task_input)` 不兼容。落点见 §4 P1-C。

### 前置 3 · 呈现/采纳分离计数（**已满足**，2026-10-08 落地）

采纳侧已有闭环（`chat_pipeline.py:2084-2086` 登记注入身份 → `post_chat_pipeline.py:1813` 回写
`adoption_outcome`），但两个缺陷使"自动化去读反馈"读不全：
① 同一轮注入的三条经验共用同一张成败票；② `times_presented` 声明了却无生产写入方
（`skill_experience.py:270-282` 只累加 `times_used/positive/negative`），且三份账本都没有『呈现』这一格——
呈现的真实落点是技能目录渲染（`context/orchestrator.py:2651-2718`），首轮误认的
`compose_effective_description` 只是写入侧重算描述（票面已更正）。
没有第 ② 格，无人监督的系统看不见"技能被喂进去但模型没照做"这一类信号——
它恰是论文那条自承局限（"语言指令压不过模型固化默认"）在本仓的可观测形态。

**票面**：落地方案见 [`docs/04-plans/2026-10-08-前置3-技能呈现账收口实施方案.md`](../04-plans/2026-10-08-前置3-技能呈现账收口实施方案.md)。
该方案把呈现账收口到 **manifest 漏斗**（唯一有生产咽喉写入、有归因纪律、已有多读方的那本账），
并退役 `usage_stats.times_presented` 这第二份定义。**此处另有一处判断要更正**：
本报告 §3.5 与 §6-4 曾把 `compose_effective_description` 认作"呈现咽喉"——实测它只有
`_apply_to_skill` 一个调用方（写入侧重算描述），**不是**每轮进 prompt 的那一处；
真正的呈现点是 `context/orchestrator.py:2651-2718` 的 `_skill_catalog_section`
（经 `skills/skill_injection.render_skill_catalog` 渲染技能目录，被 `build_context:1222`
与 `build_system_prompt:2752` 两条路径共用）。截断未列出的技能不得计呈现、
cold 臂（`skills_off`）不得计呈现，两条都已在票面钉成判据。

**落地态（六笔提交，逐笔红→绿 + 宽域 A/B + 活体，均可达）**：
`6a9e4e12 39ef9eb1 473d5ca7 721bcb92 31817fd2 07356a84`。
收口理由不是"哪份更新"，是判据：**哪本账已有生产咽喉写入、有归因纪律、有多读方**——
三份候选里只有 manifest 漏斗符合。给"零写入零消费"的 `usage_stats` 再配一条写入路，
是教义第 6 条禁止的形态，故同批退役第二份定义并立反向守卫（全仓 `times_presented` 零命中 +
生产写入点数死为 1，双源复发即红）。
活体读数（不是单元测试代替）：warm 臂真构造面产出 5 条呈现且目录进了 prompt；
cold 臂 0 条且目录缺席；真 post-chat flush 归因 `{presentations:1, selections:1,
applications:1, completions:1}`——呈现没有冒领 selection；manifest 读数面 `presentations=1`；
判据经真 `orchestrator.get_status()` 与真 HTTP 端点各给一次 `state=passed`；
宽域 A/B 仅本批树红 0 条（两侧节点总数同为 5012，汇总报数与实抽条数逐侧对上）。

**同根因的下一环，登记不静默**：① 同一轮注入的多条经验仍共用一张成败票
（分离需给每条经验各自的采纳证据，属 `adoption_outcome` 粒度改造）；
② `usage_stats.times_used/positive` 与漏斗 `selections/applications` 的采用/成败口径仍三份并存
（§6-8）——统一它要改淘汰与剪枝的判据输入，属生产行为变更，另立票面。

### 前置 4 · 缺证据不给通过分（已满足，本报告首轮记为缺陷，现勘误）

`runner.py:469-475` 有 `_judge_available` 探针，不可用即 `judge_unavailable` 早退，不进判定链；
`_score_example:277-300` 单例执行/判分异常返回 `0.0` 并置 `failed=True`，注释原文
"0.0 是诚实记分不是中性分——防'评测崩了但剩余用例分高'的幸存者偏差"。
两侧同为 0 时走 `no_improvement` 拒绝，方向 fail-closed。
历史洞（judge 不可用时前后同为中性 0.5、被当"零增益通过"）已由 `min_improvement` 0.0→0.01
（`config.py:32-36`）与上述探针关闭。**该条已在仓内成立，不再列为待办。**

### 前置条件要落成判据，不落成口头条件（**已落成**，2026-10-09）

按 AGENTS.md 核心原则第 7/8 条与反证守卫惯例，这四条一旦点单实施，收尾形态应是
**晋升判据里的可红断言**（`rsi/deployment_controller.py:83-114` 的 `evaluate_phase_transition`
增加前置格：未满足即 `GateVerdict.failed` 并点名是哪一条），而不是文档里的一句"以后要注意"。
否则它与 §3.7 所述"默认配置下闭环半通"是同一类状态——写了没人读，读了不咬合。

**本批已按该形态收口**（票面 [`docs/04-plans/2026-10-09-四条自动化前置落成晋升判据实施方案.md`](../04-plans/2026-10-09-四条自动化前置落成晋升判据实施方案.md)，
台账 §6-97）：真值源单点 `neurova/evolution/rsi/automation_prerequisites.py`，四条各一枚
**运行期可证伪探针**（不是配置旗标），控制器在链首短路消费，绑定范围 = 晋升目标 phase ∈ {2,3,4}。
写入本行时的实时读数：`caseLevelGate=True / realTrajectoryExecutor=False / presentationLedger=True /
failClosedOnMissingEvidence=True` ⇒ 聚合 `failed`，点名前置 2。也就是说本节从"文档里的一句提醒"
变成了"今天真的进不去自动执行档"——**前置 2 未满足是事实，不是判据的误伤**。

---

## 9. 前置条件核实后的对照结论复核

按 §8 的实测态重跑一遍对照，六条结论变化如下（其余各维 §3.1-§3.3、§3.5-§3.8 判定不变）。

1. **§3.4 的差距等级要上修。** 首轮判"缺接线（低成本）"，实测判"**缺判据输入（中成本）**"——
   本仓不是有一条松的门，而是想让门变严也**没有那份例级读数**
   （`runner.py:477, 553` 两处均 `_evaluate_avg`）。这一维与论文的真实距离比首轮估计更大。
2. **§3.9 的"包装已存在"论据撤回。** 真 Agent 执行器与判定链接口不兼容（附录 B.2），
   补齐要新写一层，且受 `agent_core.py` 尺寸棘轮约束不得回填装配代码。
3. **前置 4 已满足，使"能不能全自动"的答案变窄。** 本仓在"缺证据不得误判为通过"这条上
   已与论文同级甚至更硬（三态 `unevidenced` / `measurement_blind` vs 论文把分数折叠成标量）。
   原先并列的三条前置**全部落在判据的输入质量面**（例级读数、真轨迹、呈现票），
   **没有一条落在治理层**——治理层本仓更强（五阶段 + 债务闸 + 人工主 gate + 独立成功源轴）。
   前置 3、1 落地后，**只剩真轨迹执行面一条**（§8 前置 2）。
4. **补齐三条前置后，本仓准入强度会高于论文**：例级门 + 留出/真留出双集 + 服务端票据分级 +
   `min_independent_successes=3`，对论文的"grader 标量 + 例级对跑"。
   二者真正不可比的剩余项只有一条：**论文的执行面天然是真的**（真跑 230+ 工具、判真工件），
   本仓要额外补——这是与论文之间唯一剩下的**结构性**差距，其余都是自家取数缺陷。
5. **§4 P1-B（成功侧对照）不进前置清单**，理由要写清：它不阻断自动化（改写质量下降会被准入闸拦下），
   它影响的是**候选吞吐**而非**判据可信度**。归为质量项，与前置条件分档，避免把"想更好"
   混进"不做就不能自动"。
6. **待拍板项与次序**：Q1 已定（默认开 + 有界容忍入配置，落点修正见 §8 前置 1）；**Q2 已定**
   （2026-10-09：真轨迹只进人工审批前的双臂试评 + 同批修前置 2 探针口径，见 §7-Q2 拍板段与票面）；
   Q3 未拍板，**双臂批按"维持默认"设计**（自动轮不调文本进化），选它等于默认维持。
   前置实施次序原定 **3 → 1 → 2**，其中**前置 3（六笔 `6a9e4e12..07356a84`）与前置 1
   （四笔 `fc8a1b10..3ae10280`）已于 2026-10-08 落地**（见 §8），**只剩前置 2**：动执行面
   ——它的成本与风险最高，且前一环（例级读数与门）不做完，真轨迹的分数仍会被集级均值吞掉。
   次序的这一收口有实测意义：前置 1 落地后，执行面一旦接真，撞坏既有用例就会被逐条判住，
   而不是被均值吸收。
7. **前置 3 落地后新看清的一件事**：本批真正的障碍不是"没人写计数"，而是**呈现与派发在归因上
   会被混为一谈**——若把呈现条目按 selection 计（首轮方案就差点这么接），漏斗会凭空多出一条
   "模型点名了技能"的假证据，且比现状更难发现，因为它读数非零、看起来在工作。
   现由 `testPresentedEntryCountsSeparatelyFromSelection` 与活体读数 `{presentations:1, selections:1}`
   两处分别钉住。
8. **前置 1 落地后看清的机制事实：门越严，取数歧义越致命。** `_score_example` 的 `failed`
   一直在算，只是被 `_evaluate` 建明细时丢掉——若先接门、后补标记，"这一例判分崩了"会被读成
   "这一例退化了"，门就把器械故障当质量结论来拒，且拒绝看起来完全合理。所以本批的次序
   （读数可信 → 读数存在 → 读数咬合）不是保守，是判据成立的前提；票面把 Task 1 排在门之前
   正是这一条。同理，"未量出"在门禁里既不算退化也不算没退化（`unevidencedCases` 独立成格），
   三态不许在任何一层被折叠成布尔。
9. **§6-9 落地后看清的机制事实：骗局不是漏写，是缺一道反向判据。** 台账的 `accepted` 与
   运行终态不一致，此前**没有任何用例**在看守它——`test_attribution` / `test_exploration_directive`
   / `test_history_ledger` 全是手工 `append` 记录再测读方，测不出「写进去的那一行是否如实」。
   本批三条下游判据因此各跑 5 轮真 `run()` 累计在同一 key 上，不用手工记录代替；
   另两条（早退不造行、未量出不写成退化）在修复前后**同态为绿**，如实记为前瞻守卫而非红。
   教训可迁移：凡「一个旗标被多个读方按自己的语义理解」处，守它的方式是跑通整条写路径
   再回读落盘文件，不是给读方补单测。
10. **前置落成晋升判据后（2026-10-09，§8 末节），"只差前置 2"这句话的形态变了。** 此前四条
    只写在本报告里，任何人把 `NEUROVA_GOVERNANCE_SETTINGS` 的 `rsi_phase` 调上去就能跳过全部
    前置；现在晋升目标 ∈ {2,3,4} 会被控制器链首硬否决，实时读数
    `realTrajectoryExecutor=False` 点名到这一条。**因此本报告先前的次序结论不再需要人来守**：
    Q2 虽已拍板（双臂批接线），**其效果只在人工试评面** ⇒ 每轮评测的执行面仍未接真 ⇒ 前置 2 不满足 ⇒ 自动执行档进不去，这条链条现在是机器判据
    而不是纪律自觉。反过来说，它也意味着**任何"先把档位调上去再说"的尝试都会当场红**，
    包括自动化 NPC 的尝试。

---

## 附录 A. 证据来源与复算口径

- **本仓侧**：工作树实测（2026-10-08）。逐条 `文件:行号` 见正文。承重断言的复核方式：
  ① `experience_knowledge` 无消费点——`grep -rn 'experience_knowledge' neurova/` 全命中集 +
  亲读 `context/injector.py:690-780`；② `ab_library` 零生产消费——`grep -rn 'ab_library|run_cold_warm_ab'`
  全仓，命中仅 `neurova/evolution/eval/ab_library.py` 自身、三个 `tests/` 文件与两份历史文档；
  ③ runner 默认执行器回显——亲读 `eval/runner.py:146-154`；④ 集级均值判据——亲读
  `eval/runner.py:568-644` 与 `eval/history_ledger.py:175-195`；⑤ 断链——三条 grep 口径见 §6-3。
  本轮第 1 段实探（§8 前置条件核实）另加四条：⑥ holdout 侧无例级读数——亲读
  `eval/runner.py:477, 553`（两次均 `_evaluate_avg`）与 `:308-321`（`_evaluate` 才返明细）；
  ⑦ 双臂核验走模拟体——亲读 `eval/service.py:350-379`（`agent` 形参缺省即 `SimulatedAgent`）
  与 `api/endpoints/text_evolution_api.py:253-256`（调用未传 `agent`）；
  ⑧ 呈现记账与三份账——亲读 `evolution/skill_experience.py:250-292`（描述重算与 usage_stats）、
  `context/orchestrator.py:2651-2718` 与 `skills/skill_injection.py:114-168`（目录渲染=呈现真落点）、
  `skills/skill_service.py:29-58, 789-867`（漏斗与原始账两份）、
  `evolution/evolution_yield_prune.py:62-64`（evolution 账本的现役读方）；
  ⑨ fail-closed 双闸——亲读 `eval/runner.py:469-475`（探针早退）与 `:272-300`（诚实记 0）。
- **论文侧**：机制引文（§2、§3.1-3.3、§4、Appendix C.1）与 Table 1/3 的数字取自 arXiv:2609.22086v1
  **HTML 正文**，元信息（作者、提交日、页数、类目）取自 arXiv 摘要页；若干超参读数
  （缺口复发阈值 3、弱技能选靶上限 22、grader 阈值 τ=0.6、k=3、剔除 66 条）来自 HTML 正文的
  抽取式读数，**未逐条亲验原 PDF**。机构归属（Adobe / 布朗大学）仅见于二手报道，正文已标注未证实。
  以上一律按背景对待，不作为本仓任何设计判断的依据。
- **本文档不是事实源**：任何落地前须按修复教义第 1 条复核实状（行号会漂、模块会改名）。

---

## 附录 B. 本报告首轮的三处自我更正（2026-10-08，交付前实探）

> 沿用 [`rsiagent_vs_neurova_rsi_comparison_2026-10-06.md`](rsiagent_vs_neurova_rsi_comparison_2026-10-06.md)
> 附录 B 的先例：对比结论经实探/实施后自我更正并留痕。三处在**入库前**已就地改正文，
> 此处记录改了哪、为什么，供后续读者核对首轮口头表述与现文的差异。

**B.1 `ab_library` 是语义错配，不是"现成的正确 harness"。**
首轮（含对话里给出的 §4 P1-A 表述）把 `run_cold_warm_ab` 判成"形态正确、只缺接线"。实探后判错：
它的双臂开关是 `skills_enabled`（技能库开 vs 关，`ab_library.py:142-170`），而 runner 准入要比较的是
**旧正文 vs 新正文**——两种对照不可互换，按首轮方案接线会做出一条错接线。
真正缺口更上游：holdout 侧压根没有 per-task 读数（`runner.py:553` 走 `_evaluate_avg`）。
正文 §3.4 / §4 P1-A / §6-2 已按"先补读数、再加门、`ab_library` 单独处置"改写。

**B.2 `make_agent_ab_executor` 注不进判定链。**
首轮写"包装函数已存在，接一下即可"。实探后判错：其执行器签名
`(task_input, *, skills_enabled, seed)`（`ab_library.py:128`）不收 `skill_text`，
与 runner / `ab_compare` 的执行器契约 `(skill_text, task_input)`（`runner.py:153, 282`）不兼容。
正文 §3.9 / §4 P1-C 改为"需新写一层以指定正文为指令的真 Agent 包装"，
并保留 `ab_compare(agent=...)` 形参已可注入这一有利事实（`service.py:353`）。

**B.3 "缺证据时判据给出可通过分数"已闭环，首轮列为短板有误。**
该洞由 `runner.py:469-475` 探针早退 + `:277-300` 单例失败诚实记 0 两处封住（fail-closed）；
`config.py:32-36` 的注释记录的是**历史原委**，不是现行缺陷。正文新增 §8 前置 4 记为**已满足**，
§7-Q3 的推进前置条件相应收敛为三条（前置 1/2/3）。

**B.5 `compose_effective_description` 不是呈现咽喉（首轮定位错误，已就地更正）。**
本报告 §3.5 与 §6-4 首轮把它认作"每轮进 prompt 的呈现点"。实测它只有 `_apply_to_skill`
一个调用方，作用是把未合并经验重算进技能描述（**写入侧**生效通道），与"这一轮目录里
有没有它"无关。真呈现点是 `context/orchestrator.py:2651-2718` 的 `_skill_catalog_section`
经 `skills/skill_injection.render_skill_catalog` 渲染技能目录，被 `build_context:1222` 与
`build_system_prompt:2752` 两条路径共用。误判的代价不是措辞：按首轮定位接计数器会把
"经验被写进描述的次数"当成"技能被模型看到的次数"，两个数量级不同、语义也不同。
教训与本仓既有那条同源：**判"某处是不是咽喉"要数它的调用方与调用时机，不能看函数名**。

### B.6 前置 3 落地后追加的一条机制事实（2026-10-08）

活体探针首跑时 manifest 读数全零，根因不是产品缺陷：技能注册进了 `agent.skill_service`
那个实例，而 post-chat flush 按 `(pool, owner)` 路由到 `library_service.get_library`
缓存的**另一个** SkillService 实例，于是 `record_skill_funnel` 如实判"查无此技能"返回 `False`。
教训：**写侧落点必须与路由落点是同一个库实例**；`False` 不抛异常，会把"我没接对"
读成"产品没写"——这是活体验证里最容易误判成通过的一类读数形态。
纠正后 OVERALL=PASS，读数见 §8 前置 3 的落地态。

### B.4 本轮环境事实（不作本仓缺陷登记，供后续批次参照）

- 流水线 Skill 引用的宽域 A/B 脚本 `scripts/ab_compare.sh` **在本仓不存在**
  （`find` 无命中、`git log --all --diff-filter=AD` 无记录、`git check-ignore` 未忽略）。
  后续代码批次若要走第 5 段 A/B，须按同语义在**仓外**手工建 detached worktree，
  不可退回 `git stash` 形态（工作树常含并发会话在途改动）。
- 本轮并发在途改动（**不属本批，严禁搭车提交**）：`neurova/aigc_studio/services.py`、
  `neurova/aigc_studio/store.py`、`neurova/core/agent_run_store.py`、`agent_workspaces/**`、
  `tests/unit/api/test_studioRunCancel.py`。本批只提交本报告与 `docs/0-index/README.md` 两个路径。
- 本轮范围经确认：**未动任何生产代码**，§4 与 §8 的落点均为待点单项；
  §7-Q1 的默认值决定（默认开 + 有界容忍入配置）已记录在案，实施时生效。
