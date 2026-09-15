# Neurova × Hermes 自我进化机制代码级对比与升级方案

> 对比日期:2026-09-13
> 对比基线:Hermes 双仓库 —— `NousResearch/hermes-agent`(main,245,000 ★,last push 2026-09-13)与 `NousResearch/hermes-agent-self-evolution`(main,5,318 ★)vs Neurova `main`(385991cd)
> 方法:Hermes 侧 **浅克隆 + 全量源码通读**(self-evolution 仓库全量 12 个 .py + 主仓库 `agent/` `tools/` 关键子系统),所有 Hermes 结论有文件路径与行为佐证;Neurova 侧逐模块核对现有实现与接线状态,所有结论均有当前代码文件锚点。
> 前置说明:GitHub 上的 "Hermes" 指 Nous Research 的 `hermes-agent`(即过去的 OpenClaw 演进体,与已归档的 `neurova-openclaw-comparison` 同一脉络)。其自我进化机制**分两层住在两个仓库**,见 §2。

---

## 0. 结论先行(TL;DR)

Hermes 对 Neurova 最有价值的启发**不是"引入进化算法"**——Neurova 的进化基建(`neurova/evolution/` 9,915 行 + `evolution/rsi/` + 评审闸)在**规模上远超** Hermes 的 self-evolution 仓库(约 1,500 行)。启发在于 **Hermes 用极少的代码把"自我进化"约束成了"可度量、可回滚、不破坏现状"的工程闭环**:

1. **判分用 LLM-as-judge 多维细则,而非子串匹配**:`FitnessScore = 0.5·correctness + 0.3·procedure_following + 0.2·conciseness − length_penalty`。Neurova 的 `prompt_optimizer.py` 判分是 `required_elements` 子串包含检查——只能查"要素在不在",判不了"输出对不对"。
2. **变异是反射式的,不是规则式的**:GEPA 读执行 trace 理解**为何失败**,再做定向修改。Neurova 的 `skill_improver._suggest_fix` 是错误关键词 → 固定建议的**字典查表**(`"timeout" → "增加超时时间"`),从不看真实失败内容。
3. **留出集 + 固定种子**:变体在 holdout 上与基线对比,防过拟合且可复现。Neurova 无留出集概念——变体在原集上选最优。
4. **benchmark 是 GATE 不是 fitness**:技能分涨 20% 但系统 bench 掉 5% → **直接拒绝**。这条纪律让"自我进化"不能以局部最优牺牲整体。
5. **约束闸是硬闸**:尺寸预算(技能 ≤15KB / 工具描述 ≤500 字符)、增长上限(≤20%)、语义保持(不漂移)、全量 pytest 100%——违反任一即丢弃变体。
6. **遥测走旁路,绝不写进用户产物**:Hermes 把使用计数放 `.usage.json` 侧车,**永不写 SKILL.md frontmatter**,理由是技能会被分享/发布。这一点 Neurova 反而做得更好(走 manifest.json),但缺状态机。
7. **运行时自进化用后台 fork + 前台优先**:每回合后 daemon 线程重放会话快照问"该不该存/更新技能",继承父运行时命中**同一前缀缓存**;新用户回合到来即硬取消(2s 上界),**自我改进永不能阻塞用户**。

按"对 Neurova 现状的净增量 + 改动成本"排序的**可落地清单**(P0=1~2 周、P1=2~4 周、P2=长线):

- **P0-1 评测标尺升级**(Wave 1):LLM-judge 判分 + 反射式变异 + train/val/holdout 划分。这是全链地基,其余都是在它之上加约束。
- **P0-2 约束闸 + 回归门**(Wave 2):尺寸/增长/语义保持三闸 + benchmark 作 GATE 接线。
- **P1-3 技能遥测生命周期**(Wave 3):`active→stale→archived` 纯函数状态机 + pinned/protected 保护。**完全独立、零 LLM、可与 Wave 1 并行**。
- **P1-4 会话历史挖掘评测集**(Wave 4):从 `agent_run_store` + 会话历史解冷启动。
- **P2-5 技能库巩固(umbrella)**(Wave 5):类级技能合并,**Hermes 自身默认关**,建议同样处理,前三波成熟后再评估。

**关键工程决策:不引入 DSPy。** GEPA 的精华不在 DSPy 框架,在于"读 trace 做定向变异"——这部分用 Neurova 现有 `llm_router` 手写约 200 行即可,避免引入异步不兼容的新 SDK 依赖链,符合项目"只提升不下降、不动核心框架"的硬约束。

**明确不建议抄的**:DSPy/MIPROv2/Darwinian Evolver 三个外部引擎;Hermes 的 SKILL.md frontmatter 遥测方案(Nurova 的 manifest 侧车更好);curator 的 LLM 巩固 fork 默认启用(Hermes 自己都默认关)。

---

## 1. 规模与形态基线

| 维度 | Hermes self-evolution | Hermes 主仓库 | Neurova |
|---|---|---|---|
| 进化代码量 | ~1,500 行(12 个 .py) | learning/curator 子系统散布 | **9,915 行**(evolution/ + evolution/rsi/) |
| 引擎 | DSPy + GEPA(主)/ MIPROv2(备)/ Darwinian Evolver(码) | 无(运行时) | 自研遗传/棘轮/PrefixSpan/RSI 编排 |
| 评测集 | 四源:合成 / SessionDB 挖掘 / golden / 外部导入 | SessionDB | `prompt_optimizer.PromptEvalCase`(子串式)+ `rsi/eval_harness.py`(确定性) |
| 判分 | LLM-as-judge 多维细则 + 长度惩罚 | — | 子串包含检查(Wave 1 要升级的点) |
| 变异 | GEPA 反射式(读 trace) | 无 | 规则式变体 / 错误关键词字典 |
| 约束闸 | 尺寸/增长/缓存/语义/pytest 五闸 | — | 仅 `skill_review_gate`(管人审,不管体积与漂移) |
| 优化目标 | 技能文本 / 工具描述 / 提示段 / 代码 | 技能生命周期 / 记忆 | 工具序列 / RSI 系统参数 |
| 部署 | 永远走 PR,绝不直提 | 归档可恢复 | 评审闸 PENDING 人审 + rollback_manager |
| 运行时自进化 | — | background_review fork + curator | `post_chat_pipeline`(内联,无 fork) |

**规模反差的关键结论**:Neurova 的进化是**结构级**的(工具序列遗传、RSI 参数棘轮),Hermes 补的是**文本级 + 有标尺**的闭环。两者不冲突,是互补的。

---

## 2. Hermes 机制解剖

### 2.1 两层架构

| 层 | 所在 | 载体 | 职责 |
|---|---|---|---|
| **B 层(离线进化管线)** | 独立仓库 `hermes-agent-self-evolution` | DSPy + GEPA | **operates ON 主仓库而非 inside it**——零侵入主代码,只产出 PR |
| **A 层(运行时自进化)** | 主仓库 `agent/` | 后台 fork + 纯函数状态机 | 每回合后台复查 + 技能库空闲维护 |

B 层的"独立仓库、零侵入、产出 PR"本身是一条设计启发:**把高风险的自修改能力隔离在主系统之外,通过 PR 边界强制人审**。

### 2.2 B 层:离线进化管线(`hermes-agent-self-evolution`)

**分层目标**(按价值/风险排,`PLAN.md`):

| Phase | 目标 | 引擎 | 状态 |
|---|---|---|---|
| 1 | 技能 SKILL.md | DSPy + GEPA | ✅ 已实现 |
| 2 | 工具描述 | DSPy + GEPA | 🔲 Planned |
| 3 | 系统提示段 | DSPy + GEPA | 🔲 Planned |
| 4 | 工具实现代码 | Darwinian Evolver | 🔲 Planned |
| 5 | 持续改进循环 | 自动管线 | 🔲 Planned |

**优化循环**(`evolution/skills/evolve_skill.py`):

```
加载基线技能 → 校验基线约束 → 生成/加载评测集
  → 循环{ GEPA 反射式变异 → 全量评测打分 }
  → 约束闸校验最优变体
  → 留出集对比基线(avg_evolved - avg_baseline)
  → 达标 → 产出 PR(含 metrics.json:train/val/holdout 三集分数 + 尺寸变化)
```

**评测集四源**(`core/dataset_builder.py` + `core/external_importers.py`):

| 源 | 做法 | 文件锚点 |
|---|---|---|
| A 合成 | 强模型读技能 → 生成 `(task_input, expected_behavior 评分细则)`;细则是 rubric 不是精确文本 | `dataset_builder.SyntheticDatasetBuilder` |
| B SessionDB 挖掘 | 真实会话中技能被加载的对话 → LLM-as-judge 打分;高分做好例、低分做 GEPA 反思的失败例 | `external_importers.RelevanceFilter` |
| C golden | 手写 JSONL,关键技能才投入 | `dataset_builder.GoldenDatasetLoader` |
| D 外部导入 | Claude Code `~/.claude/history.jsonl`、Copilot `events.jsonl`、Hermes `sessions/*.json`——**用已有工具历史解"新用户无数据"冷启动** | `external_importers.{ClaudeCode,Copilot,HermesSession}Importer` |

挖掘管线有**两级筛选**:便宜词面启发式预筛(`_is_relevant_to_skill`)→ LLM 相关性精筛(`RelevanceFilter.ScoreRelevance`),并统计 LLM 错误率上报。

**密钥清洗**(`external_importers.SECRET_PATTERNS`):正则覆盖 Anthropic/OpenRouter/OpenAI/GitHub/Slack/Notion/AWS token + Bearer 头 + PEM 私钥 + `password=/secret=/token=` 赋值。**任何命中即剔除该条**。

**适应度函数**(`core/fitness.py`):

```python
composite = max(0.0, 0.5*correctness + 0.3*procedure_following + 0.2*conciseness - length_penalty)
# length_penalty: artifact_size/max_size > 0.9 后线性爬升,上限 0.3
```

优化期间为省钱用**关键词重叠**做快代理(`skill_fitness_metric`),最终留出集才用真 judge。解析失败退回中性 0.5。

**约束闸**(`core/constraints.py`),每个变体必须全过:

| 闸 | 阈值 | 理由 |
|---|---|---|
| `size_limit` | 技能 15KB / 工具描述 500 字符 / 参数描述 200 字符 | 工具 schema 每轮都发,每个字符乘以整个对话 |
| `growth_limit` | ≤基线 +20% | 防提示词膨胀退化注意力 |
| `non_empty` | 非空 | — |
| `skill_structure` | frontmatter 含 name + description | 结构完整性 |
| `test_suite` | `pytest tests/ -q` 100% 通过,300s 超时 | 硬地板 |
| 缓存兼容 | 绝不热插拔进活跃会话 | 只对新会话生效 |
| 语义保持 | 与基线语义不漂移 | 防跑题 |

**分层闸设计**(`PLAN.md` "Benchmarks as Fitness Signals"):

```
候选变体
  ├─► pytest(100% 必须过)──────── GATE 1:功能正确性
  ├─► TBLite 快子集(20 题)────── GATE 2:能力快检(~20 分钟)
  ├─► 任务专属评测集 ───────────── FITNESS:技能质量分
  ▼
仅 Top 3
  ├─► 全量 TBLite(100 题)─────── GATE 3:回归详检
  ├─► YC-Bench fast_test ───────── GATE 4:长程连贯性
  ▼
最优候选 → PR(含全指标)
```

**核心原则(原文)**:*"Benchmarks are GATES, not fitness functions."* 一个提升技能质量 20% 但使 TBLite 掉 5% 的变体被 **REJECTED**。

### 2.3 A 层:运行时自进化(主仓库)

**`agent/background_review.py`** —— 回合后台复查:

- `run_conversation` 每回合后可 spawn daemon 线程,重放会话快照问"该不该保存/更新技能或记忆?",直接写 store。
- fork **继承父运行时**(provider/model/凭据/缓存系统提示)→ 命中**同一前缀缓存**;若路由到不同模型则缓存本就冷,改重放压缩摘要。
- **前台优先**:新用户回合到来即 `cancel_background_review_for_live_turn()`,2s 上界后日志告警并放行——*"self-improvement work must never block a user-facing turn"*(issue #84423)。
- 输入 token 总量预算 600k(`_REVIEW_MAX_INPUT_TOKENS_DEFAULT`),`<=0` 禁用。
- 工具白名单 + 线程作用域静默。

**`agent/curator.py`** —— 技能库后台园丁,**空闲触发(无 cron 守护)**:

两段式设计:

1. **确定性生命周期(纯函数,零 LLM)**:`apply_automatic_transitions()`
   - `active → stale`(14 天无活动)→ `archived`(30 天)
   - `pinned` 技能全绕开;`cron` 引用的技能视为 pinned
   - **从未活跃的技能锚 `created_at`,不自归档**(`use_count == 0` 是"无证据",不是"陈旧")
   - 首次见到先 `seed_record_if_missing`,延迟一个周期(全新安装绝不首次就改动技能库)
2. **LLM 巩固 fork(默认关,`DEFAULT_CONSOLIDATE = False`)**:umbrella-building 提示
   - 把上百个"一会话一窄技能"合并成少数**类级技能**
   - **只归档不删除**(`.archive/` 可恢复)
   - "读前写"强制:写前必须 `skill_view` 同一目标,否则 REFUSED
   - **包完整性检查**:`references/` 必须重新编目,不留悬空链接(issue #96962)

**`tools/skill_usage.py`** —— 遥测与来源:

- 侧车 `~/.hermes/skills/.usage.json` 按技能名存,**永不写 SKILL.md frontmatter**
- 跨进程文件锁(`fcntl`/`msvcrt`)+ 原子写
- `created_by: agent` 由 `skill_manage` **显式标记**,*"never inferred from location"*
- `PROTECTED_BUILTIN_SKILLS`:承重内置技能永不归档

**`agent/learning_graph.py` + `learning_mutations.py`** —— 学习图:

- 节点 = 非 base 已学技能 + `MEMORY.md`/`USER.md` 分块
- 边 = 声明式 `related_skills` + 记忆↔技能词面重叠(top-4)
- 用户可编辑/删除;删除技能是**归档**(`hermes curator restore` 可恢复)

**`agent/learn_prompt.py`** —— `/learn` 硬规则:

- **`description` ≤60 字符**——因为系统提示技能索引在 60 字符截断,**超了会静默不路由**(最常被违反且非装饰性)
- 源文本消毒:提示注入 + 双向 Unicode(Trojan Source)
- 知识库技能布局:精简 SKILL.md 索引 + `references/` 逐章按需加载

---

## 3. Neurova 现状核对

### 3.1 已有的(不必重建)

| 组件 | 文件 | 行数 | 状态 |
|---|---|---|---|
| 工具序列遗传引擎 | `neurova/evolution/genetic_engine.py` | 599 | 已接线 `post_chat_pipeline._step_genetic_evolution` |
| PrefixSpan 模式挖掘 | `neurova/evolution/pattern_miner.py` | 357 | 已接线 |
| 闭环编排 | `neurova/evolution/closed_loop.py` | 824 | 已接线 |
| RSI 编排器 | `neurova/evolution/rsi/orchestrator.py` | 777 | **已接线** `agent_core.py:1481` |
| 确定性评测集 | `neurova/evolution/rsi/eval_harness.py` | 319 | 已作 RSI 棘轮的"行为安全地板" |
| 自我改进提案 | `neurova/evolution/rsi/self_improvement_proposer.py` | 966 | PENDING 人审面已存在 |
| 部署控制器 | `neurova/evolution/rsi/deployment_controller.py` | 171 | 五阶段渐进部署 |
| 回滚管理 | `neurova/evolution/rsi/rollback_manager.py` | 131 | — |
| 技能改进器 | `neurova/evolution/skill_improver.py` | 731 | 已采集使用数据 |
| 提示优化器 | `neurova/skills/prompt_optimizer.py` | 315 | 确定性评测集驱动(v2 重写) |
| 评审闸 | `neurova/evolution/skill_review_gate.py` | 32 | C10,默认开,四类产物统一裁决 |
| 技能使用遥测 | `neurova/skills/skill_service.record_skill_usage` | — | C11,已持久化 `use_count/success_count/last_used_at_ms` |
| 安全扫描 | `neurova/skills/security_scanner.py` | 908 | 正则库可直接复用 |

### 3.2 真实缺口(逐条对位)

| # | Hermes 机制 | Neurova 现状 | 缺口定性 |
|---|---|---|---|
| G1 | LLM-as-judge 多维细则 | `prompt_optimizer.PromptEvalCase` 子串包含检查 | **判分无 LLM 语义**——判不了"输出对不对" |
| G2 | GEPA 反射式变异(读 trace) | `skill_improver._suggest_fix` 错误关键词 → 固定建议字典 | **变异不反射**——`"timeout"→"增加超时时间"`,从不看真实失败内容 |
| G3 | train/val/holdout + 固定种子 | 无 | **无留出集**——变体在原集选最优,过拟合无防护 |
| G4 | 尺寸/增长/语义保持闸 | `skill_review_gate` 只管"要不要人审" | **无约束闸**——产物体积膨胀、语义漂移无人管 |
| G5 | benchmark 作 GATE | `eval_harness` 范式已存在,但只服务 RSI 参数 | **未接到技能/提示进化** |
| G6 | 技能遥测生命周期状态机 | `record_skill_usage` 有计数,无状态 | **无 active→stale→archived**,无 pinned 保护 |
| G7 | 会话历史挖掘评测集 | `agent_run_store`(SQLite 状态机)+ 会话历史俱在 | **未用作评测集来源**,冷启动算法无数据 |
| G8 | 后台 fork + 前台优先 | `post_chat_pipeline` 内联执行 | 无 fork,自我改进与用户回合争资源 |
| G9 | 只归档不删除 | `skill_service` 有 enable/disable,无归档 | 缺归档语义 |

**缺口集中在四点:判分方式、变异方式、留出集、约束闸。** 前两项是 P0;基建(评测集外壳、使用采集、部署控制器、回滚、评审闸、安全扫描)已存在,可直接复用,这是本方案能以低成本推进的前提。

---

## 4. 升级方案

### 4.0 总体设计

**不引入 DSPy(第一个关键决策)。** GEPA 的精华不在 DSPy 框架,在于"读执行 trace 理解为何失败,再做定向变异"——用现有 `neurova/llm/llm_router` 手写约 200 行即可。避免引入同步/异步不兼容的新 SDK 依赖链,符合项目"只提升不下降、不动核心框架"的硬约束。

**避免 split-brain(项目 ADR0011 教训)。** 不新建平行评测集,而是**扩展** `prompt_optimizer.PromptEvalCase`,双路径保持后向兼容。

**三层递进(对齐现有 RSI 五阶段部署控制器):**

```
Wave 1  评测标尺升级      判分 子串→LLM-judge;变异 规则→反射;加留出集     [P0]
Wave 2  约束闸 + 回归门    尺寸/增长/语义保持;benchmark 作 GATE 接线         [P0]
Wave 3  技能遥测生命周期   active→stale→archived + pinned/protected 保护     [P1]
Wave 4  会话历史挖掘评测集  从 agent_run_store 解冷启动                      [P1]
Wave 5  技能库巩固(umbrella)  可选,依赖前三波成熟                          [P2]
```

每波中途有**验证闸**:不达标不进下一波。

---

### Wave 1 — 评测标尺升级 [P0]

#### 1.1 扩展既有评测集抽象(不另起炉灶)

**修改** `neurova/skills/prompt_optimizer.py` 的 `PromptEvalCase`:

```python
@dataclass
class PromptEvalCase:
    case_id: str
    description: str
    task_input: str = ""                 # 新增:真实任务输入(judge 用)
    expected_behavior: str = ""          # 新增:评分细则(rubric),非精确文本
    required_elements: List[str] = ...   # 保留:快速路径
    forbidden_patterns: List[str] = ...
    max_length: Optional[int] = None
    weight: float = 1.0
    scorer: str = "auto"                 # "auto"|"judge"|"substring"
```

`PromptEvalSet.score_prompt` 增加**双路径**:用例有 `expected_behavior` 走 judge,否则退回子串检查——保持后向兼容,历史调用面 `neurova/skills/auto_skill_improver.py` 零破坏。

#### 1.2 新增模块 `neurova/evolution/eval/`

```
neurova/evolution/eval/
├── __init__.py
├── config.py         # EvolutionConfig
├── fitness.py        # FitnessScore + LLMJudge
├── dataset.py        # EvalExample / EvalDataset(train/val/holdout)
├── mutator.py        # ReflectiveMutator(反射式变异)
└── runner.py         # SkillEvolutionRunner(优化循环)
```

**`config.py`** —— 对位 Hermes `core/config.py`:

```python
@dataclass
class EvolutionConfig:
    judge_model: str = ""                   # 默认取 llm_router 默认小模型
    optimizer_model: str = ""
    iterations: int = 10
    max_skill_size: int = 15_000            # 对齐 Hermes
    max_tool_desc_size: int = 500
    max_param_desc_size: int = 200
    max_prompt_growth: float = 0.2
    eval_dataset_size: int = 20
    train_ratio: float = 0.5
    val_ratio: float = 0.25
    holdout_ratio: float = 0.25
    seed: int = 42                          # 切分可复现
```

**`fitness.py`** —— 直接对位 Hermes `core/fitness.py`:

```python
@dataclass
class FitnessScore:
    correctness: float = 0.0
    procedure_following: float = 0.0
    conciseness: float = 0.0
    length_penalty: float = 0.0
    feedback: str = ""          # 供反射式变异消费
    @property
    def composite(self) -> float:
        return max(0.0, 0.5*self.correctness + 0.3*self.procedure_following
                        + 0.2*self.conciseness - self.length_penalty)

class LLMJudge:
    async def score(self, *, task_input, expected_behavior, output,
                    skill_text, artifact_size=None, max_size=None) -> FitnessScore
```

- 用 `llm_router` 的 judge 模型(小模型,省成本),结构化 prompt + JSON 解析(项目已有 LLM 输出解析惯例)。
- 长度惩罚:超上限 90% 后线性爬升,上限 0.3(原样照搬)。
- 解析失败 `_parse_score` 退回中性 0.5(对齐 Hermes,不因模型抖动崩)。

**`dataset.py`** —— 四源裁剪为三源:

```python
@dataclass
class EvalExample:
    task_input: str
    expected_behavior: str      # rubric
    difficulty: str = "medium"
    category: str = "general"
    source: str = "synthetic"   # synthetic|history|golden

@dataclass
class EvalDataset:
    train: list[EvalExample] = ...
    val: list[EvalExample] = ...
    holdout: list[EvalExample] = ...
    def split(self, ratios=(0.5, 0.25, 0.25)) -> "EvalDataset"
    def save(self, path: Path); @classmethod load(cls, path)
```

切分用 `random.Random(seed)`,保证可复现(测试要能断言)。

**`mutator.py`** —— Wave 1 的价值核心,对位 GEPA 反射:

```python
class ReflectiveMutator:
    async def mutate(self, *, artifact_text: str, artifact_type: str,
                     failures: list[JudgeFailure], constraints: dict) -> str
    # failures = 上一轮在 val 集上得分最低用例的 (task, output, feedback)
    # prompt 要求:读失败原因 → 提出定向修改 → 保持原意图 → 不超预算
```

对照现有 `prompt_optimizer.generate_variants` 的"加角色段/加结构段"——那是**盲目变异**;这里是**定向变异**。两者共存:规则变体作冷启动种子,反射变异作迭代主力。

**`runner.py`** —— 优化循环,照搬 `evolve_skill.py` 骨架:

```
加载基线 → 校验基线约束 → 生成/加载评测集
  → 循环{变异 → 全量打分 → 记录}
  → 约束闸校验最优变体
  → 留出集对比基线
  → 达标 → 产出提案(进评审闸)
```

#### 1.3 接线到现有 `skill_improver.py`

`skill_improver._suggest_fix` 的字典查表(`skill_improver.py:299-310`)是**根因级缺陷**。修改:

- 保留 `record_usage` / `_analyze_failure_pattern`(失败聚类有价值)
- `_generate_improvement` 改为:有评测集时走 `ReflectiveMutator`,无评测集时退回原字典(开关控制)

#### 1.4 开关

`NEUROVA_TEXT_EVOLUTION=0` 整体关闭(默认关,opt-in)——对齐项目 C10"进化产物默认待审"哲学与 Hermes curator `consolidate` 默认关。

#### 1.5 测试(TDD,先红后绿)

| 测试文件 | 覆盖 |
|---|---|
| `tests/unit/evolution/eval/test_fitness_score.py` | composite 权重与长度惩罚曲线、解析失败退回 0.5 |
| `tests/unit/evolution/eval/test_dataset_split.py` | 固定种子切分可复现、边界(1 条/空集) |
| `tests/unit/evolution/eval/test_reflective_mutator.py` | mock LLM:失败反馈进 prompt、产出非空、预算约束 |
| `tests/unit/evolution/eval/test_runner_holdout.py` | **变体只在原集涨、留出集跌 → 拒绝** |
| `tests/unit/skills/test_prompt_optimizer_judge_path.py` | 双路径 + 后向兼容 |

#### 1.6 验收标准

- [ ] `FitnessScore.composite` 满足 `.5/.3/.2 − penalty`,与 Hermes 数值一致
- [ ] **留出集回归测试:构造"过拟合变体"必须被拒绝**(先红后绿)——这是本波核心断言
- [ ] `prompt_optimizer` 历史调用面零破坏
- [ ] mock LLM 下单测毫秒级,不打真实 API
- [ ] 全部新代码默认关闭,不影响现有 pipeline

**LOC 预估**:新增约 700-900 行(含测试),`prompt_optimizer.py` 净增约 60 行。

---

### Wave 2 — 约束闸 + 回归门 [P0]

#### 2.1 新增 `neurova/evolution/eval/constraints.py`

对位 Hermes `core/constraints.py`:

```python
@dataclass
class ConstraintResult:
    passed: bool; name: str; message: str; details: str = ""

class ConstraintValidator:
    def validate(self, text: str, artifact_type: str,
                 baseline_text: str | None = None) -> list[ConstraintResult]
    # 1. size_limit      — skill ≤15KB / tool_desc ≤500 / param ≤200
    # 2. growth_limit     — 相对基线 ≤20%
    # 3. non_empty
    # 4. structure        — SKILL.md frontmatter(name+description)
    # 5. semantic_similarity — 与基线语义不漂移
```

**语义保持**是 Hermes 有而 Neurova 完全缺的一环。实现用现有 embedding 栈(`neurova/embedding/` + 本地 bge onnx):余弦相似度 < 阈值(如 0.75)即判漂移。embedding 不可用时退回 token Jaccard(`learning_graph._tokenize` 同款),保证离线可用。

#### 2.2 benchmark 回归门接线

复用 `rsi/eval_harness.py` 既有范式(**不新建**),把 `run_iteration` 暴露给 Wave 1 的 runner 作 GATE:

```python
# runner 选最优变体后
gate = eval_harness.run_all()
if gate.gain < -tolerance:  reject(variant)   # bench 回退 → 拒绝,无论技能分多高
```

#### 2.3 测试与验收

- `tests/unit/evolution/eval/test_constraints.py`:五类闸逐项 + 边界(恰好等于上限/差 1 字符)
- `tests/unit/evolution/eval/test_semantic_gate.py`:同义改写通过、主题漂移拒绝
- 验收:**"bench 回退即便技能分 +20% 也拒绝"** 回归测试先红后绿

**LOC 预估**:约 350 行(含测试)。

---

### Wave 3 — 技能遥测生命周期 [P1]

**完全独立、零 LLM、可与 Wave 1 并行开工。**

#### 3.1 扩 `skill_service.py` 的 usage 加状态字段

现有 `record_skill_usage` 已写 `usage{use_count,success_count,last_used_at_ms}` 到 manifest。**不新开侧车文件**(项目技能用 manifest.json 已足够),在其上加:

```python
usage["state"] = "active"        # active|stale|archived
usage["pinned"] = False
usage["created_by"] = ""         # "agent"|"user"|"hub" —— 显式标记,绝不按位置推断
usage["last_activity_at_ms"] = 0
```

#### 3.2 新增 `neurova/evolution/skill_lifecycle.py`(纯函数,无 LLM)

对位 `curator.apply_automatic_transitions`:

```python
def apply_transitions(now=None) -> dict[str, int]:
    # active → stale (14d 无活动)
    # stale  → archived (30d)
    # 用后回暖 → reactivated
```

三条保护语义(照搬,Hermes 踩过坑):

1. `pinned` 技能全绕开
2. `created_by != "agent"` 的(builtin/hub/user)不动
3. **从无活动的技能锚 `created_at`,不自归档**;首次见到先 seed,延迟一个周期

归档 = 移到 `.archive/`(可恢复),**永不删除**。

#### 3.3 测试与验收

- `tests/unit/evolution/test_skill_lifecycle.py`:14/30 天边界、pinned 豁免、never-active 不归档、seed 延迟首次
- 验收:每一条保护语义有独立断言

**LOC 预估**:约 300 行(含测试)。

---

### Wave 4 — 会话历史挖掘评测集 [P1]

#### 4.1 新增 `neurova/evolution/eval/miner.py`

对位 `core/external_importers.py`,数据源换成本项目的:

- **源 A**:`core/agent_run_store.py` 的 `agent_runs` 表(session_id/message_digest/status)——挖真实任务
- **源 B**:会话历史(复用 memory 系统会话存储)
- **源 C**:golden JSONL(手写,关键技能)

流程:

```
抽取 (user_input, assistant_output)
  → 密钥清洗(复用 security_scanner,不重写)
  → 两级筛选(便宜词面预筛 → LLM 相关性打分)
  → 生成 EvalExample
  → 切分落盘
```

#### 4.2 测试与验收

- `tests/unit/evolution/eval/test_miner_secrets.py`:**含 API key 的会话必须被剔除**(照搬 Hermes 密钥矩阵:sk-/ghp_/AKIA/xoxb-/Bearer/PRIVATE KEY)
- `tests/unit/evolution/eval/test_miner_relevance.py`:两级筛选,LLM 失败计数上报

**LOC 预估**:约 400 行(含测试)。

---

### Wave 5 — 技能库巩固(umbrella)[P2,可选]

对位 `curator` 的 LLM 巩固 fork:识别前缀簇 → 合并成类级技能 → **只归档不删除**、包完整性检查(`references/` 必须重新编目,不留悬空链接)、读前写强制。

**依赖前三波成熟。Hermes 自身把这一步默认关且标记 opt-in——建议同样处理,前三波跑出真实增益再评估。**

---

## 5. 贯穿性纪律(不可让步项)

从 Hermes 抄的、必须落到每一次进化的硬规则:

1. **benchmark 是 GATE 不是 fitness** —— 变体必须"任务分提升 **且** 系统 bench 不回退",缺一即拒。
2. **永不直提,产物进评审闸** —— 复用现有 `skill_review_gate`(C10 默认开),进化产物走 `self_improvement_proposer` 的 PENDING 人审面。
3. **只归档不删除** —— 可回滚是底线。
4. **遥测不写进用户 authored 内容** —— 对齐 Hermes 侧车的理由(技能会被分享/发布)。本项目走 manifest.json,不污染 SKILL.md。
5. **尺寸预算 + 长度惩罚** —— 防止进化漂移向冗长。
6. **留出集 + 固定种子** —— 防过拟合,且可复现。
7. **全量 pytest 作硬闸** —— 产物必须不破坏现有测试基线。
8. **自我改进绝不阻塞用户回合** —— 若 Wave 1 runner 接入在线路径,必须异步且可取消(为 Wave 6 后台 fork 预留)。

---

## 6. 优先级与理由

| 顺序 | Wave | 优先级 | 理由 |
|---|---|---|---|
| 1 | Wave 1 评测标尺 | P0 | 价值最高、风险最低:判分与变异是全链地基,其余都是在它之上加约束 |
| 2 | Wave 2 约束闸 | P0 | 没有约束闸的进化是危险的;但必须先有 Wave 1 的产出才能闸 |
| 3 | Wave 3 生命周期 | P1 | 纯函数、零 LLM、独立于前两波,**可并行** |
| 4 | Wave 4 挖掘 | P1 | 解冷启动,依赖 Wave 1 评测集结构稳定 |
| 5 | Wave 5 巩固 | P2 | 收益递减,且 Hermes 自己都默认关 |

**建议起点**:**Wave 1 + Wave 3 并行开工**(Wave 3 完全独立、纯确定性、零风险)。

Wave 1 的核心断言是 **"过拟合变体被留出集拒绝"**——这条测试先红后绿,即证明闭环真的在度量而非自欺,与项目 `rsi/eval_harness.py` 已确立的"行为安全地板"哲学一脉相承。

---

## 7. 遗留与不做清单

**不做**:

- DSPy / MIPROv2 / Darwinian Evolver 三个外部引擎(用 `llm_router` 自研反射变异替代)
- Hermes 的 SKILL.md frontmatter 遥测(Nurova manifest 侧车更优)
- curator LLM 巩固默认启用(Hermes 自己默认关)
- 在线热插拔进化产物(只对新会话生效)

**待拍板**:

- Wave 4 的源 A(`agent_run_store`)挖掘是否需要跨 agent 隔离(参考 `neurova-memory-agent-wide-isolation` 口径)
- Wave 5 是否随前三波一并立项

---

## 附录 A:Hermes 源码锚点索引

| 机制 | 文件 |
|---|---|
| 进化配置/仓库发现 | `hermes-evo/evolution/core/config.py` |
| 适应度/LLM-judge | `hermes-evo/evolution/core/fitness.py` |
| 约束闸 | `hermes-evo/evolution/core/constraints.py` |
| 评测集生成 | `hermes-evo/evolution/core/dataset_builder.py` |
| 外部历史导入 + 密钥清洗 | `hermes-evo/evolution/core/external_importers.py` |
| 技能包为 DSPy module | `hermes-evo/evolution/skills/skill_module.py` |
| 优化主循环 | `hermes-evo/evolution/skills/evolve_skill.py` |
| 完整规划(五 Phase/闸设计) | `hermes-evo/PLAN.md` |
| 回合后台复查 | `hermes-agent/agent/background_review.py` |
| 技能库园丁(两段式) | `hermes-agent/agent/curator.py` |
| 技能遥测/来源 | `hermes-agent/tools/skill_usage.py` |
| 学习图 | `hermes-agent/agent/learning_graph.py` |
| `/learn` 硬规则 | `hermes-agent/agent/learn_prompt.py` |

## 附录 B:Neurova 接入点索引

| 接入点 | 文件 | 行 |
|---|---|---|
| 判分(待升级) | `neurova/skills/prompt_optimizer.py` | `PromptEvalSet.score_prompt` 60-95 |
| 规则变体(待升级) | `neurova/skills/prompt_optimizer.py` | `generate_variants` 130-165 |
| 失败分析(保留) | `neurova/evolution/skill_improver.py` | `_analyze_failure_pattern` 260-295 |
| 字典建议(待升级) | `neurova/evolution/skill_improver.py` | `_suggest_fix` 299-310 |
| 评测地板(复用) | `neurova/evolution/rsi/eval_harness.py` | 全量 319 行 |
| 评审闸(复用) | `neurova/evolution/skill_review_gate.py` | 全量 32 行 |
| 技能遥测(待扩状态) | `neurova/skills/skill_service.py` | `record_skill_usage` 308-333 |
| 安全扫描(复用) | `neurova/skills/security_scanner.py` | 全量 908 行 |
| run 存储(挖掘源) | `neurova/core/agent_run_store.py` | 全量 |
| 部署控制器(复用) | `neurova/evolution/rsi/deployment_controller.py` | 全量 171 行 |

---

## 8. 实施与核验记录(2026-09-13 收口轮)

五 Wave 已全部实施并以红绿灯 TDD 验证。本节记录实施终态、核验中发现并修复的问题、以及 live-verify 证据。

### 8.1 实施终态

| Wave | 产物 | 测试 |
|---|---|---|
| 1 | `evolution/eval/`(config/fitness/dataset/mutator/runner/bench_gate/factory/miner/synthetic/service/constraints 共 11 模块)+ `prompt_optimizer` 双路径 + `skill_improver` 异步反射口 + pipeline 接线 | eval 101 测绿 |
| 2 | 约束五闸 + eval_harness 门(apply_fn 给牙齿)+ 装配工厂 | constraints 16 + factory/gate 8 测绿 |
| 3 | `skill_lifecycle.py` 状态机(含 `run_sweep_if_due` 间隔闸)+ `skill_service` 五个生命周期方法 | 12+15+6 测绿 |
| 4 | `miner.py`(密钥 15 组模式 + 两级筛选 + 会话真实源 `messages_from_sessions`) | 39 测绿 |
| 5 | `skill_consolidator.py`(纯计划产出,执行走审批面) | 9 测绿 |
| API | `text_evolution_api.py` 10 端点挂 `/api/v1/evolution`(读=登录/写=admin) | 15 测绿 |
| 前端 | `api/modules/text-evolution.ts` + `AgentSkillPage.vue`(状态徽标/钉住/进化/提案审批/设置弹窗)+ `skillEvo` 顶层两段 ×11 语言 | vitest 1408 全绿 + vue-tsc 零错误 + i18n 三守卫 35 测绿 |

### 8.2 核验轮发现并修复的问题

1. **生产级预存断点(路由)**:`/agent/{agent_id}/skills` 与 `/agent/{agent_id}/pending-skills` 被装饰器堆叠到同一函数,真正的 `get_agent_skills`(SkillService 列表)**从未注册**——前端技能页在闸关时恒空。修复:装饰器分离;live 证据 = 该端点现返回 default agent 磁盘真实 24 个技能。
2. **猜测 API 落空**:`constraints` 的 embedding 入口按想象写成 `neurova.embedding.embedding_service`,真名 `get_embedding_engine`(且只在已初始化时消费,不触发启动加载,对齐 09-09 启动性能决策);`miner` 首版依赖不存在的 `agent_runs.list_finished`,改接 `session_repository.get_history` 真实会话层。
3. **中文分词粒度**:Jaccard 回退把中文整段成单 token(改写/漂移算不出差异),改 jieba 词切分(项目已依赖)+ 字符二元组回退。
4. **设置路径 import 时冻结**:测试/多进程隔离互踩,改动态解析。
5. **契约错位**:context_template 进化误用 SKILL.md 的 frontmatter 结构闸 → 引入 `artifact_type="template"`;`get_skill_info` 投影漏 `usage`(UI 状态经此读不到)→ 补;首见无 usage 技能永久停在 seeded 不锚时钟 → 补 `seed_skill_usage`(Hermes seed_record_if_missing 同语义:锚 now、延迟一轮)。
6. **i18n 纪律**:三级键 `skill.evolution.*` 违反项目两级规则(section.key)→ 重构为顶层 `skillEvo` 段;动态模板键 `skill.evolution.reject.${reason}` 不被键引用守卫接受 → 改静态映射函数。
7. **测试基建**:`get_skill_improver` 单例跨测试污染(fixture setup 先 reset);类方法 monkeypatch 须补 `self`;pipeline 既有测试的 mock 按异步新契约升级 AsyncMock。

### 8.3 live-verify(18/18)

进程内真实 `create_app()` + 真实路由栈 + 真实磁盘(不触发 lifespan,避免渠道建连挂起):openapi 含 9 条 `/v1/evolution` 路径;设置读写 round-trip 持久化;技能列表返回真实 24 项且带 usage;生命周期汇总 active=24;提案空态;evolve 校验 404;服务层全链(假 LLM)holdout 0.2→0.9 → 产出 pending 提案 → 批准 → **磁盘实测 version 1.0.1 + context_template 更新**;proposals.json 与 runs/ 审计真实落盘;40 天无活动技能归档 + 状态可回转(归档=可恢复,永不删除)。

### 8.4 预存问题登记(非本次引入)

- `test_github_push_skill`(2 例):并行线程未提交新测试,参数契约错位,HEAD 上因缺未跟踪的 `neurova.web_reach.credentials` 连导入都不过;
- ~~`test_improvement_items_g2g3` B3~~:核验期间并行线程已自行修复;
- 前端 `npm run lint` 环境缺 eslint 二进制(仓库既有状况);
- vitest 偶发 1 抖动(复跑 1408/1408,与本次改动无关)。

### 8.5 默认态与开关

`NEUROVA_TEXT_EVOLUTION` 未设且 `config/evolution_settings.json` 缺省 → 文本进化**关闭**(默认态零行为变化);生命周期扫描**默认开**(纯确定性、零 LLM、首见只 seed)。开发可用 env 显式覆盖(env 赢过设置文件)。

### 8.6 第二轮核验(数据流断点专项)

换视角复审,专攻"声明的数据流是否真的在流":

1. **judge→mutator 反馈断链(真断点,已修)**:`runner._collect_failures` 把 `JudgeFailure.feedback` 硬编码为空串——judge 的文字反馈(反射式变异的核心输入,GEPA 的"理解为何失败")从未流进变异器,反射退化为盲改。修复:`_score_example` 透传 `(composite, output, feedback)`,新增回归测试 `test_judge_feedback_flows_into_mutator` 锁死该数据流。
2. **`optimize_prompt` 判据缝隙(已修)**:评测集含 rubric 用例时仍走同步子串打分(rubric 用例被诚实记 0),优化将在错误标尺上选"最优" → 含 rubric 时改走 `score_prompt_async(judge=...)`,`optimize_prompt` 增加 `judge` 注入参。
3. **前端 iterations 空值(已修)**:`a-input-number` 清空后为 null → 后端 `ge=1` 校验 422;钳制 `|| 5`。
4. **组件契约核对(通过,无需改)**:GlassButton 支持 `ghost/secondary/primary/danger` 四 variant;`_step_rsi_iteration` 经 `_safe_step` 注册(维护块随其执行);`AgentSkillPage` 路由已注册;`test_runner_holdout` 的死代码 `_ScriptedJudge` 清除。

第二轮回归:后端 evolution 116(eval)+ 782(总)+ skills 728;前端 vue-tsc 零错、i18n+api 234 测、全量 vitest exit 0。


