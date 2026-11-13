# HarnessPro 与 Neurova 成本感知 harness 自改进对照评测（2026-11-13）

> **性质声明**：本文属 [`docs/INDEX.md`](../INDEX.md) §2.4「竞品/外部对标」——**研究参考，仅作背景与
> 评测标尺，不可作为本仓设计的事实源或对齐依据**（`AGENTS.md` §2 协作红线：外部产出只作功能依赖或
> 背景登记，不引入其设计标准，不搬运其命名、结构与措辞）。文中任何「启发/候选」若要落地，一律按本仓
> 修复教义独立立项（先红后绿、复核实状、单点收口、净 LOC 逐条列去向），本文**不构成对齐承诺**。
> 文中「对方有 X」只用于**提问**，不用于**规定本仓怎么做**；候选立项理由一律写成本仓自身可核实的
> 断点或缺口（§3.5、§5.2）。
>
> **对照对象**：*HarnessPro: Recursive Harness Self-Improvement with Pareto Optimization for
> Performance-Cost Trade-offs*，Zhuoshi Pan 等 9 人（清华大学 / Z.AI / 上海交大 / Warwick /
> Kling AI），arXiv:2610.26770v2，2026-10-19 提交 / 10-20 修订，41 页，**未经同行评审（under review）**；
> 代码 `github.com/pzs19/HarnessPro`（MIT），本机 clone @ commit `6fd2d4dbc3b7`（2026-10-28，main 最新）。
>
> **取证分级（诚实形态）**：论文侧＝arXiv HTML 全文逐节精读（正文 §1–§6＋附录 A–D 全部通读），
> 非二手解读；其实验数字为**论文自述**（under review，未复现其 benchmark 跑分——本机无
> Terminal-Bench 2 / SWE-bench Pro / ProgramBench 任务数据与 GPT-5.5 端点，如实声明）。
> 代码侧＝clone 仓全量勘察（模块地图、policy/hook/runner 关键文件逐读）＋**本机实跑取证**：
> Windows 10.0.26300 / Python 3.12 下离线测试 **6 errors**（`fcntl` POSIX-only＋缺 `pier` 依赖，
> §7.1），动态行为以代码与文档为准，凡未实跑处均已标注。Neurova 侧＝工作树 HEAD `3f7c916be`
> （2026-11-13）实测：两路只读深度核查（运行时 harness 面 / 记忆与评测面）＋主代理对承重断言
> 逐条 `grep` 亲验（`effort_inference.py:34`、`eval/runner.py:90-92`、`eval/synthetic.py:48`、
> `hooks_engine.py:27` 无 Stop 调用点、`benchmark.py:105-130` simulated 诚实标记，均命中）。
>
> **同主题事实源链（本文的文档定位，先于内容）**：本仓「外部 harness/RSI 对标」已有五份前作——
> [`rsiagent_vs_neurova_rsi_comparison_2026-10-06.md`](rsiagent_vs_neurova_rsi_comparison_2026-10-06.md)（外部框架）、
> [`designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md`](designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md)（程序性记忆，P1-A..C）、
> [`modularrsi_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md`](modularrsi_paper_vs_neurova_harness_rsi_comparison_2026-10-15.md)（harness 模块化演化，M-A..E）、
> [`harness2_vs_neurova_recursive_harness_comparison_2026-10-21.md`](harness2_vs_neurova_recursive_harness_comparison_2026-10-21.md)（google-research/harness²，N1–N8/C1–C8）、
> [`rsi_survey_vs_neurova_rsi_evaluation_2026-11-10.md`](rsi_survey_vs_neurova_rsi_evaluation_2026-11-10.md)（RSI 综述评测协议，S1–S6）。
> 本文是链上第六档。**与前作的增量**：harness² 重「证据制度与盲选」，ModularRSI 重「模块化演化面」，
> 综述重「实证判据」；**HarnessPro 独有的三件事前作均未覆盖**——① 执行成本入目标函数＋
> 性能-成本 Pareto 多档交付（lite/medium/heavy）；② label-free **可执行测试合成**替代 LLM 判分；
> ③ 运行时**分档预算钩子**（动态推理努力路由＋工具预算分段硬停＋工具输出压缩）。
> 重叠项一律指回前作编号（轨迹证据→harness² N2、防泄漏→harness² §2.4.3、递归轮次→ModularRSI、
> 全成本账→综述 S2），本文新增项另起 **HN／HC 前缀**，不占前作号位；各表其纸，不合并总档。
>
> **阅读对象**：`neurova/agent/`（loops、gates、hooks）、`neurova/evolution/`（eval、rsi）、
> `neurova/core/`（usage_accounting、tool_offload、trace_recorder）的维护者。
>
> **复评指针**：同日修复批（§9）落地后，按 §4 同一口径的复评与剩余提升空间见 §10——
> §0–§8 保持当日评估快照原样，不回写。

---

## 0. 结论摘要

- **一句话画像**：HarnessPro 是一个**成本感知的递归 harness 优化器**——把「指令、推理档位、
  工具预算钩子、输出压缩、校验清单」当成可编辑工件，用「轨迹诊断 → 三档计划 → 编辑 →
  合成测试评测 → Pareto 选档」的循环递归改进，**同时优化通过率与执行成本**，最终交付
  lite/medium/heavy 三档可直接部署的 harness 工件。Neurova 是**生产型智能体平台**——运行时
  面宽（记忆/睡眠/技能/渠道/沙箱/前端），自改进治理成熟（留出集/噪声带/泄漏审查/人工评审/
  回滚），但**成本只记账不进目标、评测靠 judge 不靠可执行测试、执行档位只有思考深度没有
  harness 工件档**。
- **评分（十维加权，方法 70%＋工程 30%，口径见 §4.1）**：**HarnessPro 7.5 / 10，Neurova 7.9 / 10**。
  分域读数：**方法域（1–7 维）HarnessPro 8.6 ＞ Neurova 7.9**——差距集中在「成本入目标、
  可执行测试判据、分档运行时工程」；**工程域（8–10 维）Neurova 7.8 ＞ HarnessPro 5.0**——
  差距在测试规模、生产安全、平台化。**生产就绪度单列**：HarnessPro ≈ 4.0 / Neurova 8.4
  （研究原型 vs 生产平台，不混入综合分）。
- **最重要的三个判断**：
  1. **HarnessPro 的真贡献不是「又一种 RSI」，而是把「钱」写进了目标函数**。同样的递归
     自改进，RHO 只追通过率（SWE-bench Pro 上成本 +42.6%），HarnessPro 用归一化加权平方
     距离在「性能-成本」平面上选三个操作点，heavy 档对 RHO 平均 **+2.0pp 通过率、−26.1%
     单任务成本**（GPT-5.5×Codex，三基准平均；论文自述）。Neurova 有完整 token 记账、定价
     估算、预算告警（`usage_accounting.py`、`cost_budget.py`），但**没有任何一条进化链把成本
     当选择目标**——成本字段在评测结果里只是被记录（`eval/runner.py:90-92`），不参与门控。
  2. **label-free 不等于 judge-free**。HarnessPro 用「一次性生成、全程固定」的 LLM 合成
     **可执行测试**做候选评测，失败召回率从直接 LLM 判分的 41.7% 提到 83.3%（论文自述）；
     消融显示去掉测试合成器通过率掉 3.4–10.0pp。Neurova 的合成评测集（`eval/synthetic.py`）
     产出的是 **rubric 文本**，判分仍靠 LLM judge——「写测试」与「打分」之间差着一个
     可执行判据层。
  3. **Neurova 的运行时机制底子比预想厚，缺的是「分档工件化」**。动态推理努力路由
     （`effort_inference.py` 查询难度→light/standard/deep→`reasoning_effort`）、四把门控
     （Iteration/TokenBudget/DoomLoop/Goal）、工具输出压缩（offload 落盘＋head/tail 预览＋
     OutputRef＋历史折叠）都已真实接线——形态上与 HarnessPro 的 evolved mechanisms
     一一对应。差距在：路由是**关键词启发式**而非 rubric 分类器；门控阈值是**全局单一
     配置**而非按任务分档；压缩阈值不随档位走；**没有 lite/medium/heavy 这样的可部署
     harness 档位工件**。
- **明确不建议照搬**（§5.3）：POSIX-only 的 `fcntl` 钩子、把合成测试全面替代真值/留出判分、
  单 rollout 采纳、32k 行 third_party 基准代码捆绑、无沙箱外部执行器直连生产。
- **最值得本仓学的三条（HC1–HC3）**：① 每任务成本账＋Cost-of-Pass 读数，并把成本变化纳入
  技能/参数进化的验收门（软门起步）；② 工具型技能的**可执行合成测试**判据层（生成一次、
  全程固定、防 gaming 闸）；③ 部署档位 harness 工件（指令＋预算＋钩子＋压缩阈值打包成
  lite/medium/heavy，按部署预算选档）。

---

## 1. 公平性前提：两者不是同一个问题

| | HarnessPro | Neurova |
|---|---|---|
| 问题域 | **离线研究**：在 3 个编码基准上验证「成本感知递归 harness 自改进」方法 | **生产常驻**：对话驱动的智能体平台，自改进是后台能力之一 |
| 改什么 | harness 工件：模型指令、执行档位（profile rubric＋policy.json）、运行时钩子（hook.py）、校验清单、辅助脚本 | 运行参数（五族 setpoint）、技能正文/描述、工具权重；**不改代码、不改模型权重** |
| 判据 | LLM 合成**可执行测试**（label-free，训练/验证期）→ 官方测试只做最终测试集评测 | golden/留出集＋LLM judge＋确定性 9 用例行为地板＋RAG 检索 P/R/F1 真执行 |
| 目标函数 | **（−通过率, 成本）双目标**，Pareto 前沿选 lite/medium/heavy 三点 | 质量单目标（留出分＋噪声带门），成本只记录不选择 |
| 执行面 | Codex CLI 0.147.0 / Claude Code 2.1.231，Docker 任务容器 | 进程内 agent＋沙箱＋工具层＋多渠道路由 |
| 交付形态 | 9 个 harness 工件目录（3 基准 × 3 档），含 policy.json/hook.py/rubric | 平台服务＋前端＋治理 API，无「档位工件」形态 |
| 规模 | src 10,960 行＋scripts 9,548 行＋harnesses 6,227 行＋third_party 32,004 行；测试 287 行 | Python 源码约 34.7 万行，测试约 47 万行（2,572 个测试文件 / 25,269 个 test 函数） |

因此本文评分口径是：**按「harness 自改进（含运行时机制）」这一共同交集评分**；生产就绪度单列。
HarnessPro 的分数回答「作为一门方法/装置它做得好不好」，不回答「能不能直接上生产」。

---

## 2. HarnessPro 代码级解剖

### 2.1 方法流水线（论文 §3–§4，与仓库实现互证）

一次演化 epoch 的完整顺序：

1. **训练核选择**（一次性）：按 RHO 的 DPP 方法，从除去测试集的任务里选 **10 个任务**做训练核——
   LLM judge 读任务描述＋初始轨迹，给难度分 r∈[0,10] 和抽象失败指纹 φ（去掉任务专名），
   难度加权 DPP 核 `K = diag(w)·S·diag(w)`，贪心最大化子集行列式（论文式 10–12）。
   **难度偏难、指纹去重**，核选全程不看官方测试结果。
2. **测试合成**（一次性）：Test Synthesizer 从「任务描述＋初始 harness 轨迹」为每个训练/验证
   任务生成**固定测试套件**（如 `test_generated.py` 10 个 unittest 用例＋case_manifest＋
   coverage＋repair-log＋self-review），在冻结的初始产物容器里执行校验；证据边界明确
   「禁止使用官方测试/评分器/答案；禁止从初始产物反推期望值」。生成后**全程固定**，
   保证候选间公平。附录 C.3 给出完整指令与 MCP 校验工具契约。
3. **轨迹诊断**（每 epoch）：每个候选 harness 在训练核上跑 **G=3 次独立 rollout**，记录轨迹、
   通过位、成本、时延；Trajectory Analyzer 对 G 条轨迹**联合诊断**，输出结构化问题清单
   （问题、对性能/成本的影响、证据指针＝轨迹文件路径＋事件行号范围）。附录 C.1 的两个
   样例（Caffe 构建失败归因、Mailman 冗余探索）显示诊断粒度到「哪次 rollout 的哪段命令
   浪费了多少 token」。
4. **计划与编辑**（每 epoch）：Evolution Planner 按三份不同优先级指令（I₁ 降本优先 /
   I₂ 均衡 / I₃ 性能优先）各出一份改进计划；计划可**对比其他候选的代码 diff**以识别有效
   机制；Harness Editor 在**独立工作区**把计划实现为可执行候选并 **commit 到 Git** 可回溯。
   3 候选 × 3 计划 = 每轮最多 9 个新候选，与父代合并评测。
5. **过滤与选档**（每 epoch）：验证集上每候选跑 1 次，用**固定合成测试**判分；先淘汰
   「低于初始 harness 通过率地板」与「被 Pareto 支配」的候选，再按归一化加权平方距离
   `J_m(h) = α_m·d_perf(h)² + β_m·d_cost(h)²` 选出 lite（α:β=1:2）/ medium（1:1）/
   heavy（2:1）三个代表进入下一轮。**验证/测试集全程对规划器保密**；测试集只在全部
   epoch 结束后评测一次。
6. **递归**：选出的三档作为下一 epoch 的候选集，循环 3（TB2/SWE-Pro）～4（ProgramBench）轮。

### 2.2 模块地图与规模（clone @ `6fd2d4db`）

| 层 | 位置 | 行数 | 职责 |
|---|---|---:|---|
| 运行时策略 | `src/rho/harness_runtime.py` | 1,322 | policy.json 加载校验（profile 阈值严格递增、routing 开关、classifier/adjuster/fresh-review 配置）、规则匹配 |
| agent 适配 | `src/rho/agent/external.py` / `codex.py` / `claude_code_hook_adapter.py` | 1,271 / 814 / 191 | Codex/Claude Code 子进程管理、流式事件解析、usage 事件、钩子桥接 |
| 观测与计价 | `src/rho/observability.py` / `pricing.py` | 615 / 211 | 轨迹标注、usage 抽取（含 cached/cache_write tokens）、可重试传输错误识别；公开牌价目录＋成本估算 |
| 轨迹存储 | `src/rho/stores/trajectory.py` | 124 | 文件型轨迹库：meta.json＋instructions＋events.jsonl＋stdout/stderr＋workspace_diff |
| 评测 runner | `scripts/run_tb2_harness_eval.py` 等 3 个＋辅助 | 9,548 | 三基准评测装配、Docker/工具链准备 |
| **harness 工件** | `harnesses/{tb2,swe-pro,programbench}/{lite,medium,heavy}/` | 6,227 | 每档含 README、`runtime/model_instructions.md`、`runtime/profile_rubric.md`（部分）、`runtime/policy.json`、`runtime/hook.py`，SWE-Pro 另有 `bin/repair-verify`＋校验清单 |
| 测试 | `tests/` | 287 | 2 个文件：policy 装载/runner 配置/钩子兼容/ProgramBench 运行时的离线回归 |
| third_party | `third_party/` | 32,004 | ProgramBench、Pier 评测器、RTK 0.28.2 二进制等 |

### 2.3 关键机制逐条

#### 2.3.1 动态推理努力路由：任务描述 → 五档 profile

每个任务开始前，用一次**免工具的小模型调用**（GPT-5.5 medium，120s 超时，≤2,048 输出
token，≤24,000 字符任务文本）按 `profile_rubric.md` 从五个执行档里选一个：

| 档位 | 推理努力 | 工具预算（medium 档 harness：收敛/收尾/硬停） |
|---|---|---|
| compact | low | 4 / 8 / 14 |
| lean | low | 10 / 16 / 22 |
| standard | medium | 26 / 38 / 44 |
| deep | high | 30 / 48 / 54 |
| research | high | 8 / 20 / 46（源重建型） |

rubric 是**证据法则**而非关键词表：只有「任务文本显式描述的验证器/交互/依赖/约束」可作
依据；「未描述的验证器 = 未知质量，默认 standard」；强 oracle（可本地重复、定位失败、
定量误差）才允许 deep。工程上还有 `confidence_overrides`（如 lean 置信度 <0.9 升 standard）
与 `fallback_profile`。代码：`harness_runtime.py` 的 `ModelClassifierConfig` /
`ConfidenceOverride` / `ClassificationRule`（`harness_runtime.py:12-151`）。

#### 2.3.2 运行时预算钩子：分段提醒 + 硬停

`hook.py`（stdlib-only）在每个工具调用前计数，按所选 profile 的三段阈值行动：

- **economy 段**：到达 `economy_after_tools` 时在工具结果后附「批量独立检查、停止复述」提醒；
- **strict 段**：到达 `strict_after_tools` 起每隔 `strict_reminder_every` 次附「停止泛化探索、
  只查与当前失败直接相关的证据、保留收尾预算」提醒；
- **finalize/hard-stop**：超过 `finalize_after_tools` 先劝收尾，超过「finalize＋max(8, reminder)」
  直接 `permissionDecision: deny`（「预算已尽，用现有证据给出最佳最终答案」）。

关键工程细节：**提醒以 `additionalContext` 附在工具结果之后**，不改动 prompt 前缀——
保住 provider 的 prompt cache 命中（论文 §5.3 明确点出）。审计日志与工具计数落
`.rho_runtime/`（fcntl 文件锁）。

#### 2.3.3 工具输出压缩

policy 的 `tool_output` 段配置 `history_token_limit`（单条输出保留预算，非模型上下文窗口）、
`max_chars/head_chars/tail_chars` 与 `rtk_enabled`：超限输出折断为「头＋尾＋省略标注＋
原始路径指针」，重复行折叠（`_compact_text`）；Bash 类命令可被 RTK（Rust Token Killer）
重写以压缩回显。TB2-medium 取 900 token/4000 字符，SWE-Pro 取 1400/6000，ProgramBench
取 3000/4500——**同一机制、按基准与档位调参**。

#### 2.3.4 label-free 测试合成：判据与生成物分离

与 RHO 的「LLM 自偏好选轨迹」不同，HarnessPro 让 LLM **写测试而非打分**：测试从「公共
任务契约＋初始轨迹」生成，一次性生成后冻结；判据层是真实执行（在冻结产物容器里跑
unittest），不是又一次模型调用。论文图 2 的混淆矩阵显示：直接 LLM 判分漏掉 58.3% 的
失败，合成测试把失败召回提到 83.3%。这是全文最值得借的单点机制。

#### 2.3.5 Pareto 选档：一次优化，三档交付

过滤（性能地板＋非支配）后按 §2.1 式 8–9 选三点。工程含义：**同一套演化预算产出三个
可部署档位**，运营按预算选档，而不是「一个 harness 打天下」。论文消融进一步证明：
把 evolved 机制（动态路由/预算钩子/低努力）单独移植回 RHO，都会被 evolved harness
Pareto 支配——**收益来自机制组合，不来自单点技巧**。

### 2.4 实验读数（论文表 2/3 摘录，论文自述未复现）

GPT-5.5×Codex（P=通过率%，C=均成本 $/任务，T=均时延 s）：

| 方法 | TB2 P/C/T | SWE-Pro P/C/T | ProgramBench P/C/T |
|---|---|---|---|
| Vanilla | 69.5 / 0.89 / 260 | 59.0 / 1.88 / 337 | 60.3 / 2.65 / 669 |
| RHO | 76.3 / 1.09 / 354 | 80.0 / 2.68 / 437 | 68.8 / 3.59 / 928 |
| HP-Lite | 72.9 / **0.43** / 230 | 72.3 / **0.80** / 203 | 64.3 / **2.18** / 985 |
| HP-Medium | 76.3 / 0.56 / 253 | 79.0 / 1.26 / 326 | 67.9 / 2.90 / 745 |
| HP-Heavy | **80.8** / 0.72 / 310 | **80.7** / 1.97 / 333 | **69.6** / 2.95 / 888 |

GLM-5.2×Claude Code 同型（heavy：TB2 81.4%/$0.62、SWE 77.3%/$1.01、PB 64.4%/$14.95）。
消融：去测试合成器 → −3.4~−10.0pp；去 planner → 多数场景双劣；RHO＋单机制均被支配。
演化动态：heavy 档 TB2 三轮 74.6%→80.8%、$0.91→$0.72；SWE-Pro medium 直到第三轮才
「双改善」（70.0%/$1.57 → 79.0%/$1.26）——**递归轮次有真实边际**。

### 2.5 弱点与边界（代码级）

| 发现 | 证据 | 影响 |
|---|---|---|
| 测试极薄 | `tests/` 287 行 / 2 文件 / 4 用例；无 CI 徽章与工作流 | 方法正确性主要靠论文实验背书；回归网弱 |
| POSIX-only | `hook.py`、`scripts/run_swebench_pro_harness_eval.py:10` 直接 `import fcntl`；本机实测 6 errors（§7.1） | Windows 生产环境不可直接运行 |
| 依赖重、耦合外部基准 | third_party 32,004 行＋Docker 镜像＋基准数据＋Codex CLI；`pyproject` 本地 editable 依赖 `datacurve-pier`/`programbench` | 复现门槛高；跨基准迁移需重写 runner |
| 验证集单 rollout | 每 epoch 每候选在验证集只跑 1 次（论文 §5.1），训练核才 G=3 | 选档噪声未量化；±std 只来自最终测试的 3 次重复 |
| label-free 判据的残余风险 | 合成测试由 LLM 生成，召回 83.3% 意味着仍有 ~1/6 失败漏判；「生成一次全程固定」防了漂移，防不了系统性误设 | 候选选择可能被坏测试误导；官方测试只是终审 |
| 成本口径是估算 | `pricing.py` 用公开牌价，注释明言「provider 折扣/长上下文乘数不可得，报告须称 estimate」 | 跨 provider 对比需谨慎 |
| 治理面缺失 | 无人工审批、无回滚 API、无多租户/鉴权；候选编辑靠 Git commit 追溯 | 研究装置形态，非生产系统 |

---

## 3. Neurova 对应面

> 取证：两路只读深度核查＋主代理承重断言亲验；行号绑定 HEAD `3f7c916be`（2026-11-13）。

### 3.1 运行时 harness 面：形态对应出人意料地齐

| HarnessPro 机制 | Neurova 对应物 | 状态 |
|---|---|---|
| 运行时钩子（PreToolUse deny / PostToolUse additionalContext） | `core/hooks_engine.py:27` `KNOWN_EVENTS=("PreToolUse","PostToolUse","Stop")`；挂载 `tool_executor.py:1192`（block→`hook_blocked`，L1210-1223；additionalContext→`hook_context` 并入结果 L1258-1261） | **有，且语义同构**；但 `Stop` 事件已定义、全仓无调用点——会话级钩子未接线 |
| 动态推理努力路由 | `agent/effort_inference.py:34` `infer_query_effort(text)`：强分析关键词或长度≥120→deep、精确寒暄→light、歧义→维持；`chat_pipeline.py:2454` `_resolve_auto_effort` 回写 metadata；`llm/provider_compat.py:56` 映射 light→None/standard→medium/deep→high；超时降级重试置 `reasoning_effort="low"`（`openai_loop.py:723-724`） | **有**——但推断是**纯关键词/长度启发式**，无 rubric 分类器、无置信度兜底、无工具预算联动 |
| 工具调用预算 | `security/agent_limits_settings.py:24`（token_budget 100k、max_loop_rounds 20、并行上限 4、doom 窗口）；`agent/gates.py` 四把门：`IterationGate`:106、`TokenBudgetGate`:128、`DoomLoopGate`:198、`GoalGate`:269，`GateRunner.on_round_end`:408 统一执行 | **有，且比对方多 doom-loop/目标门**；但阈值是**全局单一配置**，不按任务分档，无分段提醒 |
| 工具输出压缩 | `core/tool_offload.py:85` 超阈值全文落盘＋head/tail 400 字符预览＋`recall_history(tool_call_id=…)` 指针；`agent/tool_output_ref.py` OutputRef 引用化（默认开，env 逃生）；`context/orchestrator.py:255-330` 历史折叠/分层预算/microcompact | **有，形态接近 RTK/microcompact**；但阈值全局化，不随档位/profile 变化 |
| 轨迹记录 | `core/trace_recorder.py:139` 会话级轨迹树（SQLite/文件、可回放）＋`core/tool_trace.py:74` 逐工具证据（参数≤500 字符脱敏）＋`core/agent_run_ledger.py:81` 运行状态机＋Prometheus 指标（`metrics.py:339`） | **有，且维度更全**（含心跳/租约/续跑）；但无「G 次 rollout 联合诊断」的消费层 |
| 成本核算 | `core/usage_accounting.py:58` per-model/provider token 聚合＋`estimate_cost`:187 定价目录估算；`multi_model_client.py:855` 每调用从真实 `response.usage` 记账并落 SQLite；`models/cost_budget.py:37` 六域预算＋告警 | **有**——但粒度是「调用/模型/用户」，**无每任务成本单、无 Cost-of-Pass** |

### 3.2 演化与评测面：治理强，判据弱在「可执行」

- 技能文本进化已统一到 `SkillEvolutionService`：评测集**三级回退**（golden → 会话历史挖掘
  `eval/miner.py` → 合成 `eval/synthetic.py:48`）、留出集对比＋噪声带、约束闸、泄漏审查、
  近平分匿名 A/B、实验指纹、pending＋人工批准。**与 harness² 档 N1–N8/C1–C8 的落地状态
  一致，本文不重复立项。**
- 合成评测集的**判据形态**是 rubric 文本（`synthetic.py:5`「expected_behavior 是评分细则，
  不是精确文本」），由 LLM judge 打分——**没有可执行断言套件**。
- RAG 检索评测是真执行的（`benchmark/rag_eval.py` P/R/F1@K＋可选 judge），但只覆盖检索域。
- 通用 agent benchmark 端点**诚实退役**：`api/endpoints/benchmark.py:105-130` 只记 simulated、
  `score=None`——「不伪造分数」纪律的正确形态，但也意味着**没有可跑的通用 agent 批量
  跑分台架**。
- 成本在评测结果里有字段（`eval/runner.py:90-92` `cost_baseline/cost_candidate/cost_change`，
  序列化于 `:210-212`），RSI 参数链有 `_iterationCostVector`（`rsi/orchestrator.py:708`）——
  **成本被记录，但不进任何门控或选择目标**。
- 评测集构建无「难度×多样性」核选（golden→挖掘→合成的回退解决的是「有没有」，不是
  「选哪 10 个最划算」）；综述档 S 系列已立「配对探针/全成本/密封集」等项，本文不重复。

### 3.3 记忆与经验面：Neurova 的碾压区

HarnessPro **没有记忆系统**——跨任务复用只体现在「选出的 harness 工件」本身。Neurova 有
完整记忆/经验栈：MemCore（七类记忆＋四阶段生命周期＋来源信任级）、经验知识库 EKB
（证据三级纪律：工具回执＞服务端票据＞用户赞踩，只填 NULL 不可翻案）、经验结晶器
（Hebb 式零 LLM）、反思/模式挖掘/对话规则提取管线、以及**四阶段睡眠整合**（idle_tracker
驱动 light_sleep/rem/deep_sleep/hibernate，REM 期生成洞察，`/api/v1/sleep` 观测面）——
这正是 HarnessPro 论文里作为**基线**引用的 Sleep-time Compute 的超集。此域为本仓硬资产，
不因对照而退让。

### 3.4 治理与平台面

人工评审主 gate、五阶段门禁、负债反向闸、回滚与修订、沙箱、鉴权、多租户、渠道、i18n、
前端——HarnessPro 全部没有。研究装置与生产平台的差异单列为生产就绪度，不混入综合分。

### 3.5 对照后发现的本仓断点（每条带证据，按核心原则第 7 条写影响面）

**HN1｜成本只记账、不进目标；无每任务成本单与 Cost-of-Pass 读数**
- 现状：token/成本记账到「调用/模型/用户」粒度（`usage_accounting.py:58`、`multi_model_client.py:855`）；
  技能进化的成本字段只被记录（`eval/runner.py:90-92`），RSI 只有成本向量（`rsi/orchestrator.py:708`）。
- 影响面：无法回答「这个技能这轮改进，每成功一单花了多少钱、比基线省了还是贵了」；
  进化门只看质量分，可能采纳「质量 +0.1、成本 +80%」的候选；运营侧没有 lite/medium/heavy
  式的预算选档入口。数据已在库（llm 调用级 usage），缺的是**按任务聚合＋按判据消费**。

**HN2｜合成评测停在 rubric 文本，无可执行测试判据**
- 现状：`eval/synthetic.py:48` 生成 task_input＋expected_behavior(rubric)，判分走 LLM judge。
- 影响面：judge 的失败漏判直接进采纳决策（HarnessPro 实测 LLM 判分漏 58.3%）；工具型技能
  （有明确输入→输出契约）本可用可执行断言判「过/不过」，把 judge 降级为辅助。
- 边界：对话型/开放型技能不适用；golden/留出集仍是真值判据，合成测试只做**辅助判据层**
  与冷启动补充——不是替代（区别于 HarnessPro 的 label-free 场景）。

**HN3｜努力路由是关键词启发式，无置信度兜底与预算联动**
- 现状：`effort_inference.py:34` 纯文本规则；无「分类器＋置信度＋fallback profile」结构；
  档位只影响 thinking effort，不联动工具预算（gates 阈值全局）。
- 影响面：难任务可能被低估档位（关键词不命中即维持现状）；简单任务不会因「档位低」而
  收紧工具预算——省不了对方的「路由＋分档钩子」组合收益。

**HN4｜门控预算全局单一，无分档 profile；Stop 钩子未接线**
- 现状：`agent_limits_settings.py:24` 全局默认（100k token / 20 轮 / 并行 4）对所有任务一视
  同仁；`hooks_engine.py:27` 的 `Stop` 事件全仓无调用点。
- 影响面：无法按「任务档位」分配预算（贵任务多给、廉任务早停）；会话级钩子（如结束
  时沉淀、审计）无挂载点。四把门控的执行骨架已在（`gates.py`），缺的是**分档配置源与
  档位选择器**。

**HN5｜输出压缩阈值全局化**
- 现状：`tool_offload_settings.py`／OutputRef 阈值（8192 字符）为全局设置；历史折叠预算
  分层但不随部署档位变化。
- 影响面：同一套阈值既要伺候「深度研究型」又要伺候「寒暄型」任务，压缩激进度不可调；
  HarnessPro 按基准×档位调三套参数（900/1400/3000 token）的做法证明这里有真实优化空间。

**HN6｜演化评测集无难度×多样性核选；harness 无「多档工件」形态**
- 现状：评测集三级回退（golden→挖掘→合成）解决覆盖，不做「选哪 10 个探针任务」的
  核选；agent 配置（指令/预算/钩子/压缩）散落在 agent_config、settings、hooks.json，
  **没有可导出、可版本化、可按档位部署的 harness 工件**。
- 影响面：评测成本随评测集线性走，无「小核选集先探路」的省法；运营无法给「低成本
  部署」一份裁剪过的 harness 档。

---

## 4. 评分

### 4.1 权重与逐维判定

权重按「对 harness 自改进系统长期可信度的边际贡献」分配；方法域 70%（1–7 维）＋
工程域 30%（8–10 维）。与 harness² 档的十维不同处：本文把「成本入目标/多档交付」
与「运行时机制工程化」设为独立高权重维（这是 HarnessPro 的立身之本，也是 harness²
未覆盖的增量），并压缩了「上下文/提示工程」单列维（并入运行时机制与证据制度）。
**两个口径的分数不可互比。**

| # | 维度 | 权重 | HarnessPro | Neurova（当前） | 一句话判定 |
|---|---|---:|---:|---:|---|
| 1 | 闭环完整性（诊断→计划→编辑→评测→选择→递归） | 15% | 9.0 | 8.6 | HP 全链自动、多轮候选集、Git 可溯；N 治理闭环完整（统一 service/门禁/回滚）但无「harness 工件编辑循环」，RSI 实证递归未闭合（综述档结论） |
| 2 | 评测与证据制度 | 15% | 8.5 | 8.3 | HP 合成测试可执行、固定、防泄漏边界清晰，但验证集单 rollout、~17% 漏判；N 留出/噪声带/泄漏审查/诚实 None 更严，但判据靠 judge、benchmark 执行器退役 |
| 3 | 目标函数与选择机制（成本入目标/Pareto/多档交付） | 10% | 9.5 | 5.5 | HP 双目标＋三档选点是全文核心贡献；N 成本只记录（runner:90-92）不选择，无 CoP、无多档 |
| 4 | 轨迹诊断与失败归因 | 8% | 8.5 | 7.5 | HP 的 G=3 联合诊断带证据指针、直接喂计划；N 有 trace/tool_trace/缺口投递/失败归因，但无联合诊断消费层 |
| 5 | 运行时机制工程化（路由/预算钩子/压缩/缓存友好） | 12% | 9.0 | 8.0 | HP 五档路由＋分段硬停钩子＋按档压缩＋缓存前缀保护；N 四把门控＋启发式路由＋offload 压缩已接线，但全局单一、无分档、Stop 未接线 |
| 6 | 经验复用与跨任务迁移 | 5% | 6.0 | 9.0 | HP 只靠工件泛化、无经验库；N 有 MemCore/EKB/结晶器/睡眠整合/技能经验闭环 |
| 7 | 可复现与可审计 | 5% | 8.0 | 8.7 | HP 公开工件＋splits＋定价表＋离线测试；N 实验指纹进缓存/台账/审批/作业身份 |
| 8 | 测试与可验证性 | 10% | 4.0 | 8.5 | HP 287 行/4 用例、Windows 实跑 6 errors；N 2,572 文件/25,269 用例＋e2e/perf 门 |
| 9 | 生产安全与平台化 | 10% | 3.5 | 8.5 | HP 无沙箱/鉴权/多租户、外部 CLI 直连；N 平台面完整 |
| 10 | 规模控制与可维护性 | 10% | 7.5 | 6.3 | HP 边界清楚、规模小（src 11k）；N 大而全、审计在途 |

**加权结果**：
- HarnessPro：`0.15×9.0＋0.15×8.5＋0.10×9.5＋0.08×8.5＋0.12×9.0＋0.05×6.0＋0.05×8.0＋0.10×4.0＋0.10×3.5＋0.10×7.5 = 7.535 ≈ 7.5`
- Neurova：`0.15×8.6＋0.15×8.3＋0.10×5.5＋0.08×7.5＋0.12×8.0＋0.05×9.0＋0.05×8.7＋0.10×8.5＋0.10×8.5＋0.10×6.3 = 7.86 ≈ 7.9`

### 4.2 分域读数

- **方法域（1–7 维，70%）**：HarnessPro **8.6** / Neurova **7.9**。差距集中在第 3 维
  （成本入目标，3.5→9.5 vs 5.5）与第 5 维（分档运行时工程，9.0 vs 8.0）；第 6 维反向
  （N 9.0 vs 6.0）。
- **工程域（8–10 维，30%）**：HarnessPro **5.0** / Neurova **7.8**。差距在测试、生产安全、平台化。
- **生产就绪度（单列，粗算口径同 harness² 档）**：HarnessPro ≈ **4.0** / Neurova ≈ **8.4**。
- **结论**：**7.9 vs 7.5 的 0.4 领先是工程权重撑起来的；方法域 Neurova 落后 0.7**，落点
  非常具体——成本不入目标、判据不可执行、运行时不分档。这三件事都不需要推翻现有
  治理框架，是在既有骨架上补层。

### 4.3 哪些证据会改变评分

- 若 Neurova 把每任务成本单＋CoP 读数落格并接入进化门（HC1），第 3 维可到 7.5+，总分 +0.2。
- 若可执行合成测试在工具型技能上实证失败召回 ≥80%（HC2），第 2 维 +0.5，总分 +0.08。
- 若部署档位工件＋分档钩子落地（HC3/HC4），第 5 维可到 9.0，总分 +0.12。
- 若 HarnessPro 后续版本补上多 rollout 选档、跨平台与最小治理（审批/回滚），其第 2/8/9 维
  会上升，但那已不是本篇评估的版本。
- 论文数字均为作者自述（under review）；若正式版数据修订，§2.4 读数与第 3 维判定需复核。

---

## 5. 启发

### 5.1 概念层五条

1. **成本是行为，不是账单。** HarnessPro 的关键转译是：把「token 花销」从财务口径变成
   搜索压力——每个候选都要在「通过率-成本」平面上证明自己的位置。Neurova 的记账设施
   已经齐了，缺的是让**进化决策消费它**。落地不必照搬 Pareto 数学：先让「成本变化」
   成为技能/参数进化验收报告里的必填项与软门，再谈多档。
2. **「写测试」比「当裁判」可靠。** LLM 判分的系统性乐观（漏判 58.3%）在 harness² 档
   N 系列与综述档 S 系列里都有旁证。凡是**契约清晰、可重复执行**的技能面（工具型技能、
   工作流节点、检索质量），都应优先建「生成一次、全程固定」的可执行判据层；judge 留给
   开放型任务。防 gaming 的关键与 HarnessPro 一致：**测试生成与候选评测分离、生成物
   冻结、证据边界禁止从被测物反推期望**。
3. **档位是产品能力，不是配置技巧。** lite/medium/heavy 的本质是「同一引擎、三份可部署
   工件、按预算选档」。Neurova 已有全部零件（路由、门控、压缩、钩子），缺的是把它们
   打包成**版本化工件**并给运营一个选择入口。先做「档位=一组命名配置」的最小形态，
   不急着做工件市场。
4. **预算钩子要「分段劝、最后拦」。** 只设硬上限会制造悬崖（任务在 99% 处被砍）；
   只设软提醒不会真省。HarnessPro 的三段式（economy 提醒→strict 收敛→finalize 劝收尾→
   hard-stop 拒绝）加「提醒附在工具结果后保缓存前缀」的细节，是可以直接借的形态——
   在本仓对应「门控开火时向当轮注入引导文本」而非仅 TERMINATE。
5. **递归的边际在后面几轮。** SWE-Pro medium 档前两轮「涨分不省钱」，第三轮才双改善——
   单轮 RSI（含本仓当前技能进化的一次性提案形态）天然看不到这种复利。这与综述档
   「结构递归成立、实证递归未闭合」的判定互相印证：值得把「同一目标跨多轮持续改进、
   每轮带成本读数」作为 RSI 侧的观察指标，而不是急着加轮数。

### 5.2 候选清单（按优先级）

> 「理由」列只写本仓断点；「可借鉴机制」列只描述 HarnessPro 做法，不构成对齐承诺。
> 落地一律独立立项、先红后绿。

| # | 优先级 | 本仓断点（证据） | 可借鉴机制 | 建议落地形态 | 代价/风险 |
|---|---|---|---|---|---|
| HC1 | **P0** | HN1：成本不进目标、无每任务成本单/CoP | 成本进目标函数；Cost-of-Pass 口径；验证报告必含成本变化 | ① `llm_calls`/usage 按 run/task 聚合出「每任务成本单」；② 技能/参数进化验收报告加 `cost_per_task_baseline/candidate`＋CoP；③ 进化门加**成本软门**：候选成本涨幅超阈值（如 >20%）时强制人工复核或要求质量增益显著更高；先只读报告，后升门 | 低-中：聚合查询与报表；误伤风险由「软门＋人工复核」兜底；不改判据真值 |
| HC2 | **P0** | HN2：合成评测是 rubric 文本，判分靠 judge | 可执行测试合成器：生成一次、全程固定、执行判分 | 对**工具型技能**（有明确 I/O 契约）建 `test_synthesizer`：从技能契约+历史成功案例生成断言用例（沙箱执行），评测时先跑测试套件、judge 只对开放维度兜底；防 gaming 闸：测试生成禁读候选正文（只读契约/基线轨迹）、生成物冻结、覆盖率与漏洞自检入报告 | 中：沙箱执行设施已有（工具沙箱/离线评测）；需定义「可测试技能」的准入形状；测试本身可能写错——保留 golden/留出真值门 |
| HC3 | **P1** | HN4/HN6：门控/压缩全局单一，无多档工件 | lite/medium/heavy 三档 harness 工件（指令+policy+钩子+压缩阈值打包） | 「执行档位」作为**命名配置集**（不新建存储）：`agent_limits_settings`＋offload 阈值＋努力路由参数按档位成组（如 `NEUROVA_EXEC_PROFILE=lite|standard|heavy`，默认 standard=现行为）；管理 API/页面可选档；先内部 env 门控 | 中：配置面分组与回填；档位间行为差异需测试钉住；不开放 agent 自改档位 |
| HC4 | **P1** | HN3/HN4：路由无置信度兜底、预算不分段、Stop 钩子未接线 | 分段预算钩子（economy/strict/finalize＋hard-stop）＋分类器置信度兜底 | ① `gates.py` 增加「阶段提醒」出口：门控按轮次阈值向当轮注入引导文本（复用 hook_context 通道），hard-stop 仍由现有 TERMINATE 承担；② `effort_inference` 加低置信度回退 standard 的显式规则；③ 接线 `Stop` 钩子（会话结束事件触发 hooks_engine） | 中：提醒注入点在 loop 内，需保缓存前缀（追加在工具结果后）；hard-stop 默认关、灰度开 |
| HC5 | **P2** | HN3：路由为关键词启发式 | rubric 分类器＋confidence_overrides＋fallback | 若 HC4 后仍观察到档位误判（用配对探针复核），再把启发式升级为「小模型 rubric 分类＋置信度兜底」；分类调用本身计成本、进 HC1 的账 | 中：每任务多一次小调用；rubric 需按本仓任务域自研，不抄对方文本 |
| HC6 | **P2** | HN6：评测集无核选 | 难度×多样性 coreset（DPP 思想） | 技能进化评测前，从候选评测集里按「难度加权＋失败指纹去重」选小核选集先探路（如 10–20 条），全量集只跑过门候选；与综述档 S 系列的配对探针共用设施 | 中：需要失败指纹/embedding；核选偏差需用「核选通过→全量复核」双段设计兜住 |
| HC7 | **P3** | HN5：压缩阈值全局化 | 按档位调压缩参数 | 随 HC3 档位化：lite 档更激进的 offload/head-tail 预算，heavy 档放宽；阈值入档位配置组 | 低：纯配置；需防「压缩过度导致工具结果不可用」的回归测试 |

**建议起手序**：HC1（成本账＋软门）→ HC2（可执行测试判据）→ HC3/HC4（档位与分段钩子）
→ HC5/HC6/HC7。HC1/HC2 直接补方法域最大失分点，且都复用既有设施（usage 记账、
沙箱、评测 runner、治理门）。

### 5.3 明确不建议照搬

1. **POSIX-only 钩子实现**：`fcntl` 文件锁（`hook.py`、`run_swebench_pro_harness_eval.py:10`）
   本机实测即挂；本仓跨平台（Windows 生产），进程内门控已是更优解，不引入外置脚本锁。
2. **用合成测试全面替代真值判分**：HarnessPro 的 label-free 是「没有官方测试」场景的
   不得已；本仓有 golden/留出集与人工评审，合成测试只做辅助判据与冷启动，判据真值
   层不退让。
3. **单 rollout 采纳**：HarnessPro 验证集每候选只跑 1 次即参与选档（训练核才 G=3）；
   本仓不应把「跑一次更好」当采纳依据——配对探针/多 rollout 的纪律按 designer 档
   P1-B 与综述档 S1 执行。
4. **32k 行 third_party 基准代码捆绑**：研究复现便利 vs 供应链/许可/维护负担；本仓
   外部依赖走包管理＋许可审查（PyMuPDF 替换先例）。
5. **无沙箱执行器直连生产链**：Codex CLI 网络不受限、Docker 直挂是研究装置形态；
   本仓工具沙箱与审计边界不为此让路。
6. **把「三档」做成营销分档而不配治理**：每档必须有各自的回归测试与成本读数，
   否则「lite」只是「更容易失败」的别名。

---

## 6. 待拍板问题（决策影响面）

> 按核心原则第 8 条：每题给选项、代价、不可逆点、影响面与推荐项。
> **本文只立项不拍板**；以下问题需用户裁定后才进入实施。

### T1｜成本是否进自动进化门？
- **A（推荐）**：先做「每任务成本单＋CoP 只读报表」，进化验收报告必含成本变化；
  第二步升**软门**（成本涨幅超阈值→强制人工复核）。代价：报表与聚合查询开发；
  不可逆点：无（只读起步）。影响面：`usage_accounting`、`eval/runner`、`eval/service`、
  技能进化前端报告页。
- **B**：直接硬门（成本变差即拒绝候选）。代价：可能误杀「质量大增、成本小涨」的候选；
  需先有可靠 CoP 口径。不可逆点：自动改动量下降。
- **C**：不进目标，成本只做运营报表。代价：HN1 长期存在，方法域差距保持。

### T2｜可执行合成测试的适用边界与防 gaming 强度？
- **A（推荐）**：只对「工具型/契约型技能」启用；测试生成器只读契约与**基线轨迹**
  （不读候选正文），生成物冻结入评测工件；执行走既有沙箱；golden/留出集真值门保留。
  影响面：`eval/synthetic.py` 旁新增执行判据层、评测 runner 判分顺序、沙箱配置。
- **B**：全技能面启用。代价：开放型任务无法断言，会退化为伪执行判据；不推荐。
- **C**：不做。代价：HN2 保持，judge 漏判继续进采纳决策。

### T3｜执行档位（lite/medium/heavy）以什么形态落地？
- **A（推荐）**：命名配置组＋env/API 切换，默认 standard=现行为；管理端只读展示各档
  参数与实测成本/质量读数。影响面：`agent_limits_settings`、offload settings、路由参数、
  管理 API/前端。
- **B**：做成可导出/导入的 harness 工件包（含指令文本），支持跨实例部署。代价：需要
  工件版本化、校验、回滚设施（接近 harness² 的 c1–c8 树），工作量大一档。
- **C**：不做档位，保持全局配置。代价：HN4/HN6 保持，运营无预算选档入口。

### T4｜分段预算钩子与 Stop 钩子的默认态？
- **A（推荐）**：阶段提醒默认开（只注入文本，风险低）；hard-stop 与 Stop 钩子默认关、
  env/管理端灰度开。影响面：`gates.py`、`hooks_engine`、loop 注入点。
- **B**：全部默认开。代价：生产轮次可能被意外砍尾；需先跑影子观察。
- **C**：全部默认关。代价：机制落格但无收益，等下次点单。

---

## 7. 证据附录

### 7.1 外部仓实测（本机 Windows 10.0.26300，Python 3.12.10）

```text
$ cd <tmp>/harnesspro-repo && python -I -c "sys.path.insert(0,'src'); unittest.discover('tests')"
ERROR: setUpClass (test_programbench_runtime.ProgramBenchRuntime) ... ModuleNotFoundError: No module named 'pier'
ERROR: test_budget_denial_and_repeated_denial_stop_are_preserved (test_release_runtime.ClaudeHookCompatibility) ...
ERROR: test_read_normalization_cannot_override_a_budget_denial ...
ERROR: test_static_harness_does_not_require_a_core_hook ...
ERROR: test_structured_images_remain_native_outputs ...
ERROR: setUpClass (test_release_runtime.ReleaseEntryPoints) ... ModuleNotFoundError: No module named 'fcntl'
Ran 4 tests in 0.344s  FAILED (errors=6)
```

与 harness² 档 §7.1 同款平台结论：**Windows 不可跑，Linux/uv 工具链为设计前提**；
未实跑其 benchmark（缺任务数据与模型端点），论文数字按「论文自述，未复现」引用。

### 7.2 规模读数

| 项 | HarnessPro（`6fd2d4db`） | Neurova（`3f7c916be`） |
|---|---:|---:|
| 方法/运行时 Python | 10,960（src/rho） | ≈346,580（全仓） |
| 评测 runner/脚本 | 9,548（scripts） | —（API/管线内） |
| harness 工件 | 6,227（9 档） | 无工件形态 |
| third_party | 32,004 | 依赖以包管理为主 |
| 测试 | 287 行 / 2 文件 / 4 用例 | ≈473,498 行 / 2,572 文件 / 25,269 用例 |
| 许可 | MIT＋第三方声明 | 仓内自有 |

### 7.3 关键行号索引

**HarnessPro（commit `6fd2d4db`；论文 arXiv:2610.26770v2）**
- policy 装载/校验：`src/rho/harness_runtime.py:12-151`（`_REASONING_EFFORTS`:12、
  `BudgetProfile`:16、`ConfidenceOverride`:46、`ModelClassifierConfig`:54、
  `HarnessRuntimePolicy`:129、阈值严格递增校验:175）
- 轨迹存储：`src/rho/stores/trajectory.py:13-125`（meta/events.jsonl/diff）
- usage 抽取与成本：`src/rho/observability.py:17-23`（四类 token 键）、`:104` extract_usage；
  `src/rho/pricing.py:29-80`（牌价目录＋estimate_note）
- 钩子语义：`harnesses/terminal-bench-2/medium/runtime/hook.py`（stdlib-only、fcntl 锁、
  deny 分支）；论文附录 D.1/D.3 完整摘录
- 工件结构：`harnesses/{benchmark}/{mode}/`＝README＋model_instructions＋profile_rubric＋
  policy.json＋hook.py（SWE-Pro 另有 bin/repair-verify＋checklists）
- 论文方法：§3 问题设定（式 1 双目标）、§4.1 算法 1、§4.2 三 agent（式 2–5）、
  §4.3 测试合成与选档（式 6–9）、附录 A.1 DPP（式 10–12）、附录 B 三份演化指令、
  附录 C 工件样例、附录 D 三档 policy/rubric 全文
- 主结果/消融：论文表 2（三基准×七方法）、表 3（消融＋RHO 变体）、图 4（演化动态）

**Neurova（HEAD `3f7c916be`，2026-11-13；主代理亲验项加 ✓）**
- 努力路由 ✓：`agent/effort_inference.py:34`；`agent/chat_pipeline.py:2454`、`:2961`；
  `llm/provider_compat.py:56`；`llm_client.py:282-289`；`agent/loops/openai_loop.py:297-300`、`:723-724`
- 门控/预算：`security/agent_limits_settings.py:24`；`agent/gates.py:106/:128/:198/:269/:408`；
  `agent/loops/base.py:368-450`；`agent/loops/turn_run_state.py:26`
- 钩子 ✓（Stop 未接线）：`core/hooks_engine.py:27`；`tool_executor.py:1192/:1210-1223/:1249/:1258-1261`；
  `tool_executor.py:1437-1470`（on_tool_executed 咽喉）
- 输出压缩：`core/tool_offload.py:39-50/:85/:123-128`；`agent/tool_output_ref.py:1-24/:55`；
  `context/orchestrator.py:255-330`
- 轨迹/台账：`core/trace_recorder.py:139/:256/:309/:328`；`core/tool_trace.py:44/:74`；
  `core/agent_run_ledger.py:81/:238`；`core/agent_run_store.py:47-64`；`core/metrics.py:339`
- 成本记账 ✓：`core/usage_accounting.py:19-23/:58/:187/:202`；`llm/multi_model_client.py:855/:870`；
  `models/cost_budget.py:37/:182-198`；`api/endpoints/budget_api.py`
- 演化/评测：`evolution/eval/runner.py:1-11/:30-31/:53-100（cost 字段 :90-92 ✓）`；
  `evolution/eval/synthetic.py:5/:48 ✓`；`evolution/eval/miner.py:1-8`；`eval/service.py:5-9`；
  `evolution/rsi/orchestrator.py:708`；`benchmark/rag_eval.py:1-52`；
  `api/endpoints/benchmark.py:105-130 ✓`（simulated 诚实标记）
- 记忆/睡眠：`mem_core.py:442/:964/:1007/:1100`；
  `cognitive_layers/memory_layer/models.py:15-87`；`memory_layer/manager.py:1654/:1693-1696/:2285`；
  `memory_layer/sleep.py:153/:635-690`；`core/idle_tracker.py:82/:243-321`；
  `skills/experience_knowledge_base.py:497-554`；`evolution/skill_review_gate.py:29-35`；
  `evolution/skill_experience.py:100-171`；`evolution/skill_attribution.py:128-199`
- 缺口反馈：`agent/loops/base.py:161-183`（`_recordHarnessGapFromExit`）；`agent/capability_gap.py:87-111`

---

## 8. 一句话收束

HarnessPro 证明了一件事：**递归自改进的下一步收益不在「更会改提示」，而在把「成本」
和「可执行判据」请进决策回路**——它用合成测试代替 judge、用 Pareto 选档代替单点最优、
用分档预算钩子把省钱的机制落到每一次工具调用；这三件事恰好是 Neurova 方法域落后的
0.7 分的全部来源。Neurova 不需要为此换轨：记账、门控、压缩、路由、沙箱、治理的零件
都已就位，按 HC1（成本入账入门）→ HC2（可执行测试判据）→ HC3/HC4（档位化工件与
分段钩子）补层即可；同时守住本仓的硬资产——真值判据、人工评审、回滚与那 2.5 万个
测试——不因「像对方」而退让。

---

## 9. 落地回执（2026-11-13 修复批，晚于上文评测快照）

> 用户点单「先把断点修复掉」后，按 §5.2 候选与 §6 推荐项（T1A/T2A/T3A/T4A）实施的
> 落地记录。评测正文（§0–§8）是当日评估快照，不因本节改写；本节只记「断点修了什么、
> 落在哪、怎么验的」。四批提交：`71db6a1f5`（批1）/ `256873e6a`（批2）/ `00d9e62ea`
> （批3）/ `3795b4a2a`（批4）。

### 9.1 逐断点落地状态

| 断点 | 落地形态 | 提交 | 关键落点 |
|---|---|---|---|
| HN1 成本不进目标 | 每任务成本账＋CoP＋成本软门 | `71db6a1f5` | `eval/cost_ledger.py`（EvalCostLedger＋costSoftGateVerdict）；runner 三返回路径按臂落 usage 差分；提案 `cost_gate`＋`requires_manual_review`（涨幅>0.2 软门） |
| HN2 判据靠 judge | 可执行测试判据层 | `256873e6a` | `eval/exec_suite.py`（TestSynthesizer＋冻结 suite_hash＋七种确定性断言 op）；runner 判定 2.15 非回归门（`exec_suite_regression`）；套件生成失败诚实回退 judge |
| HN3 路由无兜底 | 歧义显式回退 standard | `00d9e62ea` | `effort_inference.resolveQueryEffort`（explicit/inferred/fallback_standard）；`_resolve_auto_effort` 落档位＋来源标记（提示面同形：standard 不注入指令） |
| HN4 预算无分档/Stop 未接线 | 执行档位组＋分段提醒＋Stop 接线 | `00d9e62ea` | `agent_limits_settings.EXEC_PROFILES`（lite/standard/heavy，优先级 env>档位>文件>默认）；`agent/budget_stages.py`（economy/strict/finalize 纯文本提醒，两环注入，不造第二把 TERMINATE）；`hooks_engine.runStopHooks`（默认关，`NEUROVA_STOP_HOOKS=1` 灰度开） |
| HN5 压缩阈值全局化 | 按档溢出阈值 | `3795b4a2a` | `tool_offload_settings`：无显式设置时默认 64KB 按档缩放（lite ×0.5/heavy ×2，夹紧合法域）；显式设置优先于档位 |
| HN6 无核选/无多档工件 | 难度加权多样性核选 | `3795b4a2a` | `eval/coreset.py`（bigram Jaccard 距离＋信息量权重的确定性贪心，DPP 思想自研近似）；runner `eval_coreset_k>0` 时核选到 K 再走既有 split（默认 0=旧行为） |

**档位工件（HC3）的「多档部署工件」形态以命名配置组落地**（`NEUROVA_EXEC_PROFILE=
lite|standard|heavy`，standard=内置默认逐字不变）；管理端只读展示页未做（前端面另批）。

### 9.2 与 §6 拍板项的对应

- **T1**：按 A 先做只读成本单（`cost_summary` 进 run 审计与提案面），软门同步落
  （涨幅>20% ⇒ 人工复核，不自动拒绝）。
- **T2**：按 A——可执行测试只对 skill 类工件；生成器只读基线契约与参考任务面
  （不读候选正文）；套件冻结（suite_hash 进结果面）；断言引擎确定性、无代码执行；
  golden/留出真值门保留。
- **T3**：按 A——命名配置组＋env 切换，默认 standard=现行为；无管理端 UI（另批）。
- **T4**：按 A——分段提醒默认开（纯文本）；Stop 钩子与「硬停新档位」默认关
  （`NEUROVA_STOP_HOOKS=1` 灰度）；既有四把门控仍是唯一 TERMINATE 执法点。
- **HC5（rubric 分类器）**：按文档定位为 P2 条件项（HC4 后仍观察到误判才升），
  本批未实施——`resolveQueryEffort` 的显式回退已消除「歧义不留档」的失控形态。

### 9.3 验证证据

- **先红后绿**：`test_taskCostLedger.py`（11 项）、`test_execSuite.py`（14 项）、
  `test_budgetStagesAndProfiles.py`（25 项）、`test_coreset.py`（6 项）均先行红灯
  （ImportError/断言失败）后转绿；`test_effort_inference.py` 的歧义钉子同步改约。
- **回归**：`tests/unit/evolution` **1872 passed**；`tests/unit/agent` **1688 passed**＋
  2 项预存红（`test_tkg_retriever`，审计批次已登记的预存基线，与本批无关）；
  溢出/寻址/门控阈值/ hooks 定向 80+ 项全绿。
- **活体探针（教义第 4 条）**：`tests/manual/harnesspro_gaps_live.py`（跑毕即删）
  **21/21 PASS**——真实 usage_accounting 单例记账差分 → 成本账/CoP/软门全链；
  真实 settings/hooks 引擎上的档位切换、分段提醒、Stop 灰度；可执行套件合成→
  冻结→断言→非回归门。LLM 判分/执行/合成的模型调用为注入替身（离线无凭据，
  诚实声明）；`LIVE_ALL_OK`。
- **评分投影（自评，非承诺）**：§4.3 预期的第 3 维（成本入目标）与第 5 维（分档
  运行时）提升成立；第 2 维（可执行判据）就位。综合分预计 7.9 → ≈8.2，复核需
  按本文 §4 口径重评（本文不自行改分）。

### 9.4 本批明确的边界（不冒充完成）

- 执行档位目前是**进程级 env 选择**，没有管理端 UI 与按 agent 粒度的档位派发；
- 可执行测试合成器的 LLM 面在生产走 multi_model_client，其生成质量未经真实
  模型实证（离线探针用替身）——首次真实生成需按 HC2 的防 gaming 闸复核；
- 成本账的 usage 差分是**进程级**口径（并发 LLM 活动会并入，与
  `agent_turns_tokens` 同边界）——多租户按用户拆账是另一条已有线（usage_history）；
- `eval_coreset_k` 默认 0（能力在、默认不开），开启后的判据有效性需按 §5.2 HC6
  的「核选通过→全量复核」双段设计实证。

---

## 10. 复评与提升空间（2026-11-13 修复批后）

> 口径与 §4 完全一致（十维加权：方法 70%＋工程 30%）。HarnessPro 侧读数不变（7.5，
> 方法域 8.6 / 工程域 5.0）；本节只重打**本仓侧**。这是按同一标尺的自评复算，用于定位
> 剩余差距，不是重新立项评测，也不作为「达标」结论。

### 10.1 复评：7.9 → 8.2（方法域 7.9 → 8.4，工程域 7.8 持平）

| # | 维度 | 权重 | 修复前 | 修复后 | 变动依据（本批落点） |
|---|---|---:|---:|---:|---|
| 1 | 闭环完整性 | 15% | 8.6 | 8.6 | 不变——技能进化仍是单轮提案形态，递归多轮未动（见 R5） |
| 2 | 评测与证据制度 | 15% | 8.3 | **8.8** | 可执行断言层补上「判据可执行」缺口（§9 HN2）；防 gaming 边界落格；合成失败诚实回退 |
| 3 | 目标函数与选择机制 | 10% | 5.5 | **7.0** | 每任务成本账＋CoP 出街、成本软门进提案面——成本第一次进决策回路；但仍是「复核闸」不是「选择目标」，也无 Pareto 多档交付 ⇒ 不到 8（见 R1） |
| 4 | 轨迹诊断与失败归因 | 8% | 7.5 | 7.5 | 不变——数据在（tool_trace/缺口证据），联合诊断消费层未建（见 R4） |
| 5 | 运行时机制工程化 | 12% | 8.0 | **8.8** | 档位组＋分段提醒＋Stop 接线＋按档压缩（§9 HN3/HN4/HN5）；路由仍为启发式、档位为部署级而非任务级 ⇒ 与 9.0 的残差在 per-task 路由（见 R3） |
| 6 | 经验复用与跨任务迁移 | 5% | 9.0 | 9.0 | 不变 |
| 7 | 可复现与可审计 | 5% | 8.7 | **8.8** | 成本/断言面读数进 run 审计与提案（边际） |
| 8 | 测试与可验证性 | 10% | 8.5 | 8.5 | 新增 56 项定向测试；总量级不变 |
| 9 | 生产安全与平台化 | 10% | 8.5 | **8.6** | 新机制全部带默认态与灰度逃生门（边际） |
| 10 | 规模控制与可维护性 | 10% | 6.3 | 6.3 | 不变（本批净增约 +1,400 行源码/测试，规模棘轮照常） |

**加权**：Neurova **7.9 → 8.2**；对 HarnessPro（7.5）的领先扩大。**方法域 7.9 → 8.4**，
与 HarnessPro（8.6）的差距从 **0.7 收窄到 0.2**；工程域 7.8 vs 5.0 持平。

### 10.2 剩余提升空间（按优先级；均为候选，落地须按修复教义独立立项）

**方法域——对着 HarnessPro 还差的 0.2 分**

| # | 优先级 | 提升点 | 现状与差距 | 建议形态 | 验收思路 |
|---|---|---|---|---|---|
| R1 | **P0** | 成本从「复核闸」升「选择键」 | 成本已入账、进提案面，但候选间选择仍是质量分 argmax；HarnessPro 是性能-成本双目标选点 | 多候选排序引入「增益为主、CoP/成本变化为辅」的复合判据（如 ε-约束：增益达线后按成本升序）；成本软门升**可配置硬门**（管理员选） | 红灯：同等留出增益下，低成本候选胜出；成本数据缺失时诚实回退纯质量 argmax |
| R2 | **P0** | exec suite 真实模型实证＋断言扩展 | 合成器真实生成质量未实证（探针用替身）；断言只有 7 种字符串/正则级 op | 跑一次真技能「合成→冻结→执行→门」全链并据实调参；补 `json_path`/键集断言与「差分断言」（候选 vs 基线输出的 metamorphic 判据） | 真实技能上合成可用率、断言失败召回有读数；新 op 有红绿 |
| R3 | **P1** | **按任务动态档位**（HC5 正式立项） | 档位是部署级静态 env；HarnessPro 是每任务一次分类调用选 profile＋预算联动——这是运行时面剩下的主要形态差 | `effort_inference` 升小模型 rubric 分类器（置信度兜底、fallback standard），任务级选档并联动预算组/分段阈值 | 同一任务集上档位分布有读数；误判任务经配对探针复核不劣化 |
| R4 | **P1** | 轨迹联合诊断消费层 | tool_trace/缺口证据已采集，但没有「多轮聚合成结构化诊断（问题/影响/证据指针）→ 喂变异器」的层——HarnessPro Analyzer 形态 | 新增诊断聚合器：按任务聚合 tool_trace＋capability gap＋judge 反馈，产结构化诊断进变异器提示 | 变异器提示含诊断段；对照实验：有/无诊断段的提案质量读数 |
| R5 | **P2** | 递归多轮演化 | 技能进化是单轮提案→门→pending；HarnessPro/ModularRSI 的多 epoch 候选集递归未建（综述档：结构递归成立、实证递归未闭合） | 同一技能跨轮持续改进：上轮胜者作下轮基线，逐轮成本/增益轨迹入账 | 多轮轨迹读数；每轮均有成本单与回滚点 |

**工程域**

| # | 优先级 | 提升点 | 说明 |
|---|---|---|---|
| R6 | **P1** | 档位管理端 UI＋per-agent 档位 | 档位现为进程级 env；管理面只读展示与按 agent 粒度派发未做（API 侧已有 `get_limit_domains` 形态可循） |
| R7 | P2 | exec suite 覆盖面扩展 | 现只对 skill 类工件；tool_description/template/RAG 检索面可复用同一断言引擎 |
| R8 | P2 | 成本账按用户/租户拆账 | 现为进程级差分（并发并入）；`usage_history` 已带 user_id，可 join 出按用户成本单 |
| R9 | P2 | 观测面出街 | `cost_summary`/`exec_suite`/CoP 目前只在 run 审计文件与提案 JSON 里；API/前端读数未接 |
| R10 | **P0（事务性）** | 推送远端 | 本批 5 笔提交（4 代码批＋1 文档回执）＋本节更新尚在本地 main，未推双远端 |

### 10.3 继续守住的不做清单

- **不用 label-free 替代真值判据**：golden/留出集与人工评审仍是门；可执行断言是辅助
  判据层，不是替代（HarnessPro 的 label-free 是「没有官方测试」场景的不得已）。
- **不开放 agent 自改档位/prompt**：档位是运营/管理员决定；C8 可编辑面维持不开放。
- **不为 Pareto 数学把质量判据降级**：成本在本仓的定位是「同增益下选省的」，
  不是「省字先于对错」；HarnessPro 的性能地板（PR ≥ PR(h₀)）与本仓留出非退化门
  同义，已具备。
- **不照搬 POSIX-only 钩子/无沙箱执行器/单 rollout 采纳**（§5.3 维持）。

### 10.4 落地回执（2026-11-13 第二批：R1–R10 执行完毕）

> 用户点单「按照文档 10.2 部分 R1 到 R10 执行提升」后的落地记录。提交：
> `cbcd458c4`（R1）/ `5a5ed972a`（R2+R7）/ `42266a095`（R3+R6）/ `cd9b131b6`（R4）/
> `45e0a3fb0`（R5）/ `2758df499`（R8+R9）/ `456965495`（R2 加固）。

| 项 | 状态 | 落地形态与落点 |
|---|---|---|
| R1 成本升选择键 | **已落** | 近平分成本 tiebreak（增益达线且与最高分近平分的候选集选文本最短者；盲选让位、等长保持先到）；成本硬门 `cost_hard_gate_enabled/ratio`（默认关）；`cost_tiebreak` 读数出街（`eval/runner.py`、config） |
| R2 可执行测试实证 | **部分**（诚实边界） | 新增 `json_path`/`json_keys`/`differs_from_baseline`/`same_as_baseline` 断言 op；合成器 LLM 响应形态归一（mock/provider 对象路径取 content）。**真模型实证 SKIP**：本机 provider 走 mock 面（无真实凭据），合成诚实返回空套件——待有凭据环境复跑 |
| R3 按任务动态档位 | **已落（灰度）** | `agent/turn_profile.py`：turn 级 ContextVar 档位通道＋rubric 分类器（置信度<0.6 回退 standard、LLM 失败 fail-open）；`NEUROVA_TASK_PROFILE=1` 灰度开（默认关） |
| R4 轨迹联合诊断 | **已落** | `eval/failure_analysis.py`：失败证据按归一化模式聚合（次数/占比/最差分/例证/环节证据并集）→ `diagnosisDigest` 渲染「联合诊断」段进变异器；runner 按签名内省传参，旧签名契约不漂移 |
| R5 递归多轮演化 | **已落（service 级）** | `SkillEvolutionService.evolveRecursive`：上轮胜者作下轮基线，逐轮 rejected/reason/holdout/成本态/提案 id 轨迹，早停＋总改善；API 面未接（另批） |
| R6 档位派发 | **部分** | per-agent 档位存储（`security/agent_profile_settings.py`）＋governance GET/PUT `/governance/agent-exec-profiles[/{id}]`（仅管理员）＋轮次解析接线（显式 metadata > agent 存储 > 分类器 > 部署 env）；**前端 UI 未做** |
| R7 套件覆盖面扩展 | **已落** | `EXEC_SUITE_ARTIFACT_TYPES = (skill, template, tool_description)`；service 装配单点 `_execSuiteApplies`；预算上界同步 |
| R8 按用户成本 | **已落** | `usage_history.per_user_cost_totals`（按用户×模型聚合，`estimate_cost_for` 定价目录单点，未知模型 0 不伪造） |
| R9 观测面出街 | **已落（后端）** | `GET /analytics/cost-readout`：进程级快照＋按用户成本榜；run 审计文件本就含 `cost_summary/exec_suite` 全量 |
| R10 推送 | **本批执行** | fetch 远端确认未前移后推送（merge 不 rebase） |

**验证**：每项均先红后绿（test_costSelection 7 / test_execSuite 21 / test_taskProfile 21 /
test_governance_agent_profiles 5 / test_failure_analysis 10 / test_evolveRecursive 4 /
test_usage_cost_readout 6）；回归 `tests/unit/evolution` 408、agent 1713（+2 tkg 预存）、
治理/analytics/usage 定向 62、跨面终局 1931 全绿。

**过程发现（如实记）**：① `.gitignore` 既有临时脚本规则族（`diag*/check*/verify*/patch*` 等）
会命中正经源码模块——新模块命名需避开（diagnosis→failure_analysis 两次改名）；② R7 覆盖面
扩展后，service.evolve 对 template 等工件也会发起套件合成，离线测试目录经 conftest 增补
`_call_llm` 离线钉子（注入路径不受影响）后恢复全绿；③ 本机 provider 无真实凭据走 mock 面，
`result["response"]` 为 LLMResponse 对象——合成器出口已归一，`SyntheticDatasetBuilder`/
`SimulatedAgent` 的同形假设是**既有问题**（登记，未在本批扩大处置面）。

**复评分数维持 §10.1 的 8.2**（R1–R10 是把 §10.1 复评时的缺口落进代码；进一步的分数上移
取决于：真模型实证（R2）、按任务分类器的实装灰度（R3）、管理端 UI（R6）与递归多轮的
API/运营接线（R5）——这些是下一批的事，不在本文自行改分。

### 10.5 追补（同日，用户点单两项）

- **R3 分类器开关设置项化**（`81fd4f039`）：新增 `security/task_profile_settings.py`
  （JSON 持久化，优先级 env 灰度直开 > 设置文件 > 默认关）；`turn_profile.taskProfileEnabled`
  改读设置单源；governance GET/PUT `/governance/task-profile`（仅管理员）。
- **R6 前端 UI 补齐**（同提交）：SettingPage 新增「任务级档位分类」开关面板与
  「Agent 档位派发」面板（agent 列表 × lite/standard/heavy 选择，未设置显示
  「跟随部署档位」占位，变更即 PUT）；`settings.ts` 增 task-profile /
  agent-exec-profiles 客户端；i18n settings 段新增 8 键 ×11 语言。
- **验证**：taskProfile/governance 定向 33 绿；前端 vitest 2464 绿＋i18n 一致性 41 绿＋
  vue-tsc 0 错。
- **剩余尾巴**：R2 真模型实证（待有凭据环境）、R5 的 API/运营接线、coreset 双段实证。
