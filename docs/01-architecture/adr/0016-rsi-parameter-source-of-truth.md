# ADR 0016: RSI 可优化参数的事实源

- **Status**: Accepted
- **Date**: 2026-09-19
- **Decision Maker**: RSI 进化闭环修复（工单 002）
- 相关：ADR 0011（SkillRegistry 单一实现）、工单 017（镜像表删除）、工单 018（替身系统假接线）

## Context

RSI 棘轮要调整 11 个"可优化参数"（`rsi/integration_manager.py:31-51`）。同一个参数名在项目里
存在**四处**独立定义，任何一处漂移都会静默改变进化行为：

| 角色 | 位置 | 语义 |
|---|---|---|
| 参数清单 | `rsi/integration_manager.py:31-51` | RSI 能碰哪些参数 |
| 优化目标 | `rsi/system_performance.py:17` `SYSTEM_SETPOINTS` | 棘轮往哪儿收 |
| 硬边界 | `rsi/integration_manager.py` `PARAMETER_BOUNDS` | 允许漂到哪 |
| 装配起点 | 真实子系统签名默认 / `AgentConfig` 显式传入 | 进程启动时实际是多少 |

审计（2026-09-19）另有**第五处**：`agent_core.py:381-392` 的 `_NullSystem` 类属性镜像表。
它不是"零消费方的死表"——`agent_core.py:1537-1540` 在真实闭环系统缺席时用
`_NullSystem()` **顶替该系统的位**，于是 `get_optimizable_parameters()` 的
`getattr(system, name, None)` 读到的就是这张镜像表。实测后果见 Consequences。

六个参数的四处现值（"-" 表示该处未定义）：

| 参数 | setpoint | 真实消费方默认 | `_NullSystem` 镜像 | AgentConfig |
|---|---|---|---|---|
| sleep.base_decay_rate | 0.1 | 0.1（`memory_layer/sleep.py:144`） | 0.1 | - |
| sleep.similarity_threshold | **0.7** | **0.7**（`sleep.py:142`） | **0.8** | - |
| emotion.emotional_protection_threshold | 0.5 | 0.5（`modules/emotion_module.py:102`） | 0.5 | - |
| emotion.emotional_protection_factor | **0.3** | **0.3**（`emotion_module.py:103`）；旁路 TemperatureEngine 签名 0.6（`temperature.py:110`） | **1.0** | - |
| experience.crystallize_min_observations | 3 | 3（`experience_feedback.py`，实测） | 3 | - |
| experience.crystallize_min_success_rate | **0.6** | **0.6**（实测） | **0.7** | - |
| experience.pattern_min_support | 2 | 2（实测） | 2 | - |
| tool_memory.success_bonus | 0.1 | 0.1（`closed_loop.py:64`、`tool_memory_integration.py:52`） | 0.1 | 0.1 |
| tool_memory.failure_penalty | **0.05** | **0.05**（`closed_loop.py:65`、`:53`） | **0.1** | 0.1 |
| tool_memory.decay_rate | **0.01** | **0.01**（`closed_loop.py:66`、`:54`） | **0.05** | 0.05 |
| tool_memory.muscle_memory_threshold | 0.8 | 0.8（`tool_memory_integration.py:56` 签名） | 0.85 | **0.85**（`agent_core.py:234`，经 `:609` 实传） |

## Decision

**四类角色各自唯一，且"起点 ≠ 目标"是设计意图而非缺陷。**

1. **参数清单** 是唯一的准入面。清单内每个参数**必须**同时登记 `SYSTEM_SETPOINTS`
   与 `PARAMETER_BOUNDS`；漏一项即 CI 红（守卫见 References）。
   理由：漏 setpoint → `_generate_candidates_for_param` 的 `get_setpoint()` 返回 None → 该参数
   永不产生候选（`orchestrator.py:447-449`），表现为"该优化的参数永远不被优化"的静默死参数；
   漏 BOUND → 落 `_PARAM_BOUND_DEFAULT=(0.0,100.0)`，对置信度/比率类参数等于不夹紧。
2. **优化目标 = `SYSTEM_SETPOINTS`**，其值一律对齐**真实消费方的设计默认**。
   上表六处冲突里，`_NullSystem` 镜像表是**唯一**站在对侧的值 → 判镜像表为错，
   真实消费方与 setpoint 均保留现值，镜像表由工单 017 删除。
3. **装配起点 = 真实子系统签名默认**；`AgentConfig` 只在其文档串声明的字段上覆盖起点。
4. **`emotion.emotional_protection_*` 的唯一事实源是 `EmotionModule`**：
   `attach_temperature_engine`（`emotion_module.py:110-115`）在挂桥时把引擎值**覆写**为
   EmotionModule 的值，此后 setter 持续转发（`:122-135`）。
   故 `TemperatureEngine` 签名默认 `0.6`（`temperature.py:110`）在 Agent 路径上从不生效，
   是**被遮蔽的影子默认**；仅在未挂桥路径（voice bridge、独立构造）下泄漏为实际值。
   判：EmotionModule 0.3 为准，影子默认登记为待收口项。
5. **`tool_memory.muscle_memory_threshold` 的分歧予以保留**（起点 0.85 / 目标 0.8），
   它是上表里唯一"起点有意偏离目标"的参数 —— 见 Consequences 的梯度账。

### 逐参数结论

11 个参数全部**不改生产默认值**。六处冲突的处置：
`similarity_threshold`、`emotional_protection_factor`、`crystallize_min_success_rate`、
`failure_penalty`、`decay_rate` → 错在镜像表，删表即可归一（工单 017）；
`muscle_memory_threshold` → 无冲突，起点与目标本应两值。
另在本单补齐 `PARAMETER_BOUNDS` 缺失的 5 项
（`experience.pattern_min_support` + `tool_memory` 四参），并把
`emotion.emotional_protection_threshold` 从 `(0.0,100.0)` 收到 `(0.0,1.0)` ——
它此前登记了，但登记值与兜底逐位相等，等于没登记（守卫 `test_bounds_are_tighter_than_the_default_fallback` 抓到）。

## 不采纳的替代方案

- **让 `SYSTEM_SETPOINTS` 抄 AgentConfig 现值**：会把 5 个已与真实消费方一致的 setpoint 拽偏，
  且 RSI 从此对这些参数零梯度（起点即目标 → `abs(delta)<1e-9` → `orchestrator.py:458` 返回空候选），
  等于用"消除冲突"的名义关掉进化能力。
- **让 `AgentConfig`/子系统默认全部等于 setpoint**：混淆"起点"与"目标"两类语义，
  结果是 RSI 永远无事可做；且 `muscle_memory_threshold` 的 0.85 是**有意**的历史取值，
  无证据支持改动它。
- **把镜像表改成与 setpoint 一致的数值（而不是删表）**：数值对上只治了五个冲突值，
  治不了"RSI 在替身对象上做参数寻优并回执成功"这个更重的病。见 Consequences。
- **不引入第五个配置文件作为"参数真值源"**：多一处定义正是本 ADR 要消除的病因。

## Consequences

**正向**
- 新增参数漏登记时 CI 即红，而不是运行时静默不进化。
- `PARAMETER_BOUNDS` 覆盖全部 11 参，比率/置信度参数不再可能被复利调整漂出语义域。
- 镜像表与影子默认的缺口成为显式待办（017/018），不再是隐式行为。

**必须承认的代价 —— 梯度账**
本 ADR 判定"不改任何默认值"之后，`get_optimizable_parameters()` 读到的 11 个参数里
**只有 `tool_memory.muscle_memory_threshold` 一个偏离其 setpoint**（0.85 vs 0.8）。
其余 10 个起点即目标，`_generate_candidates_for_param` 对它们恒返回空候选。
即：**当前 RSI 参数寻优臂的真实作用面只有一个参数**。
这不是本 ADR 造成的，而是本 ADR 把它从"三处值互相矛盾所以看起来有活干"
变成"值一致所以看清了只剩一个梯度"。
由此推论：`docs/specs/.../tickets/007` 的 measurement_blind 与
`008` 的零证据不得判收敛，是这条账能被诚实呈现的前提 ——
否则 RSI 会以"唯一参数已到位"的名义宣称全局收敛。

**梯度账重验（2026-09-22，工具环路修复批 008）**

008 换了肌肉记忆的指纹口径（`\w\s` 分词 → 字符 n-gram）并让写侧存规范参数形状，
"`muscle_memory_threshold` 是唯一还有梯度的旋钮"这条结论**不得默认仍成立**，故重算：

- 重算入口：`scripts/diagnostics/muscle_memory_threshold_attainability.py`
  （真写读路径 + 真实形态的近似问法配对，分母 = 配对总数）。
- 实测：起点 `0.85` 与 setpoint `0.8` 在 8 条相关配对上的裁定**完全相同**
  （5 触发 / 8 相关），落在开区间 `(0.8, 0.85)` 的真输入为 **0 条**，无关对照零误报。
  ⇒ 该旋钮的**梯度带当前为空**：阈值能从 0.85 调到 0.8，但沿线没有真输入改变裁定。
  即"唯一有梯度的参数"这一表述需限定为"**参数面上有位移**，**行为面上暂无差异**"——
  两者不是一回事，原先的账把它们混成了一个结论。
- 因此 RSI 参数寻优臂在本批之后**实际空转**：位移可产生（`abs(delta) >= 1e-9` 即出候选），
  但据以采纳的增益读数为零。这不改变"要不要保留这颗旋钮"的判定（它是 D4 终态的一部分），
  只是把"还剩一颗有梯度的参数"改记为"剩一颗可动参数、梯度带为空"。

**负向 / 遗留**
- 未消除 `_NullSystem` 携带参数面的问题（→ 工单 018）。在其落地前，
  缺席系统仍会被"优化"：实测四系统全为替身时 `run_iteration()` 报
  `applied_count=6`、每条 `applied=True`、`gain=+0.111`，而背后无任何真实子系统。
  增益之所以为正，是 `eval_harness._param():32-39` 回读 `get_optimizable_parameters()`，
  读到的正是刚写进替身的那个值 —— 棘轮在奖励自己编辑空对象。
- `TemperatureEngine` 签名默认 `0.6` 与 `EmotionModule` 的 `0.3` 并存（未挂桥路径会泄漏），
  本 ADR 只判定谁为准，未在本单改签名默认（改动会波及记忆衰减行为，需独立验证）。
- 治理设置里的 `rsi_phase` 是**进程级单文件、多 agent 共享**，与本 ADR 的参数事实源无关，
  但同属"一处定义多处读取"家族，登记备查。

## References

- 守卫测试：`tests/unit/evolution/rsi/test_parameter_source_of_truth.py`
  （四条一致性用例 + 一条 `_NullSystem` 假接线红灯，后者由工单 018 转绿）
- 边界补齐：`neurova/evolution/rsi/integration_manager.py` `PARAMETER_BOUNDS`
- 参数清单：`neurova/evolution/rsi/integration_manager.py:31-51`
- 目标表：`neurova/evolution/rsi/system_performance.py:17-37`
- 镜像表：`neurova/agent_core.py:381-392`（工单 017 删除）
- 情感桥：`neurova/cognitive_layers/memory_layer/modules/emotion_module.py:110-135`
- 行为判据同源：`neurova/evolution/rsi/eval_harness.py`（`em_threshold_band`、
  `tm_threshold_band`、`tm_decay_forgetting_band`）
- 前序 ADR：0011（统一 SkillRegistry）
