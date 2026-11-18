# Harness² 与 Neurova 代码级对比（2026-10-21）

> **性质声明**：本文属 `docs/INDEX.md` §2.4「竞品/外部对标」——**研究参考，仅作背景，不可作为本仓设计的事实源或对齐依据**（`AGENTS.md` 协作红线：外部项目只作功能依赖或背景登记，不引入其设计标准）。文中任何候选若要落地，一律按本仓修复教义独立立项（先红后绿），本文不构成对齐承诺，也不授权搬运外部代码或提示词。
>
> **对比对象**：`google-research/harness2`（Apache-2.0，shallow clone @ commit `1cfe254e8d25b15f37048c3730134686abe60335`，2026-10-13；抓取日 2026-10-21）。`third_party/` 下的 benchmark、runner 与数据另按其上游许可证，见其 `dependencies/README.md`。
>
> **方法**：两侧独立代码细读；证据一律 `文件:行号`。外部仓行号绑定上述 commit；Neurova 行号绑定抓取日工作树，后续会漂。评分为加权主观评定，依据逐条附后。外部仓在本机（Windows 10.0.26200，Python 3.12.10）实跑 demo **失败**：`ModuleNotFoundError: No module named 'fcntl'`；本机无 WSL，故其动态行为以代码与文档为准，凡未实跑处均已标注。
>
> **阅读对象**：`neurova/evolution/`、`neurova/context/`、`neurova/skills/` 的维护者。

---

## 0. 结论摘要

- **一句话画像**：Harness² 是一个**研究型 harness 优化器**——把 prompt、护栏、记忆、工具指引、子代理、技能、脚本、插件当成可编辑的组件树，用「提议—探测—合成」的对照实验在固定模型权重下改进它，并靠证据隔离、盲选、预算恒等式和运行指纹保证结论可审计。Neurova 是一个**生产型智能体平台**——自改进的重心在参数调优、技能文本进化和治理门禁，平台面（记忆、多智能体、渠道、沙箱、MCP、前端）远比前者宽；当前技能文本链已统一到单一 service，并接入完整工具 trace、域级 harness 检索与跨域 UI，C8 可编辑面仍未开放。
- **评分（十维加权，以自改进方法为中心，口径见 §4）**：**Harness² 7.8 / 10，Neurova 8.2 / 10**。权重合计 100%（方法 70% + 工程 30%）；若换成「统一生产级标尺」（测试 15% + 生产安全 50% + 可复现 15% + 平台化 20%），Harness² 约 **4.3 / 10**、Neurova 约 **8.4 / 10**——两者不是同类产物，综合分只在声明口径下有意义。
- **最重要的三个判断**：
  1. **Harness² 赢在「证据制度」，不是赢在代码量**。它 12,747 行 Python（其中 4,170 行是 benchmark 适配），另有 2,591 行 third_party；核心方法只有约 5,700 行，却把「证据从哪来、谁能看、看完怎么选、选完怎么记账」全部钉成结构。Neurova 的进化域约 19,509 行，能力面更宽；当前已把技能改进统一到单一 service，并补上失败全量证据、逐工具 trace、域级 harness 检索与跨域 UI。
  2. **Harness² 的方法不能整体搬，但它的四条纪律可以直接借**：① 编辑必须有行为探测，不能只改文本；② 改进证据要落到可读的文件工件，不能只剩截断摘要；③ 采纳与评分要分离，评分器不应同时当选择器；④ 每轮候选、每次调用、每个断点都要有恒等式或指纹，否则「账上有、实际没发生」无法被发现。
  3. **Neurova 有一批 Harness² 没有的硬资产**：三态门禁（`unevidenced` / `failed` / `passed`）、真留出集与噪声带、六类泄漏审查、版本单调与回滚修订、确定性 9 用例行为地板、记忆/技能市场/多智能体/沙箱/渠道/i18n。这些不应为了「像 Harness²」而退让；对照的价值是补短，不是换轨。

- **明确不建议照搬**（详见 §5.4）：POSIX-only 的 `fcntl` 锁、`--dangerously-skip-permissions`、无沙箱执行自生成脚本、把单次 rollout 当采纳证据、用 LLM 盲选替代真值判分、直接搬外部 benchmark 代码与提示词。

### 0.1 当前状态摘要

- **闭环**：自动技能改进统一走 `SkillEvolutionService`；`auto_apply_skill_evolution` 默认关，过门先产 pending，显式开启才自动应用。旧自动反射分支已退役。
- **证据**：失败与成功执行都落全量证据（输入/输出/错误/元数据/上下文/逐工具 trace，单字段 50k、失败 100 份/成功 20 份、写入前脱敏）；小产物复制进证据包，大产物保留路径 + SHA-256 清单；失败证据经 `extra_failures` 与 `JudgeFailure.tool_trace` 进入变异器，成功证据经审计端点可读。
- **选择与复现**：主 runner 近平分匿名 A/B tie-break（无选择器回退 argmax）；judge 不可用时默认转确定性可用性回退门，提案强制人工复核、自动审批拒绝；实验指纹进噪声缓存、编辑台账、锚过滤、审批基线与作业身份；混配置拒绝并重跑。
- **执行面**：API 默认取 **auto**——agent 在线且预算允许时走真臂，离线或超预算回落模拟面并在响应标注 `real_trajectory_fallback`；显式 `true` 仍严格 409/422，显式 `false` 强制模拟。
- **域级复用**：既有技能库上提供 `skillDomain` / `listDomainHarnesses` / `searchDomainHarnesses`；跨域 API 与 AgentSkillPage 域级 harness 面板已接；自动路径与 `/evolve` 把同域 harness 注入变异器。
- **当前残留**：C8 可编辑面未开放（2026-10-21 已拍板：维持不开放）；常驻面只有软告警，无强制上限（2026-10-21 已拍板：维持软告警）；大产物（>2MB）保留路径 + SHA-256，不复制内容；N8 采纳页仍是基础版。N8 独立采纳流已接：域 harness → pending 提案 → 人工批准写回目标技能。
- **验证**：`tests/unit/evolution` **1675**、`tests/unit/skills` **1199**（2 skipped）、相关 API 定向 **43**、前端 **74** + `vue-tsc` 全绿；活体 `JUDGE_FALLBACK_LIVE_OK`、`EVIDENCE_LIVE_OK`、`EVIDENCE_HTTP_LIVE_OK`。外部仓 Harness² 未实跑（本机无 Linux/WSL，`fcntl` 失败），评分沿用静态+进程内探针口径。

---

## 1. 公平性前提：两者不是同一个问题

| | Harness² | Neurova |
|---|---|---|
| 问题域 | **离线研究**：在 3 个职业基准上验证「递归 harness 优化」方法是否涨分 | **生产常驻**：对话驱动的智能体平台，进化是后台能力之一 |
| 改什么 | 模型权重冻结；只改 **c1–c8 组件树**（提示、护栏、记忆文件、工具指引、子代理、技能、脚本、插件） | 参数（setpoint 步进）、技能正文/描述、工具权重；不产代码、不改模型权重 |
| 判据 | 基准的 judge 分；但**方法本身不看 judge**，用行为对照与盲选 | 内部确定性评测、LLM judge、留出集、治理门禁、人工审批 |
| 执行面 | OpenCode / Codex 外部执行器；网络不受限，Codex 沙箱关闭 | 进程内 agent + 沙箱 + 工具层 + 多渠道路由 |
| 失败代价 | 一次 benchmark 跑贵，可重跑 | 生产行为漂移、用户可见、需回滚与审计 |
| 规模 | 12,747 行 Python + 2,591 行 third_party，5 个测试用例 | 346,580 行 Python，473,498 行测试 |

因此本文的评分口径是：**按「自改进/harness 优化」这一共同交集评分，不按产品总体规模评分**；生产就绪度单列，不混进综合分。跨域可迁移的启发放 §5。

---

## 2. Harness² 代码级解剖

### 2.1 流水线与数据流

一次任务（`harness2/core/schedule.py:566` `run_task`）的完整顺序：

1. **基准执行**：`k` 次 base rollout（`recursion.py:343` 并行模式 / `:452` 顺序模式共用）。
2. **证据树**：`context.build()` 把任务、完整轨迹、交付物、当前 harness、候选池、同域经验库写到磁盘（`context.py:105`），提示里只放一个短指针（`context.mission()`，`context.py:521`）。
3. **提议**：INV（怎么工作）与 DOM（领域知识）两个维度各自编辑 `context/harness/`；编辑即提案，未触碰的文件继承（`prompts.py:347` / `:372`，`tree.py:15`）。
4. **校验**：`tree.validate()` 检查 always-on 上限、技能 frontmatter、技能是否被常驻文本点名、脚本是否可编译、脚本引用是否存在、hooks 结构（`tree.py:336`）；adapter 再加基准特有约束（`spec.py:242`）。
5. **探测**：每个候选 harness 跑一次 rollout（`recursion.py:260` `_roll`），失败记录为证据而非抛错。
6. **合成**：并行模式从 2k 个候选中产出 k 个最终 harness（`recursion.py:343`）；顺序模式逐轮 checkpoint（`:452`）。
7. **盲选**：只把 k 个 final 放进选择池，匿名化、去掉来源，选择器只读交付物（`selection.py:268`、`:71`）。
8. **判分**：选择**之后**才调用 benchmark judge（`judge.py:15` 明确「方法不 import 本模块」；`spec.py:247` 注明 judge 只在选择提交后调用）。
9. **反思**：`reflect_adoption()` 用完整改进记录蒸馏一条可迁移经验（`selection.py:402`、`prompts.py:1105`），写入同域经验库（`library.py:106`）。
10. **记账**：`Ledger.assert_identity()` 要求 R=4k、P=3k 且无重复标签（`ledger.py:89`）。

这条链的关键不是「LLM 改提示」，而是**每一步都有可核对的落点**：编辑落在文件树、证据落在磁盘、选择落在匿名 id、判分落在选择之后、经验落在同域库。

### 2.2 模块地图与规模

| 层 | 文件 | 行数 | 职责 |
|---|---|---:|---|
| 方法核心 | `core/tree.py` | 427 | c1–c8 树读写、校验、diff、多样性 |
| | `core/context.py` | 546 | 证据树构建、答案键/评分器泄漏护栏 |
| | `core/prompts.py` | 1,163 | 全部提示词；基准文本只作值，不作分支 |
| | `core/proposer.py` | 534 | 提案器会话、审计、缓存、工作区收割 |
| | `core/recursion.py` | 578 | 并行/顺序两种递归 |
| | `core/selection.py` | 505 | 匿名分配、盲选、采纳反思 |
| | `core/library.py` | 222 | 同域经验库 |
| | `core/schedule.py` | 850 | 命名空间、流顺序、驱动、续跑 |
| | `core/ledger.py` / `judge.py` / `report.py` / `runmark.py` / `spec.py` | 132 / 155 / 165 / 115 / 277 | 预算、判分、汇总、运行指纹、协议 |
| 执行基座 | `substrate/opencode.py` / `codex.py` / `base.py` | 395 / 480 / 83 | 两种外部执行器的安装、权限、轨迹渲染 |
| 基准适配 | `benchmarks/jobbench.py` / `lab.py` / `workbuddy.py` 等 | 4,170 | 仅适配，不含方法逻辑 |
| CLI / 装配 | `cli/*`、`config.py`、`preflight.py`、`install.py`、`demo.py` | 1,897 | 入口、依赖钉死、预检、确定性 demo |
| 测试 | `tests/test_workflow.py` | 229（5 个用例） | 关键契约回归 |

> 口径：上表方法核心 5,688 + 执行基座 992 + 基准适配 4,170 + CLI/装配 1,897 = **12,747**；测试 229 行**另计**，third_party 2,591 行也另计。

设计上值得注意的三点：

- **方法 / 基座 / 基准三轴分离**：`spec.py:15-20` 明确 method、substrate、benchmark 各自独立；基准必须提供 `BenchSpec` 值 + `BenchmarkAdapter`（`spec.py:200-250`），核心只依赖 `SubstrateLike`（`spec.py:190`）。换基准不改方法代码。
- **提示词是数据，不是分支**：`prompts.py:15` 声明「benchmark 文本以值到达，绝不以分支到达」；`BenchPrompts` 在构造时拒绝 `benchmark/evaluation/grader/rubric/score` 等字样（`spec.py:111-126`），防止把评分语汇带进提案面。
- **单一事实源**：命名空间只有 `ns()` 一个构造器（`schedule.py:111`）；选择池只有 `selection_pool()` 一个构造器（`selection.py:93`）；流顺序只有 `stream_order()` 一个构造器（`schedule.py:130`）。

### 2.3 八个可编辑组件与两种执行基座

Harness² 把 harness 拆成 8 个可编辑组件（README:70-73；OpenCode 面见 `substrate/opencode.py:42-88`，Codex 面见 `substrate/codex.py`）：

| 组件 | OpenCode 路径 | Codex 路径 | 运行时成本 |
|---|---|---|---|
| system prompt | `systemprompt.md` | `AGENTS.md` | 常驻 |
| guardrails | `guardrails.md` | `AGENTS.md`（合并） | 常驻 |
| memory | `LongTermMEMORY.md` | `AGENTS.md`（合并） | 常驻 |
| tool guidance | `tool_descriptions/tool_guidance.md` | `AGENTS.md`（合并） | 常驻 |
| skills | `skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` | 按需 |
| subagents | `sub_agents/<name>/AGENT.md` | 同左 | 独立上下文 |
| scripts | `scripts/<name>.py` | 同左 | 按需执行 |
| plugins / hooks | `plugin/<name>.ts` | `.codex/hooks.json` | 工具循环内 |

OpenCode 的 always-on 上限是 24,000 字符（`substrate/opencode.py:50`），理由是「每个 token 都在和 agent 的输出预算竞争」（`:51`）。提示词里给出了明确的成本阶梯：**技能 > 脚本 > 子代理 > 插件/钩子 > 常驻文本**（`prompts.py:134-146`、`:242-255`），并反复强调「常驻 prose 是最贵的选择」。

### 2.4 关键机制逐条

#### 2.4.1 证据是文件，不是提示

`context.py` 顶部（`:15-26`）直接列出证据树布局：`task.md`、`rollouts/<label>.md`（完整轨迹，不做提示预算截断）、`deliverables/<label>.md`（用 judge 同一个抽取器读出的交付物）、`harness/<rel>`、`library/INDEX.md`、候选池。`mission()` 只给一个短指针，要求模型自己打开文件（`context.py:521-546`）。

**启发点**：证据的**保真度**由磁盘保证，而不是由提示预算保证。Neurova 的技能改进目前拿到的是 `input_summary/output_summary` 摘要，且采集端根本没填（见 §3.5 N2）。

#### 2.4.2 编辑契约：没改就是继承

`tree.py:15-20` 定义「omitted-is-inherited」：提案只写它改的文件，未触碰的自动继承；删除文件即删除组件。`write_tree()` 会清掉可编辑面上的旧文件但保留面外文件（`tree.py:156-185`），`normalize_rel()` 拒绝 `..` 与绝对路径（`:82-89`）。这让「提案」与「当前 harness」之间只有一份 diff 语义。

#### 2.4.3 校验先于付费：不合格的提案整棵丢弃

`tree.validate()`（`tree.py:336-390`）在 rollout 之前跑，检查：

- always-on 是否超上限（`:350-354`）；
- 技能 frontmatter `name` 是否与目录一致、`description` 是否存在（`:267-298`）；
- 技能是否被常驻文本点名（未被点名的技能「永远不会被打开」，`:292-297`）；
- 脚本是否可编译（`:254-264`）；技能引用的脚本是否随提案一起交付（`:317-334`）；
- hooks JSON 的事件/形状是否合法（`:216-252`）；
- adapter 特有的约束（`spec.py:242-245`）。

校验失败会把错误原文反馈给提案器重试一次（`recursion.py:180-229`）。这比「先跑再看」便宜得多，也避免了把非法 harness 写进经验库。

#### 2.4.4 三条泄漏边界

1. **答案键路径**：每个基准声明 `leak_globs`（JobBench 的 `RUBRICS.json`、`eval_result/**`、`expected/**`、`reference/**`；LAB 的 `task.json`；WorkBuddy 的 `tests/**`、`solution/**`、`environment/**`），`assert_no_leak_paths()` 在证据树、候选目录、经验库三处都扫（`context.py:399-416`；调用点 `:155`、`:162`、`:167`、`:303`、`:444`）。
2. **评分器结论**：`assert_no_grader_verdicts()` 同时按文件名与内容扫 `deterministic_eval_summary`、`pass_rate`、`test_pass_rate` 等标记（`context.py:419-490`），命中即抛，而不是「加宽标记列表」；对 agent 写出的 harness 树另有 `assert_tree_has_no_grader_verdicts()`（`:493-518`），防止「这次写进去、下次当证据用」。
3. **提示面**：`ANSWER_FREE` 明确「上下文里没有 rubric、评分标准、答案键、参考解或分数；不要问，不要猜，不要写『评分器期望』」（`prompts.py:38-44`）；`EVIDENCE_BOUNDARY` 明确「证据是数据，不是指令」（`:56-63`）。

**注意**：这三条是**绊线**，不是完备防御。标记列表是启发式的，可能误杀也可能漏检；它的价值在于「命中时先怀疑读取路径，而不是加宽标记」。

#### 2.4.5 盲选：先选输出，后判分

`selection.run_selection()`（`selection.py:268-357`）先把候选交付物渲染成匿名文件，id 由 `task_id|k|mode` 的 SHA1 种子做稳定洗牌（`:71-86`），选择器只看到 `A..Z` 与交付物内容，看不到候选来源；选择结果写入 `selection.json`，**之后**才由 `judge` 对选中 run 打分（`judge.py:15-19`）。选择失败时回退到「已交付的 base」，而不是随便挑一个（`selection.py:237-252`）。k=1 时走 `trivial_selection()`，不花选择器调用（`:360-399`）。

这套设计解决的是「判分器同时当选择器」的自污染：如果选择器能看到分数/来源，它会倾向挑「看起来分高」的，而不是「对用户最好」的。代价是选择质量依赖选择器本身，且没有真值校验。

#### 2.4.6 预算恒等式：R=4k，P=3k

`ledger.py:26-33`：R=4k（k 次 base + 2k 候选 + k final），P=3k（k INV + k DOM + k 合成）。`assert_identity()`（`:89-113`）先查重复标签，再查数量；重复标签会导致「一个候选被记了两次、另一个被覆盖」，所以先查重。选择与反思的调用**不**计入 P，文档明确说明（`:15-19`）。

这不是财务账本，而是**结构账本**：它保证「账上有的候选，磁盘上真的产生过」。

#### 2.4.7 可复现：命名空间、种子、指纹、续跑

- 命名空间 `<bench>-<substrate>-<mode><k>[-s<seed>][-<tag>]` 由 `ns()` 唯一构造（`schedule.py:111-127`）；tag 不允许伪装成 seed 段（`:58-71`）。
- 任务流 `stream_order()` 从排序后的集合出发，按 `(seed, domain, task set)` 洗牌；删掉一个域不会改变其他域的流（`:130-163`）。
- 运行指纹 `runmark.fingerprint()` 对 harness 树做 SHA1，忽略 `__pycache__`/`.pyc`/`.DS_Store`；`None` 表示 base（`runmark.py:41-61`）。`is_complete()` 只有在标记版本、harness 指纹都匹配时才复用（`:91-102`）。
- 实验身份 `config.json` 记录 method version、执行器/改进器/judge 模型、项目、区域、端点、split、任务流、seed；不一致就拒绝复用（`cli/run_sweep.py:209-235`）。
- 断点续跑 `_resume()` 会校验选中 run 目录、交付物、harness 树、指纹，任何一项缺失就重跑（`schedule.py:350-421`）。

#### 2.4.8 诚实读数：None 不是 0，未判分不进分母

- judge 失败返回 `None`，不是 0；`Scored.graded` 区分「判分成功」与「得分高低」（`judge.py:45-53`）；未判分的行从分母排除（`report.py:80-111`）。
- 报告在 k=1 时明确提示：并行与顺序在 k=1 是同一过程，差值只是噪声地板（`report.py:122-131`）。
- 报告对「模式自己的 final 很少被选中」「base 被选中的比例过高」「stage 回退」「混合评分单位」逐项告警（`report.py:133-165`）。
- `KEEP_BASE` 被明确写成「真实答案，不是失败」（`prompts.py:333-335`；合成提示 `:748-749`）。

#### 2.4.9 提示工程：成本阶梯与「交付物形状不属于 harness」

- 组件选择顺序：技能（有触发点）> 脚本（确定性操作）> 子代理（大输入小输出）> 插件/钩子（工具循环内、不可跳过）> 常驻文本（最后，且要「加一句就删一句」）（`prompts.py:134-146`、`:242-255`）。
- 技能必须有触发行，否则「永远不会被打开」（`tree.py:292-297`；提示词 `prompts.py:151-158`）。
- 交付物的形状属于请求，不属于 harness；不得为了「让审阅者看得清楚」而加列、改名、加解释（`prompts.py:169-177`、`:268-276`）。
- `GENERALIZE` 要求把「本工作区已验证的事实」写进 harness，而不是只写「如何重新发现」；但事实必须打上「in this workspace」标签，且不得把本任务事实写进持久记忆（`prompts.py:295-330`）。

### 2.5 代码级弱点与边界

| 发现 | 证据 | 影响 |
|---|---|---|
| 测试极薄 | `tests/test_workflow.py` 229 行、5 个用例；覆盖预算/续跑、证据/库前缀、非法提案重试、NO_ENTRY、选择失败不判分；未覆盖 tree/context/selection/prompts 的细粒度边界 | 研究原型可接受；生产移植不可接受 |
| POSIX-only | `schedule.py:294` 直接 `import fcntl`；本机 demo 实测 `ModuleNotFoundError`；README 要求 Linux | 不能直接在 Windows 生产环境跑 |
| 无沙箱、网络不受限 | README:166-171 明示「Executor network access is unrestricted, and Codex runs with its sandbox disabled」；proposer 用 `--dangerously-skip-permissions`（`proposer.py:214-220`） | 研究环境可接受；生产不可接受 |
| 单候选单 rollout | `recursion.py:260-300` 每个候选只跑一次；提示词自己承认「单次结果两边都是弱证据」（`prompts.py:922-931`） | 证据噪声大；选择器可能被一次偶然结果带偏 |
| 死字段 | `RunView.cost_usd` / `wall_s`（`spec.py:185-186`）在全部构造点（`recursion.py:281`、`:290`、`schedule.py:425`、`:449`、`:466`）均未赋值 | 成本/墙钟读数缺失；不影响主链 |
| 泄漏绊线是启发式 | `GRADER_VERDICT_MARKERS` 固定字符串（`context.py:419-427`） | 可能误杀合法文本、也可能漏检新格式 |
| 选择无真值校验 | 选择器只读交付物，没有 judge 参与选择 | 选择质量不可证；k=1 直接跳过选择 |
| 基准/执行器绑定深 | `third_party/` 2,591 行 + 3 个 benchmark 适配 4,170 行；依赖外部 checkout 与凭证 | 复现成本高，跨基准迁移需重写 adapter |

**结论**：Harness² 的代码质量高在**边界与契约**，不高在测试与生产化。它是一份「方法说明书 + 可跑的实验装置」，不是可直接嵌入产品的库。

---

## 3. Neurova 对应面

### 3.1 两条自改进链，共用一个技能文本 service

Neurova 的 `neurova/evolution/` 约 19,509 行，当前有两条自改进链：

| 链 | 入口 | 改什么 | 判据 | 是否自动生效 |
|---|---|---|---|---|
| 参数 RSI | `post_chat_pipeline.py:847` 注册后台步骤；`:3179` `run_iteration` | 四族数值参数（tool_memory / sleep / emotion / experience） | 确定性 9 用例 `eval_harness.py`（`:328-395`）+ setpoint 步进 + 回滚 | 是（阶段允许时） |
| 技能文本进化 | 自动：`post_chat_pipeline.py` `run_skill_evolution_pass`；人工：`text_evolution_api.py:164` `/evolve` | 技能正文 `context_template` | 同一个 `SkillEvolutionService`：留出集 + LLM judge + 约束/泄漏/bench 门 | 自动入口受 `auto_apply_skill_evolution` 控制（默认关）；人工入口产 pending（`:413`） |

参数 RSI 的链路是完整的：收集信号 → 收敛分析 → 生成候选 → 应用 → 前后实测 → 回滚判定 → 指标/阶段门（`rsi/orchestrator.py:417-700`）。它的确定性评测集明确区分 `measured` 与 `measurement_blind`，全部用例无证据时返回 `score=None`（`eval_harness.py:356-395`）；增益只在两侧都 `measured` 时才算数（`orchestrator.py:485-500`）。这套「三态诚实」比 Harness² 的 `None≠0` 更细。

技能文本的自动/人工入口已收口到同一个 service；参数 RSI 与技能文本仍各有一套判据，这是两条不同对象层的链，不是同一功能的第二份实现。

### 3.2 评估链的真实性

- 默认执行器是 `SimulatedAgent`：只把「技能正文 + 任务」拼成一次 LLM 调用，无工具、无上下文、无多轮（`eval/service.py:60-90`）。
- 真臂执行器存在（`ab_library.py:46-96`、`TextArmAgentExecutor`），API 默认已改为 **auto**：agent 在线且预算允许时走真臂；离线或超预算回落模拟面，并在响应标注 `real_trajectory_fallback`；显式 `real_trajectory=true` 仍严格 409/422，显式 `false` 强制模拟（`text_evolution_api.py:161`、`:252`）。
- 评测集有 train/val/holdout/heldout 四段（`eval/dataset.py:44-72`），接受阈值取 `max(min_improvement, noise_band.delta)`（`runner.py:541-560`）；judge 不可用默认转确定性可用性回退门（只判非空/无异常标记），提案强制人工复核（`runner.py:649-668`、`service.py:784`）。
- 泄漏审查在约束闸之后、tune 评测之前（`runner.py:600-637`）；留出集只做验收证据（`:649-660`）。
- 选择在 top 两候选近平分（分差 ≤ `max(min_improvement, 0.02)`）时走**匿名 A/B**：只读产物、不暴露来源，读数写入 `blind_tiebreak`；其余仍按 **tune 分 argmax**、严格大于才替换（`runner.py:486-500`、`:639-648`）。没有选择器时诚实回退 argmax。

### 3.3 上下文组装与「可编辑面」

Neurova 的系统提示在 `context/orchestrator.py:1188-1225` 组装：soul / personality / constitution / 时间 / `rules_sections` 恒定规则 / 工作区 `AGENTS.md` 文档树 / 技能目录 / behavior_rules + tools_desc。工具描述走 `get_tools_description()`（`:2891`），技能目录走 `_skill_catalog_section()`（`:2644`），工作区文档走 `workspace_docs.collect_workspace_docs()`（16KB 预算，`workspace_docs.py:27`）。

现状：

- **没有「可编辑组件树」概念**。`rules_sections.py` 的规则是代码常量；工具指引在代码里；`constitution` 是构造参数；soul/personality 是工作区文件；技能来自注册表；subagent/plugins 各自独立。全仓搜索没有把 prompt/guardrails/memory/tool guidance/skills/scripts/plugins 作为一个统一树来读写/校验的模块。
- **没有受控的自改 prompt 通道**：`save_agent_soul`（`agent_config.py:311`）在生产代码中零调用，只有测试调用；正常路径上 Agent 不改写自己的 prompt/guardrails。
- **但存在一个隐式可写面**：工作区 `AGENTS.md` 会被注入 system prompt（`workspace_docs.py`），而文件写入工具对绝对路径不做沙箱限制（`skills/builtin/file_operation_executor.py:60-76` 明确「绝对路径保留原行为」）。若 Agent 具备写权限，它可以间接改常驻文本；目前没有专门的编辑契约、预算总账与校验。
- **预算分散**：技能目录 8,000 字符（`orchestrator.py:2685`）、工具描述 18,000 字符（`:2896`、`:3102-3114`）、工作区文档 16KB（`workspace_docs.py:27`）；没有一份「本 agent 常驻文本总预算/分段占用」的统一读数。

### 3.4 Neurova 相对 Harness² 的硬资产

这些不是「对方没有所以我们要有」，而是**本仓已有且更强，不应在对照中丢掉**：

| 能力 | 证据 |
|---|---|
| 三态门禁 | `rsi/gate_verdict.py` 的 `passed/failed/unevidenced`；`eval_harness` 的 `measured/measurement_blind`；`orchestrator.py:600-640` 只在 `failed` 时计连续失败 |
| 留出集/真留出/噪声带 | `eval/dataset.py:44-72`；`runner.py:541-560`；`calibration.py` 的噪声带缓存 |
| 六类泄漏审查 | `eval/leak_critic.py:1-30`：task_specialization / degenerate_noop / safety_mechanism_removal / judge_gaming / undeclared_scope_drift / cross_session_memory_leak；确定性预检恒开，LLM 层默认关 |
| 回滚与修订 | `skill_improver.py:504-640` 的 revision 快照/版本单调/落盘失败回滚；`rsi/rollback_manager.py` |
| 确定性行为地板 | `rsi/eval_harness.py:328-395` 四族 9 用例，零 LLM、纯内存 |
| 记忆/技能市场/多智能体/沙箱/渠道/i18n | 本仓平台面，Harness² 不涉及 |
| 测试规模 | 473,498 行测试 vs 346,580 行源码；本次抽跑 `test_rsi_orchestrator` / `test_skill_improver_reflective` / `test_service_closed_loop` 共 21 项全绿 |

### 3.5 对照后发现的本仓断点（每条带证据）

> 以下断点是**本仓自身可核实的缺口**，不是「Harness² 有所以我们要有」。按 `AGENTS.md` 核心原则第 7 条，每条都写清影响面。

**N1｜两条技能改进路径分裂，自动路径的 LLM 改写「只写不读」**
- 自动路径：`post_chat_pipeline.py:2848` → `run_skill_evolution_pass`（`:236-262`）→ `skill_improver.apply_improvement`（`skill_improver.py:504`）。
- 反射式改写：`propose_pending_improvements_async` 把 `ReflectiveMutator` 产出的正文放进 `changes["improved_text"]`（`skill_improver.py:499`）。
- 但 `apply_improvement` 只把 `changes` 存进 `revisions`，经验写入读的是 `suggested_fix`/`description`/`reason`（`:640-650`），**没有读取 `improved_text` 去改 `context_template` 或技能正文**。全仓 `improved_text` 的另一处消费在人工审批路径 `eval/service.py:810`（批准时写回 `context_template`）。
- 影响面：自动路径即使开了 `NEUROVA_TEXT_EVOLUTION`，LLM 改写也不会生效；真正影响行为的只有「经验积累 → `rebuild_skill` 改描述」这条慢链。自动改进因此更像「记账」，不是「改行为」。
- 与 Harness² 的对照：Harness² 的提议、探测、合成、采纳在同一个 `run_mode` 里完成，编辑结果就是下一步 rollout 的输入；没有「写了但没人读」的中间态。
- **落地状态（当前）**：已修复。旧自动反射分支退役；自动路径统一走 `SkillEvolutionService`。`auto_apply_skill_evolution` 默认关：过门先产 pending，显式开启才由 `service.decide(..., approver="auto:evolution")` 写正文。

**N2｜执行证据缺输入/输出，反思拿到的是空摘要**
- `AutoSkillImprover.record_usage()` 接受 `input_summary` / `output_summary`（`skill_improver.py:194-232`），但装配点 `agent_core.py:1573-1602` 只传 `skill_id/success/duration/error_message/metadata`，**不传输入输出**。
- 反射式改进因此构造 `JudgeFailure(task_input=r.input_summary or "(未记录输入)", output=r.output_summary or "(无输出)")`（`skill_improver.py:473-478`）。
- 影响面：LLM 反思看不到「用户给了什么、技能产出了什么」，只能看错误字符串；这直接削弱了改进质量，也使「按证据判断」退化为「按错误关键词猜」。
- 与 Harness² 的对照：Harness² 的证据树把完整轨迹、交付物、源码材料都落到磁盘，提示只给指针（`context.py:15-26`、`:521-546`）；它明确不让提示预算决定证据保真度。
- **落地状态（当前）**：已修复。`execute_skill` 把 `params/context` 传给后置事件；技能边界建工具 trace 缓冲，`ToolExecutor`/`ToolRouter` 中央点记录工具名/参数摘要/成败/错误/耗时/顺序/**产物引用**；失败与成功都落全量文件（单字段 50k、失败 100 份/成功 20 份、写入前脱敏），小产物（≤2MB、最多 5 个/10MB）复制进证据包，大产物保留路径 + SHA-256 清单；trace 经 `JudgeFailure.tool_trace` 进入变异器「工具轨迹」段，成功证据经审计端点可读。

**N3｜自动技能改进没有行为探测/留出验证**
- 自动路径在应用前只过 `SkillService._quality_gate` 的四道结构闸：内容非空、版本单调、名述自洽、评审闸（`skill_service.py:1229-1270`）；没有「base vs 候选」的行为对照。
- 强制行为验证的 `SkillEvolutionService` 只在 `/evolve` API 路径（`text_evolution_api.py:164`），产出 pending，人工批准（`:413`）；自动路径不经过它。
- 影响面：自动改进可能把「读起来更合理」但行为更差的文本写进技能；现有回滚只能事后救，不能事前拦。
- 与 Harness² 的对照：Harness² 每个候选先 rollout 再合成，且合成提示要求「若任何关联 rollout 没产出，必须显式说明并视为不安全」（`prompts.py:928-931`）；它的采纳依据是行为差异，不是文本自证。
- **落地状态（当前）**：已修复。自动路径走 `SkillEvolutionService.evolve` 的 holdout/案例/成本/泄漏门；历史失败证据作为 `extra_failures` 进入变异器；无 golden 数据集不生成文本。执行面默认 auto：真实轨迹优先，离线/超预算回落模拟面并标注原因；judge 不可用时走确定性可用性回退门，提案强制人工复核。

**N4｜候选/调用没有结构恒等式，只有成本规则**
- 参数 RSI 有候选生成/剪枝指标（`orchestrator.py:939-990`），有 `cost_history` 与 ROI（`convergence_analyzer`），但没有「预期候选数 = 实际评估数 = 实际应用数」的恒等式，也没有重复标签检查。
- 评测侧有 `history_ledger` 与 `attributed_hit_rate`，但没有 Harness² 的 R=4k/P=3k 这类「账上有的，磁盘上真的发生过」断言（`ledger.py:89-113`）。
- 影响面：候选被覆盖、评估被跳过、应用只成功一半等「账实不符」只能靠人看日志发现。
- 与 Harness² 的对照：Harness² 先查重再查数，重复标签会被判为「一个候选被覆盖、另一个从未产生」。
- **落地状态（当前）**：已修复。`EvolutionRunResult.assertCandidateIdentity()` 断言「生成 − 预检拒绝 = 评估 = 轮次」；RSI 参数轮新增 `assertRsiOptimizationIdentity()` 与 `assertRsiRoundIdentity()`（参数唯一、一参数一结果）。残留：评测侧重复候选只计数不致命，未做 Harness² 式重复标签硬断言。

**N5｜没有实验身份指纹，续跑/缓存可能混配置**
- 技能有版本号与修订哈希（`skill_improver.py:579-620`），job queue 有幂等键与租约恢复（`evolution/job_queue.py`），但评测缓存/续跑没有把「技能正文 + config + 模型 + 数据集 + seed」合成一个运行指纹。
- `calibration.dataset_fingerprint()`（`calibration.py:72-103`）只用于噪声带缓存键；不是整轮实验身份。
- 影响面：改了模型或数据集后复用旧缓存/旧续跑，读数会混入不同配置，且没有拒绝机制。
- 与 Harness² 的对照：`config.json` 记录模型/端点/split/任务流/seed 并在不一致时拒绝复用（`cli/run_sweep.py:209-235`）；`runmark` 把 harness 指纹写进完成标记（`runmark.py:64-102`）。
- **落地状态（当前）**：已修复。`experiment_fingerprint()` 进噪声带缓存键、运行/提案与编辑台账；历史锚只认同指纹条目；审批时技能正文已变则拒绝（`baseline_changed`）；job queue payload 带 `evolutionPassIdentity`，身份不一致拒绝旧作业。

**N6｜常驻指令面是「隐式可编辑」，没有总账与执行前校验**
- 常驻文本分散在 soul/personality/constitution/rules_sections/AGENTS.md/skill catalog/tools_desc（`context/orchestrator.py:1188-1225`、`:2644`、`:2891`），各有各的预算，没有总占用读数。
- 工作区 `AGENTS.md` 会被注入（`workspace_docs.py`），文件写入工具对绝对路径不做限制（`file_operation_executor.py:60-76`）；但没有任何「这个文件是可编辑面、必须满足什么约束」的校验。
- 影响面：常驻面可以悄悄变大、引用不存在的脚本、写出不可解析的规则，而系统不会在下一轮之前发现。
- 与 Harness² 的对照：Harness² 的 c1–c8 面有明确的 `is_allowed()` 白名单、`validate()` 执行前检查、always-on 上限与「技能必须被点名」规则（`tree.py:92-110`、`:336-390`）。
- **落地状态（当前）**：按软告警落地。`build_context` 记录 soul/personality/constitution/rules/workspace_docs/skill_catalog/behavior_rules/tools 的分段字符数与上限；`recordContextBudget` 在超总预算/分段预算时写 warning；`GET /v1/context/budget` 可读，无实测 404。未做强上限/可编辑面（C8 保持不开放）。

**N7｜选择以分数 argmax，未做匿名化/盲选**
- `_multi_variant_round` 与主循环都按 tune 分 argmax（`runner.py:486-500`、`:639-648`）；候选来源、基线身份对判分器可见。
- 泄漏审查降低了「背题」风险，但不能消除「判分器偏好某种风格」的选择偏差。
- 影响面：最终采纳可能偏向「判分器喜欢的措辞」，而不是「对用户任务更好的产物」。
- 与 Harness² 的对照：Harness² 把候选匿名化、只给交付物，选择器看不到来源；且选择在判分之前（`selection.py:268-357`；`judge.py:15-19`）。
- **落地状态（当前）**：已修复。`runner._multi_variant_round` 在 top 两候选分差 ≤ `max(min_improvement, 0.02)` 时调用 `blind_ab()`：匿名 A/B、只读产物；无选择器诚实回退 argmax；读数写入 `blind_tiebreak`。`ab_compare` 的近平分审批读数保留。

**N8｜经验复用以技能为粒度，没有域级 harness 库**
- 本仓有技能经验库、技能市场、`skill_experience` 的组合描述，但没有「同一领域下已验证的整套 harness/技能组合」的复用单元。
- **落地状态（当前）**：已立项实现，只扩展既有技能库、不新建存储。`SkillService.skillDomain()` 按 `config.category/domain → tags[0] → general` 分组；`listDomainHarnesses()` 返回同域已采纳 harness；`searchDomainHarnesses()` 做跨域关键词排序；`GET /v1/skill-pool/agent/{agent_id}/domain-harnesses` 暴露 `domain/adopted/revision_count/score`；`AgentSkillPage` 提供跨域搜索、采纳态与「采纳到目标技能」入口；独立采纳走 pending 提案 + 人工批准，不自动写正文。自动路径与 `/evolve` 把它注入 service 变异器提示。

---

## 4. 评分

### 4.1 权重与口径

权重按「对自改进系统长期可信度的边际贡献」分配；评分口径是**自改进/harness 优化域**，不是产品总体规模。生产就绪度单列，不混入综合分。

| # | 维度 | 权重 | Harness² | Neurova（当前） | 一句话判定 |
|---|---|---:|---:|---:|---|
| 1 | 闭环完整性（提议→探测→采纳→复用） | 15% | 9.0 | 8.6 | H2 一条闭环；Neurova 统一 service + 治理开关 + trace + 域 harness 注入 |
| 2 | 证据质量与对比设计 | 15% | 8.5 | 8.6 | H2 完整轨迹/交付物；Neurova 成功/失败全量 + 逐工具 trace + 小产物复制 + 大产物 hash 清单 |
| 3 | 防泄漏/防过拟合 | 8% | 9.0 | 8.1 | H2 答案面+盲选+绊线；Neurova 六类审查+留出集+窄标记 warn-only |
| 4 | 验证与采纳严谨性 | 8% | 7.0 | 8.1 | H2 单候选单 rollout；Neurova 留出/噪声带/案例门/失败证据+trace |
| 5 | 经验复用与跨任务迁移 | 8% | 9.0 | 8.0 | H2 同域整套 harness 库；Neurova 跨域检索+UI+采纳流+提示注入 |
| 6 | 可复现/可审计 | 8% | 9.5 | 8.7 | H2 命名空间/种子/指纹/续跑；Neurova 指纹进台账/锚/审批/作业身份 |
| 7 | 上下文/提示工程 | 8% | 9.5 | 7.8 | H2 成本阶梯+24k 上限+文件证据；Neurova 有软告警，无强制上限 |
| 8 | 测试与可验证性 | 10% | 5.0 | 8.5 | H2 229 行/5 用例；Neurova 473k 行测试 + 本轮新增/相关全绿 |
| 9 | 生产安全与平台化 | 10% | 3.5 | 8.5 | H2 无沙箱/网络不受限/POSIX-only；Neurova 沙箱/鉴权/渠道/UI |
| 10 | 代码规模控制与可维护性 | 10% | 8.0 | 6.3 | H2 边界清楚、规模小；Neurova 大而全、审计在途、新增 trace/UI 模块 |

**权重口径**：1–2 各 15%，3–7 各 8%（方法域合计 70%），8–10 各 10%（工程域合计 30%），合计 100%。

**加权结果（当前）**：

- Harness²：`0.15×9.0 + 0.15×8.5 + 0.08×9.0 + 0.08×7.0 + 0.08×9.0 + 0.08×9.5 + 0.08×9.5 + 0.10×5.0 + 0.10×3.5 + 0.10×8.0 = 7.795 ≈ 7.8`
- Neurova：`0.15×8.6 + 0.15×8.6 + 0.08×8.1 + 0.08×8.1 + 0.08×8.0 + 0.08×8.7 + 0.08×7.8 + 0.10×8.5 + 0.10×8.5 + 0.10×6.3 = 8.166 ≈ 8.2`

### 4.2 分域读数

- **方法域（第 1–7 维，权重 70%）**：Harness² **8.8** / Neurova **8.3**。差距主要集中在「完整交付物/成熟域库」，而不是「谁更会写 prompt」。
- **工程域（第 8–10 维，权重 30%）**：Harness² **5.5** / Neurova **7.8**。差距集中在测试、生产安全、平台化。
- **生产就绪度（单列）**：Harness² **4.3** / Neurova **8.4**（四维粗算：测试 15% + 生产安全 50% + 可复现 15% + 平台化 20%；代入上表第 8/9/6 维与平台化 2.0/9.0）。依据：无沙箱、网络不受限、POSIX-only、无鉴权/多租户/持久化；Neurova 有沙箱、鉴权、渠道、数据库、前端、i18n。
- **结论**：不要再读「H2 比 N 好」或反过来。准确的读法是：**方法域 H2 仍领先 0.5（完整交付物与成熟域库），工程域 Neurova 领先 2.3；加权总分 Neurova 8.2 高于 H2 7.8，是工程权重与闭环补齐的结果。** 领先不等于方法更强。

> 口径警告：第 9 维对 Harness² 的 3.5 分是「若按统一生产标尺」的分数；研究原型本就不以生产为目标，这一维不应用来否定其方法价值。反过来，Neurova 的证据/复用分是「自改进方法」的真实读数，不因平台规模大而抵消。

### 4.3 哪些证据会改变评分

- 若 Harness² 补上「每候选多次 rollout + 统计显著性」，第 4 维会从 7.0 升到 8.5 左右，综合约 +0.15。
- 若 Neurova 把大产物（>2MB）的内容也复制进证据包（当前只留路径 + SHA-256），第 2 维再 +0.1 左右。
- 若 Neurova 把 N8 采纳流做成完整的候选对比/审阅页，第 5 维 +0.2 左右。
- 若 Neurova 给常驻面加执行前校验/强制上限（C8），第 7 维 +0.5 左右，但自修改风险同步上升。
- 若 Harness² 补上生产沙箱与跨平台，第 9 维会显著上升，但那是另一个项目的工作量。

---

## 5. 启发

### 5.1 概念层：五条比代码更重要的判断

1. **两级递归要分开记账。** Harness² 把「任务级临时适配」与「跨任务持久经验」分成两层：任务级改当前 harness，任务结束就丢弃；只有被选中的 harness 与经验进入域库（`library.py:15-24`、`selection.py:402`）。Neurova 的自动技能改进把「本轮的修订」「跨轮的经验」「技能描述重建」混在一条链里，缺少「临时试错」与「持久采纳」的边界。**建议**：任何自动改进先产出「临时候选」，经探测/留出后才进入持久层；未过门的候选只留在审计记录，不写技能本体。**当前**：pending vs applied 已分开，未过门不写正文；任务级临时 harness 层仍无（结构性差异，不按对齐补）。
2. **证据制度决定能学到什么。** Harness² 故意不给提案器 rubric/分数，用行为对照 + 盲选；Neurova 用 judge/expected behavior + 留出集。前者避免「教模型讨好评分器」，但无法证明真提升；后者能测真提升，但必须用留出集/泄漏审查防过拟合。**建议**：不要整体切换；在「judge 可信」的场景用留出分做门，在「judge 不可信」的场景用对照/盲选做门，两者都记录。**当前**：judge 可信时留出分门已落；judge 不可用时有确定性可用性回退门（人工复核），但 judge 可信度本身仍无法测，盲选仍用同一 judge。
3. **harness 是行为分布，不是文本。** Harness² 的每个候选都要 rollout；提示词明确「一次 rollout 是弱证据」「编辑必须能追溯到轨迹里的具体时刻」（`prompts.py:858-869`、`:922-931`）。Neurova 的技能改进目前只有文本变更与使用统计，没有「同一任务上 base vs 候选」的行为对照。**建议**：把「行为探测」作为自动改进入口的硬前置，而不是事后评估。**当前**：已是硬前置；执行面默认 auto（真臂优先，离线/超预算回落并标注），模拟面仍是文本级。
4. **常驻上下文有成本阶梯。** 技能/脚本/子代理/钩子按需加载，常驻文本最贵；Harness² 把 always-on 上限设为 24k 并反复要求「加一句删一句」（`substrate/opencode.py:50-51`、`prompts.py:134-146`）。Neurova 的常驻面更大（soul/rules/tools/memory/skill catalog），但只有分段预算，没有总账。**建议**：先做只读的「常驻面预算报告」，再谈压缩。**当前**：只读预算报告 + 软告警已落；强制上限按 2026-10-21 拍板不做。
5. **「不变」是一等答案。** Harness² 的 `KEEP_BASE` 被写成「真实答案，不是失败」；证据不支持改动时，改就是 regression（`prompts.py:333-335`）。Neurova 的自动改进倾向于「有失败就提案」，缺少「证据不足则不提案」的显式出口。**建议**：在自动技能改进里加入 `NO_ENTRY`/`KEEP_BASE` 等价态，并让它可观测。**当前**：`reject_reason=no_improvement` 已落运行台账，机制上等价；尚未单独命名/建独立观测页。

### 5.2 候选清单（按优先级）

> 每条候选的「理由」列只写本仓断点；「可借鉴机制」列只描述 Harness² 的做法，不构成对齐承诺。落地时必须独立设计、先红后绿。

| # | 优先级 | 本仓断点（证据） | 可借鉴机制 | 建议落地形态 | 代价/风险 |
|---|---|---|---|---|---|
| C1 | **P0** | N1/N3：自动技能改进与文本进化双路径；自动路径 `improved_text` 只写不读，且无行为门 | 一条 Propose–Probe–Compose 闭环；候选先探测再合成；KEEP_BASE 合法 | 把自动路径改成「产出候选 → 用现有 `eval/service` 的留出/噪声/泄漏门跑 base vs 候选 → 过门才写 `context_template`，否则留 pending/NO_ENTRY」；删掉自动路径里不消费 `improved_text` 的分支 | 中：评测成本上升；需设回合/金额预算；可能减少自动改动量（这是正确行为） |
| C2 | **P0** | N2：`record_usage` 不传输入/输出，反思拿到空摘要 | 证据树落盘、提示只给指针；完整轨迹/交付物不截断 | 在 `_on_skill_post_execute` 采集有界 `input_summary/output_summary/tool trace/artifact ref`，经 `evolution_inputs_guard` 脱敏限长后落 per-run 证据包；改进任务按指针读，不塞进提示 | 低-中：存储与隐私；已有脱敏/限长设施可复用 |
| C3 | **P1** | N4：无候选/调用恒等式；N5：无实验身份指纹 | R=4k/P=3k 断言＋重复标签检查；namespace + runmark 指纹 + config 身份 | 每轮记录 `expected_candidates/evaluated/applied` 与 `expected_evals/actual_evals`，不等即红；把技能正文+config+模型+数据集+seed 合成一个 run fingerprint，缓存/续跑只认它 | 低：纯记账；需定义「预期」口径，避免把重试算成候选 |
| C4 | **P1** | N7：选择按 tune 分 argmax，未匿名化 | 匿名候选、只读交付物、选择后判分 | 仅在「最终采纳」或「近平分」时做匿名 A/B/多选：渲染 base 与候选交付物，去掉来源，选择器只读产物；留出分保留为门，不参与选择 | 中：多一次选择器调用；选择器本身有偏；需记录选择理由 |
| C5 | **P2** | N6：常驻面分散、无总账；`AGENTS.md` 隐式可写 | c1–c8 白名单 + validate + always-on cap | 先做只读「常驻面清单/预算报告」：按 segment 统计字符与来源，列出超预算项；不自动改 prompt。若要允许人审编辑，再加白名单与执行前校验 | 低（只读）；若走到自动改写则高风险 |
| C6 | **P2** | N7/泄漏边界：候选侧有 leak_critic，但证据树/改进上下文没有「评分器结论」绊线 | `assert_no_grader_verdicts` 在证据落盘前扫标记 | 在证据包/改进上下文落盘前加同一思想的绊线：命中评分器结论标记即拒绝该证据进入模型上下文，并记录读取路径；标记列表独立维护，不照抄字符串 | 低：可能误杀；需从窄标记起步 |
| C7 | **P2（已落）** | N8：经验以技能为粒度，无域级 harness 库 | 同域整套 harness + `EXPERIENCE.md`（cue/lesson/evidence/confidence） | 只扩展既有技能库/市场：域视图 + 跨域检索 + API + AgentSkillPage 面板 + 变异器注入 | 中：与技能市场/技能库存在重叠，已按单源约束实现 |
| C8 | **P3（只读先行）** | N6：Agent 不能改 prompt，但常驻面并非真正不可写 | 可编辑树 + 执行前校验 | 先只做「harness 快照/差异/测试」三件事，不开放自动改写；任何自动改写都必须有人审门与回滚 | 高：自修改 prompt 的安全/稳定性风险；不建议在自动链上开放 |

**当前落地状态**：
- **C1 已落**：旧自动反射分支退役；自动路径统一走 `SkillEvolutionService`；`auto_apply_skill_evolution` 默认关，过门后按开关 `decide`/留 pending。
- **C2 已落（按决策）**：成功与失败执行都落全量文件（单字段 50k、失败 100 份/成功 20 份）+ 逐工具 trace + 小产物复制 + 大产物 SHA-256 清单；失败证据经 `extra_failures` 进入变异器，成功证据经审计端点可读。
- **C3 已落**：候选/参数轮恒等式 + 实验身份指纹（缓存键、台账、锚、审批、作业身份）。
- **C4 已落**：主 runner 近平分匿名 A/B tie-break；无选择器回退 argmax；`ab_compare` 审批读数保留。
- **C5 已落（软告警）**：常驻面分段预算报告 + `/v1/context/budget` + 超限 warning；未做强制上限/编辑契约。
- **C6 已落（warn-only）**：失败证据进变异器前扫 `pass_rate` 等窄标记，命中记 warning，不阻断。
- **C7 已落（扩展既有库）**：`SkillService` 域视图 + 跨域关键词检索 + API + AgentSkillPage 面板 + 独立采纳 pending 提案 + 变异器注入；批准走既有提案审批链。
- **C8 未立项**：按本文建议保持不开放。
- **本批新增（2026-10-21）**：
  - judge 不可用 → 确定性可用性回退门（`judge_fallback=deterministic`）；提案 `requires_manual_review=True`，自动审批路径拒绝。
  - 执行面默认 **auto**：真臂优先；离线/超预算回落模拟面并在响应标注 `real_trajectory_fallback`；显式 `true`/`false` 仍严格。
  - 成功轨迹全量落盘（20 份/技能）+ 大产物路径/SHA-256 清单 + 只读证据审计端点。

### 5.3 建议起手序

当前已按 **C2 → C1 → C3 → C5 → C4 → C6 → C7** 的顺序落地（C5 为软告警，C7 只扩展既有库），并补上 judge 回退门、执行面 auto、成功轨迹与大产物 hash 清单；剩余 **C8**：

- C2 失败全量证据已进变异器。
- C1 已统一到 service；自动应用受治理开关控制（默认关）。
- C3 恒等式 + 实验指纹已落。
- C5 只读预算报告 + 软告警已落。
- C4 主 runner 近平分盲选已落。
- C6 窄标记 warn-only 已落。
- C7 域视图 + 跨域检索 + UI + 提示注入已落；C8 暂不立项。
- judge 不可用 → 确定性可用性回退门 + 人工复核已落；执行面默认 auto 已落；成功轨迹与大产物 hash 清单已落。

### 5.4 明确不建议照搬

1. **POSIX-only 实现**：`fcntl` 锁（`schedule.py:294`）在本机 demo 直接失败；Neurova 要跨平台，不能引入。
2. **无沙箱执行**：`--dangerously-skip-permissions`（`proposer.py:214-220`）、网络不受限、Codex 沙箱关闭（README:166-171）是研究环境的选择，不是生产选项。
3. **单候选单 rollout 作为采纳依据**：Harness² 自己承认这是弱证据（`prompts.py:922-931`）；Neurova 不应把「跑一次看起来更好」当成门槛。
4. **用 LLM 盲选替代真值判分**：盲选解决的是选择偏差，不解决「是否真的更好」；Neurova 有留出集，不应放弃。
5. **直接搬 benchmark 代码/数据/提示词**：`third_party/` 有其上游许可证；本仓 §2 原创性条款也禁止搬运外部实现与措辞。本文只借结构思想。
6. **把「可编辑 harness」直接开给 Agent**：Harness² 的提案器本身就是外部 LLM，且它有完整校验/泄漏/预算护栏；Neurova 若没有同等护栏，开放自动改写 prompt 的风险远大于收益。

---

## 6. 待拍板问题（决策影响面）

> 按 `AGENTS.md` 核心原则第 8 条：每题给选项、代价、不可逆点、影响面与推荐项。
>
> **当前决策（2026-10-21）**：闭环取**过门自动应用（治理开关默认关）**、**失败/成功全量 + 小产物复制 + 大产物 hash 清单**、**主 runner 近平分盲选 tie-break**、**混配置拒绝并重跑**；judge 不可用取**确定性可用性回退门**（提案强制人工复核，自动审批拒绝）；执行面默认 **auto**（真臂优先，离线/超预算回落并标注；显式 true/false 仍严格）；N6 取**软告警**（用户已拍板：不加执行前硬上限）；C6 取**窄标记 warn-only**；N8 **只扩展既有技能库/市场，不新建平行库**；完整工具 trace 与跨域检索/UI 已接；C8 **维持不开放**（用户已拍板：不开放可编辑面）。

### T1｜自动技能改进是否接入行为门？
- **A（推荐）**：自动路径改为「候选 → 现有 eval/service 留出/噪声/泄漏门 → 过门才写正文；否则 pending/NO_ENTRY」。代价：评测成本与延迟上升；不可逆点：自动改动量会下降，需接受「少而准」。影响面：`post_chat_pipeline.py`、`skill_improver.py`、`eval/service.py`、`skill_service.py`。
- **B**：保留直接写，只加最小 probe（单任务 base vs 候选），不过门则回滚。代价较低，但证据弱于留出集。
- **C**：不动。代价：N1/N3 继续存在，自动改进主要是记账。

### T2｜是否采集技能执行证据包？
- **A（推荐）**：全量有界采集（输入/输出/错误/工具轨迹/产物引用），经现有 `evolution_inputs_guard` 脱敏限长。代价：存储与隐私面；不可逆点：一旦开始采集，需明确保留期与访问控制。影响面：`agent_core.py`、`skill_improver.py`、`skills/evolution_inputs_guard.py`。
- **B**：只采失败样本。代价低，但学不到成功路径。
- **C**：不采。反射式改进继续拿空摘要。

### T3｜最终采纳是否引入匿名盲选？
- **A（推荐）**：仅在最终采纳/近平分时盲选，留出分作为门。代价：一次额外选择器调用；影响面：`eval/runner.py`、`eval/service.py`。
- **B**：全面盲选。代价高，且可能引入选择器自身偏差。
- **C**：不引入。继续 argmax。

### T4｜常驻指令面是否账本化？
- **A（推荐）**：先做只读清单/预算报告（分段字符、来源、超预算项），不自动改。代价低；影响面：`context/orchestrator.py`、`rules_sections.py`、`workspace_docs.py`。
- **B**：允许人审编辑 + 白名单 + 执行前校验。代价中；需定义可编辑面与审批流。
- **C**：允许 Agent 自动改写。**不推荐**：缺少同等护栏时风险不可控。

---

## 7. 证据附录

### 7.1 外部仓实测

```text
$ cd /e/tmp/harness2 && python -m harness2.cli.demo --output /e/tmp/h2demo --k 2
  [accounting] 1/2 exception    ledger-1  :: ModuleNotFoundError: No module named 'fcntl'
  [accounting] 2/2 exception    ledger-2  :: ModuleNotFoundError: No module named 'fcntl'
Local demo: 0 tasks completed; 2 failed.
```

进程内探针（不依赖 POSIX 路径）：

```text
VALIDATE_REJECTED: skills/orphan/SKILL.md needs frontmatter `name: orphan` ... |
skill 'orphan' is never named in the always-on text ...
LEAK_TRIPWIRE: harness file 'x.md' contains grader-verdict marker '"pass_rate"' ...
DIVERSITY: {'n': 2, 'n_distinct': 1, 'mean_line_jaccard': 1.0}
DIVERSITY_DIFF: {'n': 2, 'n_distinct': 2, 'mean_line_jaccard': 0.3333}
```

### 7.2 规模读数

| 项 | Harness² | Neurova |
|---|---:|---:|
| Python 源码行 | 12,747（core 5,688 / substrate 992 / cli 1,051 / benchmarks 4,170 / top 846） | 346,580 |
| 测试行 | 229 | 473,498 |
| 测试/源码 | 1.8% | 136.6% |
| 测试用例数 | 5 | 未逐个数；当前验证见 §7.3 |
| 外部第三方代码 | 2,591 行（`third_party/`） | 依赖以包管理为主 |

### 7.3 当前验证（2026-10-21）

```text
$ .venv/Scripts/python.exe -m pytest tests/unit/evolution --timeout=60 -q
1675 passed
```

```text
$ .venv/Scripts/python.exe -m pytest tests/unit/skills --timeout=60 -q
1199 passed, 2 skipped
```

```text
$ .venv/Scripts/python.exe -m pytest \
    tests/unit/api/test_text_evolution_api.py \
    tests/unit/api/test_evolveRealArmPathAndBudgetGate.py \
    tests/unit/api/test_evolution_ab_endpoint.py \
    tests/unit/api/test_evolutionEvidenceApi.py -q
43 passed
```

```text
$ .venv/Scripts/python.exe -m pytest \
    tests/unit/evolution/eval/test_judgeFallbackGate.py \
    tests/unit/evolution/test_successEvidence.py \
    tests/unit/api/test_evolutionEvidenceApi.py \
    tests/unit/api/test_evolveRealArmPathAndBudgetGate.py \
    tests/unit/api/test_evolution_ab_endpoint.py -q
34 passed
```

```text
$ PYTHONPATH=. .venv/Scripts/python.exe tests/manual/evolutionFallbackEvidence_live.py
JUDGE_FALLBACK_LIVE_OK judge_available=False fallback=deterministic manual=True
EVIDENCE_LIVE_OK kind=full_success small=copied large=reference artifacts=2
EVIDENCE_HTTP_LIVE_OK items=1 output='{"text": "live answer"}'
EVIDENCE_READER_LIVE_OK items=1
```

```text
$ cd NeurUI && npx vitest run src/i18n/__tests__/locale-consistency.test.ts \
    src/pages/__tests__/AgentSkillPage.abArms.test.ts \
    src/api/modules/__tests__/text-evolution-contract.test.ts \
    src/api/modules/__tests__/skill-pool.test.ts
74 passed
$ npx vue-tsc --noEmit
(exit 0)
```

活体验证链路：真 `SkillEvolutionService.evolve` → 真 runner/约束/泄漏门 → judge 不可用回退为确定性可用性门 → pending 提案 `requires_manual_review=True` 且自动审批被拒；真 `recordExecutionEvidence` 落成功全量证据，小产物复制、大产物 SHA-256 引用；真 `create_app()` + 真 JWT 的证据审计端点读回同一份轨迹。LLM 判分/执行边界用替身；控制台 GBK 显示为乱码，断言在 Python 字符串层完成。

口径说明：43 项是文本进化/真臂/双臂/证据 API 的定向面；34 项是 judge 回退、成功证据与上述 API 的联合定向面；`tests/unit/evolution` 1675 项、`tests/unit/skills` 1199 项为全量面。`tests/unit/agent` 全量套件另有 8 项失败，集中在本次**未改动**的 `chat_pipeline._retrieve_memories` 签名与公开契约面，属并发会话在途改动；本批改动文件对应的定向测试全绿。

### 7.4 关键行号索引

**Harness²（commit `1cfe254`）**
- 方法/基座/基准三轴：`core/spec.py:15-20`、`:190-250`
- 编辑契约：`core/tree.py:15-20`；校验：`:336-390`；自动触发：`:192-213`
- 证据树：`core/context.py:15-26`、`:105-188`；mission：`:521-546`
- 泄漏：`core/context.py:399-416`、`:419-490`、`:493-518`
- 递归：`core/recursion.py:135-251`、`:343-449`、`:452-566`
- 盲选：`core/selection.py:71-86`、`:268-357`、`:402-505`
- 判分分离：`core/judge.py:15-19`；报告：`core/report.py:80-165`
- 账本：`core/ledger.py:26-33`、`:89-113`
- 可复现：`core/schedule.py:111-163`、`:350-421`、`:566-666`；`core/runmark.py:41-102`；`cli/run_sweep.py:209-235`
- 提示：`core/prompts.py:38-63`、`:95-193`、`:333-335`、`:858-869`、`:1105-1163`
- 平台限制：`core/schedule.py:294`；README:166-171

**Neurova（抓取日工作树）**
- RSI 入口/循环：`post_chat_pipeline.py:847`、`:3179`；`rsi/orchestrator.py:417-700`
- 确定性评测：`rsi/eval_harness.py:328-395`
- 评估服务/执行器：`eval/service.py:60-90`；`eval/runner.py:486-500`、`:541-560`、`:639-660`
- 留出/噪声：`eval/dataset.py:44-72`；`eval/calibration.py:72-103`
- 泄漏审查：`eval/leak_critic.py:1-30`
- 自动技能改进：`post_chat_pipeline.py:236-262`、`:2848`；`skill_improver.py:194-232`、`:473-478`、`:499`、`:504-640`
- 人工文本进化：`text_evolution_api.py:154-161`、`:164`、`:413`；`eval/service.py:801-825`
- 质量门：`skills/skill_service.py:1229-1270`
- 上下文组装：`context/orchestrator.py:1188-1225`、`:2644`、`:2685`、`:2891`、`:3102-3114`
- 工作区文档：`context/workspace_docs.py:27`
- 执行记录缺 I/O：`agent_core.py:1573-1602`（已改为委托 `skill_recording.recordSkillUsage`）
- 不可自改 prompt：`agent_config.py:311`（生产零调用）
- 文件工具绝对路径：`skills/builtin/file_operation_executor.py:60-76`

**当前新增落点（2026-10-21）**
- 单一 service 入口：`post_chat_pipeline.py:236`；字典提案异步口：`skill_improver.py:441`；字典提案落账：`:449`
- 自动应用开关：`evolution_settings.py:50`、`:114`；API 白名单：`api/endpoints/text_evolution_api.py:43`
- 证据摘要/全量字段：`skill_evidence.py:56`、`:70`；装载失败证据/转 JudgeFailure：`:325`、`:349`；采集装配：`skill_recording.py:27`
- 候选账实恒等式：`eval/runner.py:139`
- RSI 参数轮恒等式：`rsi/orchestrator.py:68`、`:79`
- 实验身份指纹：`eval/calibration.py:82`；台账指纹/锚过滤：`eval/runner.py`、`eval/service.py:50`；审批基线守卫：`eval/service.py:855`；作业身份：`evolution_settings.py:127`、`:144`
- 匿名盲选：`eval/blind_selection.py:53`；主 runner tie-break：`eval/runner.py:551`
- 常驻面预算：`context/budget_report.py:26`、`:58`、`:68`；端点 `api/endpoints/context.py:390`；装配 `context/orchestrator.py:1240-1245`
- C6 窄标记：`skill_evidence.py:32`、`:42`、`:340`
- N8 域视图：`skills/skill_service.py:48`、`:68`、`:1087`、`:1091`；提示注入：`eval/mutator.py:124`
- 完整工具 trace：`core/tool_trace.py:21`、`:48`；`tool_executor.py:1155`；`tool_layers/tool_router.py:418`；`skill_evidence.py:95`、`:143`、`:340`；`eval/mutator.py:116`
- N8 跨域检索/UI：`skill_service.py:111`、`:1152`；`api/endpoints/skill_pool_api.py:850`；`NeurUI/src/pages/AgentSkillPage.vue:49`、`:53`、`:60`
- 执行面 auto：`api/endpoints/text_evolution_api.py:159`、`:261`、`:338`、`:360`、`:368`
- judge 回退门：`evolution/eval/deterministic_judge.py:22`；runner 接线：`eval/runner.py:656`；提案标记/审批拒绝：`eval/service.py:651`、`:864`
- 成功/失败全量证据与产物清单：`evolution/skill_evidence.py:143`、`:244`、`:378`、`:424`；只读证据 API：`api/endpoints/text_evolution_api.py:338`
- 产物引用：`api/endpoints/artifacts_api.py:363`
- N8 独立采纳：`evolution/eval/service.py:784`；API：`api/endpoints/text_evolution_api.py:433`、`:437`；UI：`NeurUI/src/pages/AgentSkillPage.vue:73`、`:566`；客户端：`NeurUI/src/api/modules/text-evolution.ts:161`

---

## 8. 一句话收束

Harness² 值得学的不是「让模型改提示词」，而是它把**证据、选择、判分、账本、复现**五件事拆成了互不污染的边界；Neurova 值得保留的不是「自动改得更多」，而是它已经把**三态诚实、留出集、泄漏审查、回滚**做成了生产纪律。当前已经把自动技能改进推上「有证据、可探测、可回滚、可复现」的窄门：单一 service 出一份提案，过门才按治理开关自动应用或留 pending；失败/成功证据进变异器或审计面；judge 不可用时走确定性回退门并强制人工复核；执行面默认真臂优先、回落必标注；主 runner 近平分匿名盲选；实验身份进缓存、台账、锚、审批与作业身份。**8.2 与 7.8 的 0.4 领先不是方法更强，而是工程权重与闭环补齐的结果**；方法域仍差 0.5（H2 8.8 / N 8.3），主要在完整交付物与成熟域库，而不是本次补上的 judge 回退、工具 trace 或成功证据。
