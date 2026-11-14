# VideoEvolve vs Neurova harness 自进化机制对照测评（2026-11-14）

> 对象：论文 **VideoEvolve: Evolving Agent Harnesses for Video Temporal Grounding**（arXiv 2610.01766，
> 2026-10-01 提交，Bingjun Luo、Yuhuan Fan、Jialin Guo、Siqi Li；代码 github.com/bingjunluo/VideoEvolve）。
> 触发：公众号 BuddyMe 文章《别再手动调 Harness 了：让框架自己进化自己》
> （mp.weixin.qq.com/s/gQAnyt70iNQQ6Zt5QM5ziw）——文章为二手转述，本档以论文原文为准。
> 对照面：本仓 `neurova/evolution/`（文本进化闭环 + RSI）此前按 HarnessPro 批次建成的 harness 自进化体系。
> 性质：只读测评，不含任何代码改动。改进项均给出影响面，待拍板后另立工单。

---

## 0. 结论先行

**参考总分（六维均分）：VideoEvolve 7.4 / Neurova 8.3**（领域特化研究原型 vs 通用平台，总分仅作参考，逐维更有意义）。

> **复评声明（2026-11-14，用户裁定）**：初评「7.4 / 7.8」是对**实施前**代码的盘点分，**作废**。
> 本分以实施后代码为准重评：V1–V6 六项已全部落地（V1+V2 `af0386dd6`、V6 `7b6181e37`、
> V4 `3994d1412`、V3 `4bda2ff60`、V5 `cc3a3ee6c`；补提交 `d9d1be7f3`/`6d5a111ae`），
> 当前 HEAD（含并行批次）上 evolution 目录 1970 passed、治理/进化 API 与公开面守卫全绿、
> 9527 真后端活体探针通过。逐维 re-score 见 §2 打分表。

- **两套体系高度同构**：论文的「冻结模型 + 可进化 harness」「dev/validation 分离」「聚合反馈防泄漏」
  「执行反馈引导局部修改」「验证决定继承」，在本仓分别对应冻结被测模型/技能、四集分离（train/val/
  holdout/heldout）、密封 heldout 只出聚合证据、`ReflectiveMutator`、8 道拒绝门 + 人工主闸。方向一致，
  且本仓在**判据、成本、治理**三面明显更厚。
- **论文真正的增量启发只有两条，但都打在点子上**：
  1. **有界 near-miss 修复通道**——被验证拒绝但开发增益为正的候选，带门别诊断进入有界修复轮，
     而不是直接弃置。本仓 `neurova/evolution/` 全域 grep 无 near-miss/repair/rescue 概念，落选候选
     只以「已证伪假设」形式回喂变异器。论文消融显示分支保留在两个视频分离基准上 +1.58 macro S，
     且开发期求解器调用更少——**保留「第二名」比每轮只留冠军更省更准**。
  2. **「填空式」可进化面 schema**——阶段接口固定、每份提案只编辑一个被允许的面（代码或文本）、
     候选先过接口检查再进评测。本仓的可进化面是隐式的（4 类文本槽位写死在 constraints/exec_suite 里），
     没有「面」的一等表示；将来若把阶段内策略纳入进化，这套 schema 是安全边界。
- **论文的成分分析支持本仓既有排序**：指令精修是稳定收益源且不增加调用；代码进化收益随基准波动
  （ReXTime 条件 mIoU 增益明显、TimeLens-Bench 上有限），且部署调用数近乎翻倍（0.996→1.963）。
  本仓「先文本进化、代码级仅人工提案」的保守姿态与该实证结论吻合——**不需要为「不能自动改代码」补课**，
  需要的是把「哪层带来了多少增益、花多少运行时成本」量化进提案读数。
- **不建议照搬**：六阶段骨架（observation→hypothesis→cross-check→arbitration→budget_gate→finalization）
  与「再取一次预测取中位数」的条件细化是视频时间定位域特化形态；本仓 chat_pipeline 固定阶段 +
  hooks 事件面已承担同构职责。借鉴其「接口固定、单面编辑、分支保留」的**结构纪律**，不搬其管线。

---

## 1. 论文要点

### 1.1 问题与设定

视频时间定位（给自然语言查询，在长视频中框定事件起止时间）用「冻结视频-语言大模型 + 外层 harness
（工作流、提示词、前后处理）」求解；模型不动，harness 决定查询怎么引导预测、预测怎么被精修——
即性能天花板。手工调 harness 两大痛点：失败诊断难（查询理解/边界回归/后处理哪一层错了难分）；
改动协同难（工作流与指令耦合，改一处动全身）。

形式化：harness h=(C,T)，C 为可执行代码（控制模型调用、状态更新、区间选择），T 为文本（任务指令与
可复用技能）；目标是在满足阶段接口与资源限制 B 的 harness 空间中最大化开发集得分 S_dev(h; M)。

### 1.2 机制一：填空式结构表示（Cloze-Structured Harness Representation）

- **六阶段固定骨架**：observation → hypothesis generation → cross-checking → arbitration →
  additional resource use（budget_gate）→ finalization；视觉观察、候选区间、验证证据、当前选择
  在阶段间按固定接口流动。
- **可进化槽位**：每阶段内部的模型交互方式、工具使用、假设处理逻辑（代码面），以及事件匹配与
  边界判断指令（文本面）。
- **编辑纪律**：每次 proposal 只改一个被允许的面，其余继承父代；阶段顺序不可动；候选必须先过
  接口检查 + 资源/可靠性限制，才能作为完整 harness 参与评估。

### 1.3 机制二：分支引导进化（Branch-Guided Harness Evolution）

- **两个角色**：champion（已接受改进的当前最优 harness，提供执行证据）；retained code branch
  （被保留但未取代 champion 的代码分支，可作继续编辑的父代）。
- **循环**（Algorithm 1）：当前开发 batch 执行 champion 构造证据（失败案例+弱点总结+应保留成功案例
  +历史反馈）→ 编码 agent 提出候选（普通 proposal 从 champion 出发；代码类 proposal 可从「开发得分
  最高的保留分支」出发）→ 接口检查通过者与 champion 在**同一开发 batch** 评估 → 只有严格超过
  champion 的最高分候选进入 validation → 在**与开发集按视频分离**的 validation batch 上比较，
  每轮至多一个候选取代 champion。
- **near-miss 修复**：validation 拒绝但开发增益为正的候选成为 near miss，获得**有界修复机会**
  （以 champion 或保留分支为起点，结合回归诊断再编辑）。
- **防泄漏**：逐样本 validation 内容不对提议者公开，只允许聚合反馈。
- **分支生命周期**：晋升（取代 champion）或重试额度耗尽后重置。
- **超参**：60 proposal slot/轮 × 20 轮；每查询 ≤4 次 solver 调用、96 帧；编码 agent gpt-5.6-sol；
  目标模型冻结 Qwen3.6-35B-A3B-FP8；搜索期综合分 S = 0.5·mIoU + 0.3·R@.5 + 0.2·R@.7；
  全程共耗 217,767 次 solver 调用。

### 1.4 结果与成分分析

- 五基准（Charades-STA / ActivityNet / QVHighlights / ReXTime / TimeLens-Bench）mIoU 全部超过
  Cloze 种子；Charades-STA 70.05/61.35（R@.5/mIoU）、QVHighlights 71.68/66.27，并超过 DART、
  TFVTG、ChatVTG 等冻结模型 workflow 与部分训练类方法。
- **分支消融**：No-Branch 对照保留冠军继承/历史反馈/验证/修复、只去掉分支延续，Charades
  66.59/58.82 vs Full 70.81/61.90、QVHighlights 67.81/64.22 vs 72.32/67.24、TimeLens macro S +1.58；
  且 Full 组开发期 solver 调用更少——优势不是堆算力。
- **成分交换**（模型固定、不再优化）：
  | 臂 | ReXTime R@.5/mIoU | 调用数 | TimeLens R@.5/mIoU |
  |---|---|---|---|
  | seed | 51.14/48.71 | 0.996 | 46.86/45.68 |
  | 仅进化指令 | 55.70/52.00 | 0.996（不变） | 53.02/50.35 |
  | 仅进化代码 | 52.99/49.85 | 1.963 | 49.73/47.97 |
  | 完整 | 59.17/53.93 | 1.948 | 53.53/50.73 |
  指令精修 = 稳定增益且不加调用；代码进化 = 条件式细化，收益随基准波动、调用数近乎翻倍。
- **失效案例**：细化不保证正确——水壶查询三次调用修复了漏检，电灯开关查询 seed 本对、完整
  harness 三次调用仍漏检。作者如实指出：组合多假设可能修复漏检，也可能保留/放大误差。

---

## 2. 逐机制对照

> 「本仓现状」栏与「缺口」标记为**实施前盘点**原文（2026-11-14 盘点态）；标记的缺口
> 已随 V1–V6 全部闭合（见 §3 状态更新与各批 commit 号），本表保留作盘点存档。

| 论文机制 | 本仓现状 | 判定 |
|---|---|---|
| 冻结模型 + 可进化 harness | 冻结被测模型/技能；进化只动技能正文等文本 | 同构 |
| 六阶段固定骨架 | chat_pipeline Step 0–5 固定序列 + hooks 事件面（PreToolUse/PostToolUse/Stop） | 同构（本仓阶段不可被进化改写，论文可改阶段内代码——见 §3-V3） |
| 填空式「可进化面」schema | 无显式「面」表示；4 类文本槽位散落在 constraints/max_skill_size 等标量限制里 | **缺口（V3）** |
| 单面编辑 + 接口检查后才评测 | 变异只产文本（天然单面）；无接口检查层（文本无需） | 部分具备；扩展面时需补 |
| dev/validation 视频分离 | train/val/holdout/heldout 四集；holdout 为搜索判据、heldout 密封 | 本仓更严（四集 vs 两集） |
| 逐样本验证内容不对提议者公开 | 密封 heldout 永不参与判定、只出聚合证据；泄漏闸 + leak critic | 同构，本仓更厚 |
| 执行反馈引导局部修改 | ReflectiveMutator 读失败用例+联合诊断+编辑历史+同域 harness | 同构 |
| **near-miss 有界修复** | 无（全域 grep 无 near_miss/repair/rescue）；落选者仅以「已证伪假设」回喂 | **缺口（V1/V2）** |
| 保留分支一等对象（晋升/重置生命周期） | N2 递归池保留非劣幸存者（pool_size 1–3）+ pareto_variants 可单点采纳；但分支非一等对象、无重试额度/重置语义 | 部分具备（V2） |
| 每轮至多一个候选晋升、须严格超冠军 | argmax 定胜者 + 8 道拒绝门 + 人工主闸 | 同构，本仓更严 |
| 近平分处理 | judge 匿名盲选 A/B + 成本 tiebreak | 本仓更厚 |
| 成本计量（搜索/部署分离） | EvalCostLedger（CoP/软硬门/tiebreak）+ 按用户成本榜；但提案未透出「部署形态成本差」读数 | 本仓更厚，补读数（V6） |
| 人工治理/审计/回滚 | decide() 人工主闸 + journal.git 版本链 + 回滚端点 + 运行审计 | 本仓独有厚面 |
| 成分归因（指令 vs 代码交换实验） | 有 judge_vs_sealed/source_mix 等读数；无「逐层成分归因」 | 缺口（V4） |
| 实证证据 | 5 基准 + 分支消融 + 成分交换 + 失效案例，公开可复现 | 论文强；本仓机制齐但默认关、无公开基准数 |

**六维打分**（口径同既有对照档，10 分制）。Neurova 列为**实施后复评分**（以当前代码为准；
初评 7.8 已作废）。「本仓现状」栏保留实施前盘点原文，供对照缺口是否闭合：

| 维度 | VideoEvolve | Neurova（复评） | 说明 |
|---|---|---|---|
| 进化对象覆盖面 | 8.5 | **7.0**（初评 6.5） | 可进化面由隐式标量升级为显式 schema（名称/类型/预算键/套件适用性/接口约束=写回位置+消费方，单一事实源），提案按面记录、单面编辑纪律落地；但可进化面仍限 4 类文本，阶段内代码仍不可自动改（代码级仅人工提案——论文成分分析亦支持此保守度） |
| 搜索策略 | 8.0 | **8.5**（初评 7.5） | V1 near-miss 有界修复通道（四类回归型拒绝带门别诊断，额度受治理设置约束）＋V2 分支一等化（晋升/重试额度/退役生命周期，保留与孩子共享池容量不放大预算）落地；叠加既有递归池、Pareto 多档、盲选与成本 tiebreak——论文的搜索机制已全覆盖且有余 |
| 验证与采纳判据 | 7.0 | **9.0**（持平） | 四集分离+8 道门+盲选+噪声地板+例级门+锚定地板不变；修复通道候选同过约束/泄漏闸与全链门（不是绕闸通道），判据完整性未因扩机制放松 |
| 成本核算 | 7.5 | **9.0**（初评 8.5） | V6 部署形态成本差进提案（每任务 tokens/费用差+相对比例+CoP 两列，未量到诚实 unmeasured）；真臂预算计划把修复轮计入（与 runner 同一把尺）——「采纳后每任务多花多少」审批即见 |
| 治理与安全 | 5.0 | **9.5**（初评 9.0） | V5 可部署工件：冠军+非劣变体版本化打包，证据指针（run/proposal/journal commit）闭环，批准转 applied、按工件回滚（无漂移才可滚，漂移如实拒绝）；repair_rounds 治理设置项带合法域钳位 |
| 实证证据强度 | 8.5 | **6.5**（初评 6.0） | 新增 ~50 项守卫测试（先红后绿）＋9527 真后端活体探针；但机制仍默认关、尚无真实任务基准跑分与生产流量数据——这一维仍显著落后论文的公开基准证据 |
| **均分** | **7.4** | **8.3**（初评 7.8，作废） | |

---

## 3. 启发与候选改进项（已全部拍板实施，2026-11-14）

> 状态更新（同日）：用户点单「按顺序开工」，六项**全部落地**——
> V1+V2 `af0386dd6`、V6 `7b6181e37`、V4 `3994d1412`、V3 `4bda2ff60`、V5 `cc3a3ee6c`。
> 均默认灰度关/零行为漂移（V3 含一处三抄漂移修正：runner 的 param_description
> 判分上限 15000→200，与 mutator/约束闸同源）。live-verify：9527 真后端
> 治理面 roundtrip＋422 越域＋工件三端点＋路径穿越拒读，[ERROR]=0。
> 以下为实施前的候选分析，影响面描述仍有效。

### V1 近似达标候选的有界修复通道（near-miss repair）★推荐

**做什么**：`SkillEvolutionRunner` 的 8 道拒绝门处，把「开发增益为正但被验证侧门（holdout_regression/
case_regression/exec_suite_regression/coreset_recheck）拒绝」的候选标记为 near-miss，带上门别诊断
进入 ≤N 次（新设置项 `evolution_repair_budget`，默认 0=关闭）定向修复重评；修复以当轮 champion 或
N2 池成员为起点。修复成功即按既有门正常晋升，全程入运行审计与编辑台账。

**为什么值**：论文消融的direct evidence——分支保留 +1.58 macro S 且开发调用更少。本仓落选候选目前
只有「已证伪假设回喂」一条弱通道，差一点的好候选被整轮丢弃；递归池（N2）保留的是幸存者，
不覆盖「被门误伤」的候选。

**影响面**：`neurova/evolution/eval/runner.py`（拒绝路径 :1128-1231、多变体轮 :545-768）、
`service.py`（evolveRecursive 轨迹 :975-1096）、`eval/config.py`（新设置项）、
`api/endpoints/text_evolution_api.py`（settings 透出）、`security/eval_experiment_settings.py`、
SettingPage 实验性评测面板、tests/unit/evolution/eval/ 新守卫。

**代价/不可逆点**：每轮最多多 N 次候选评测（预算闸既有，成本可控）；修复候选与普通候选同门同规，
不放松任何判据；默认 0 关闭，随时可回退。无不可逆变更。

### V2 保留分支一等化（branch lifecycle）★推荐（可与 V1 同批）

**做什么**：把 N2 递归池的池内基线升级为显式分支对象：记录每分支的谱系、开发得分、重试剩余额度；
晋升（其后代成为新 champion）或额度耗尽时重置；分支与 champion 的差分摘要注入变异器证据。
数据落运行审计 `runs/*.json` 的 lineage 字段。

**影响面**：`service.py:975-1096`（池管理）、`runner.py`（证据构造 :337-377）、运行审计 schema、
`tests/unit/evolution/eval/test_evolveRecursive.py` 扩展。

**代价/不可逆点**：纯记账与证据增强，不改判定门；pool_size 预算乘数既有。无不可逆变更。

### V3 可进化面 schema（「填空式」表示的工程化）

**做什么**：把「哪些面可进化」从隐式标量（max_skill_size 等）升级为显式 schema：每个面有
名称/类型/接口约束/大小预算/适用闸门清单；变异器按面出题、约束闸按面校验、提案按面记录。
首期仍只有 4 类文本面（行为不变），为后续把**声明式阶段内策略**（重试/回退策略、条件追加调用、
预算 spending 政策——即论文 budget_gate 的本仓对应物）纳入可进化面铺路。**不开放任意代码进化**；
代码级仍走既有 ACTION_DEFINITION 人工提案通道。

**影响面**：`eval/constraints.py`、`eval/mutator.py`（:56 起）、`eval/exec_suite.py:60`
（工件类型清单）、`service.py`（提案 schema）、前端提案详情、新守卫测试。

**代价/不可逆点**：首期零行为变化（纯结构化重述）；后续扩面逐面评审、逐面带闸。无不可逆变更。

### V4 成分归因读数（指令 vs 策略/代码 增益分解）

**做什么**：借鉴论文的成分交换实验，在提案/运行审计中增加「相对基线的增益分解」读数：
本轮胜者相对 incumbent 的提升中，指令面与（未来）策略/代码面各贡献多少、各自成本差多少。
文本-only 阶段先落「指令增量 + 成本增量」双轴读数，为将来扩面预置尺子。

**影响面**：`service.py`（提案字段 :932-967）、`runner.py`（结果聚合）、`cost_ledger.py`（按臂读数
已有，补归因口径）、前端提案详情、测试。

**代价/不可逆点**：只增读数不改判定；无不可逆变更。

### V5 Pareto 可部署工件打包（HarnessPro 档已登记残差）

**做什么**：把 champion 与 `pareto_variants` 打包为版本化工件（正文 + 档位 + 成本指纹 + 证据指针
+ journal commit 号），支持导出/按工件回滚，衔接既有 `adopt-variant` 单点采纳。

**影响面**：`service.py`、`eval/skill_journal.py`、`api/endpoints/text_evolution_api.py:674-692`、
前端、测试。

**代价/不可逆点**：工件只增不删；回滚沿既有 journal 机制。无不可逆变更。

### V6 部署形态成本差进提案

**做什么**：提案新增「部署成本差」读数：胜者相对 incumbent 的每任务调用数/token 增量（来自评测臂
实测，非文本长度代理），让审批人直接看到运行时代价——对应论文「进化后 harness 调用数 0.996→1.963」
的披露纪律。

**影响面**：`cost_ledger.py`（按臂汇总已有）、`service.py` 提案 schema、前端审批面板、测试。

**代价/不可逆点**：只增读数；无不可逆变更。

### 优先级建议

V1+V2 同批（一个机制的两半：修复通道 + 分支账本）＞ V6（小、纯增读数、审批即用）＞
V4 ＞ V3 ＞ V5。V3 是扩面前置，若近期不打算扩可进化面可暂缓。

---

## 4. 不建议照搬的部分

1. **六阶段管线与条件细化逻辑**：视频域特化（时间线采样、区间占比异常检测、起止坐标取中位数），
   与本仓 chat_pipeline/hooks 面不同构；借结构纪律，不搬管线。
2. **自动改写阶段内代码**：论文自己证明代码进化收益不稳定且调用翻倍；本仓代码级走人工提案
   通道（ACTION_DEFINITION 有黑名单校验与审批面）是更稳妥的形态，无需为「自动改代码」补课。
3. **60 slot × 20 轮的搜索规模**：217,767 次 solver 调用的搜索成本属论文级实验预算；本仓预算闸、
   核选、成本 tiebreak 已把搜索成本管住，不应放大预算去追论文规模。

---

## 附：信息来源

- 论文：arXiv 2610.01766（v1，2026-10-01）；代码 github.com/bingjunluo/VideoEvolve。
- 触发文章：BuddyMe 公众号《别再手动调 Harness 了：让框架自己进化自己》。
- 本仓事实：`neurova/evolution/` 代码与 `tests/unit/evolution/` 守卫现读
  （runner.py/service.py/mutator.py/cost_ledger.py/failure_analysis.py 等，行号绑定 2026-11-14 工作树）；
  既有对照档 `harnesspro_vs_neurova_cost_aware_harness_rsi_comparison_2026-11-13.md`。
