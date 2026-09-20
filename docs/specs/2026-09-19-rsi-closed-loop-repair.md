# RSI 进化闭环修复规格

- 日期：2026-09-19
- 来源：RSI 进化流程闭环审计（本文件所有行号均为审计期实测定位）
- 影响范围：`neurova/evolution/rsi/`、`neurova/evolution/`、`neurova/agent_core.py`、`neurova/api/endpoints/governance.py`、`NeurUI/src/`
- 前置决策：ADR 0016（参数事实源逐参数钉死）、ADR 0011（SkillRegistry 单一实现的后续身份键收口）
- 工单拆分：[`2026-09-19-rsi-closed-loop/tickets/`](./2026-09-19-rsi-closed-loop/tickets/000-索引.md)（17 张，依赖图见索引）

---

## 1. 问题陈述

RSI（递归自我进化）号称"每轮对话后自我改进"，审计结论是**三条臂全部不闭环，且断裂点互相咬合成自锁**。用一句可复现的话概括：

> 在生产默认配置（治理设置 `rsi_phase=0`）下连跑 60 轮迭代，部署阶段停在 1、累计 `applied_count=0`；
> 把 `rsi_phase` 手调为 4 后能应用参数，但第 20 轮 `should_continue()` 翻 False，本进程内 RSI 永久自停。

三臂的具体病理：

**臂一 · 参数寻优（棘轮本体）** —— 自动执行通道被自己的晋升判据锁死。
`can_auto_execute("low")` 要求 phase≥2（`rsi/deployment_controller.py:47`），而 1→2 要求"7 天无回滚"（`:111`）；
`_compute_days_without_rollback()` 在无回滚记录时返回 **0.0**（`rsi/orchestrator.py:176-184`）。
要记录回滚必须先应用参数，要应用参数必须先晋升，要晋升必须先有回滚记录 —— **三角死锁**。
雪上加霜：`run_iteration` 的 gain<0 分支走 `_restore_optimizable()`（`:228`）直接改内存，
**从不经过 `rollback_manager`**；且 `SelfImprovementProposer()` 构造时未传 manager（`:97`），
proposer 自建实例（`self_improvement_proposer.py:373`），实测 `orchestrator.rollback_manager is proposer.rollback_manager == False`。
于是"即使真发生了回滚，判据也永远看不见"。

**臂二 · 人工审批通道** —— 批准不产生运行时效应，且无人能看见。
`approve_and_apply` 把提案内容写进 `.agents/skills/<id>/manifest.yaml`（`self_improvement_proposer.py:875-887`），
而技能真实加载侧读的是 `data/agents/{id}/skills/` + `manifest.json`（`skills/skill_service.py:119/129/148`）；
`.agents` 后端**零读取方**。实测 `.agents/proposals` 积压 90 个 JSON 全为 pending。
proposer 又自建一个 phase=0 的 deployment_controller（`:372`），与 orchestrator 按治理设置建的那个不是同一对象
（`orchestrator.py:71-77`）→ 管理员在前端调 `rsi_phase` 对 medium/high 提案无效。
观测面同样为零：`RSIDashboard` 唯一调用方是测试，其 `get_rollback_history()` 硬编码 `return []`（`rsi/dashboard.py:136-138`）；
`metrics.py:39-45` 声明的 7 个规范指标生产从不写入 → `check_alerts()` 恒空。

**臂三 · 技能进化** —— 采集端被一颗 AND 门整链静默关停。
`agent_core.py:1582` 的注册门是 `if self.tool_memory and self._skill_registry:`，
而 `a.tool_memory` 在 `:590` 先置 None、仅 `ToolMemoryIntegration` 构造成功（`:600`）才赋值。
tool_memory 一旦初始化失败，POST_EXECUTE 回调整体不注册，
`_on_skill_post_execute`（`:1624`）里四条互不依赖的记账全灭：
`skill_improver.record_usage`、`SkillService.record_skill_usage`、`skill_experience.record_usage`、`genetic_engine.record_reuse`。
后果：`AutoSkillImprover._usage_records` 恒空 → `propose_pending_improvements` 每轮 0 提案 →
`run_skill_evolution_pass`（`post_chat_pipeline.py:145`）空转。实测 `data/evolution/skill_experiences.json` 的 `usage` 为 `{}`。
注意：`SkillRegistry._emit_event` **本身是有调用点的**（`skill_system.py:637/643/648`，经 `execute_skill`），
生产执行路径也确实走 `execute_skill`（`tool_executor.py:966`、`router.py:268`、`agent/loops/base.py:253`）；
断的是注册，不是发射。

叠加的第二根因是**身份键两套**：注册表建键与查键都用 `skill.name`（`skill_system.py:505`，查键 `:595/:610/:632/:778`），
而进化侧身份是 `resolve_skill_identity` 的 skill_id→id→name 序（`skills/skill_contract.py:88-92`），
注册边界写入的恰是 `skill_id`（`skill_contract.py:108`）。
`apply_improvement`、`_apply_to_skill`、`rebuild_skill`、`set_skill_enabled` 共 8 处按 identity 取技能
（`agent_core.py:1370`、`skill_experience.py:195/280/358`、`skill_improver.py:523/664`、`post_chat_pipeline.py:2513`、`collaborate/workflow/scheduler.py:396`）
在 id≠name 时恒取不到 → 改进回写恒 False。现有测试用 id==name 的假注册表把这条掩盖成绿色。

### 加重项：RSI 可以对一个不存在的系统宣布进化成功

原审计把 `agent_core.py:381-392` 的 `_NullSystem` 参数表判为"零消费方的死镜像"，
工单 002 写一致性守卫时证伪了这个判断 ——
`agent_core.py:1537-1540` 在真实闭环系统缺席时直接拿 `_NullSystem()` **顶替系统位**：

```python
self.rsi_orchestrator = RSIOrchestrator(
    sleep_system=sleep_system or _NullSystem(),
    ...
)
```

于是那张镜像表成了 RSI 眼中的"真实参数面"。实测（四系统全为替身、phase=2、单轮）：

```
applied_count = 6 | gain = +0.11111099999999996
applied_results = sleep.similarity_threshold 0.8→0.78 applied=True
                  emotion.emotional_protection_factor      applied=True
                  experience.crystallize_min_success_rate  applied=True
                  tool_memory.failure_penalty/decay_rate/muscle_memory_threshold  applied=True
```

没有任何真实子系统被改动。增益之所以为正：`_measure_performance`（`orchestrator.py:118-127`）
经 `get_optimizable_parameters()` 回读参数，读到的恰是刚写进替身对象的值
→ `eval_harness._param():32-39` 判"更接近 setpoint" → 分数上升 → `gain>0` → **永不回滚**。
`_NullSystem.get_feedback()` 恒返回 `performance_score=0.5`，故该假链路可长期自持；
`NEUROVA_RSI_RECEIPTS` 开启时还会把虚构的 old/new 落成审计回执。
→ 修法与验收见 **工单 018**（其红灯守卫已在
`tests/unit/evolution/rsi/test_parameter_source_of_truth.py` 就位）。

---

## 2. 方案概述

不新增平行体系，把已有的三套组件接成一条真链路。按"证据先于能力"的顺序分五个 PR：

```
PR-1  事实源与判据台账（ADR 0016 + 审计证据入库）      —— 零生产代码改动
PR-2  棘轮可证伪化（臂一核心：回滚留痕 + 度量功效 + 三态判据）—— 解锁自动通道
PR-3  人工通道与观测面（臂二：批准即生效 + 单一控制器 + 审批 UI）
PR-4  技能采集与身份契约（臂三：解耦注册门 + 统一 identity 键）
PR-5  净删除（镜像表 / 死方法 / 陈旧诊断脚本）           —— 兑现"净 LOC ≤ 0"
```

PR-2 是其余的承重墙：晋升判据不真，臂二臂三都只是在给一条不通的链路加界面。

**"可证伪判据"是本方案的核心设计约束**，定义为三态而非二态：

> 每一条晋升/停止判据必须能区分 `passed` / `failed` / **`unevidenced`（证据缺失）**。
> `unevidenced` 一律不得按 `passed` 处理，且必须在观测面显式可见。
> 任何"取不到数据就用默认值继续算"的写法（`_param` 的 setpoint 回退、`metrics.get("roi", 0.0)`、
> `days_without_rollback` 的空历史返回 0）都视为判据失真，按缺陷处理。

---

## 3. 用户故事（每条可独立验证）

### PR-2 · 棘轮可证伪化

1. 作为运维者，当一轮迭代实测增益为负、参数被回滚时，我希望**这条回滚被记入回滚历史**，以便阶段晋升用的是真证据。
   验收：`run_iteration` 的 gain<0 分支调用 `rollback_manager.create_snapshot()` + `execute_rollback()`；
   连续 3 轮有害调整后 `len(orchestrator.rollback_manager.get_rollback_history()) == 3`。
2. 作为运维者，当 RSI 从未发生过回滚时，我希望"无回滚天数"从**RSI 装配时刻**起算而不是恒 0，以便 7 天判据可被真实满足。
   验收：空历史时 `_compute_days_without_rollback()` 返回 `(now - _started_at)` 的天数；
   `_started_at` 从死字段变为唯一消费方，并在跨重启后取自持久化的 `rsi_installed_at`。
3. 作为运维者，我希望 orchestrator 与 proposer 共用**同一个** deployment_controller 与 rollback_manager，
   以便前端改 `rsi_phase` 对所有通道一致生效。
   验收：`orchestrator.deployment_controller is orchestrator.self_improvement_proposer.deployment_controller`，
   rollback_manager 同理。
4. 作为审计者，我希望阶段晋升判据里的 ROI 是**真值**，以便 `roi<0` 守卫不是幻影。
   验收：`analyze_convergence()` 的 `metrics` 含 `roi` 键（由 `convergence_analyzer.compute_roi()`:138 供值）；
   或在 PR-5 删除该守卫并写明理由 —— 二者择一，不允许维持现状。
5. 作为审计者，我希望评测集在参数取不到时**不把该用例计入分母**，以便 gain=0 只在"真的无差异"时出现。
   验收：`eval_harness._param()` 的 setpoint 回退标志上抛到用例层，回退用例从 `overall` 分母中剔除
   （`eval_harness.py:32-39`、`:318`）；全族回退时 `run()` 显式返回"度量失明"信号而非 `score=1.0`。
6. 作为使用者，我希望 RSI 在证据不足时报告"无法判定"，而不是宣告"已收敛"并永久自停。
   验收：`convergence` 状态集扩为 `{converged, diverging, oscillating, insufficient_data, measurement_blind}`；
   `should_continue()` 仅在 `converged`（且度量有效）时为 False；
   gain 恒 0 且 applied_count>0 的序列判为 `measurement_blind`，**不再**喂 0 进 `record_iteration`（`orchestrator.py:237-239`）。
7. 作为使用者，我希望即使 RSI 判定收敛，它仍以退避频率巡检，以便参数漂移能被再次捕获。
   验收：`should_continue()==False` 后 post_chat 转入降频（如 1/20 轮）而非永久 SKIPPED
   （`post_chat_pipeline.py:2729`）。
8. 作为审计者，我希望"自动晋升"与"人工设置阶段"两条写入路径**不互相覆盖**。
   验收：`advance_phase()` 成功后回写 `save_governance_settings({"rsi_phase": n})`
   （`security/governance_settings.py:52`）；重启后阶段不回零。
9. 作为审计者，我希望升级通道（发散→人工提案）在真实运行中可达。
   验收：构造一个持续有害的参数序列，实测 `status` 出现 `diverging` 且 `_escalate_to_proposer_if_needed` 返回非空
   （现状 80 轮实测集合只有 `{insufficient_data, converged}`）。

### PR-3 · 人工通道与观测面

10. 作为管理员，我希望批准一个 skill_manifest 提案后，**技能真的进注册表、下一轮对话真的能用**。
    验收：`approve_and_apply` 改为经 `skills/market_registry.py:127 persist_synthesized_skill(...)` 落 SkillService
    并回灌 registry；批准 → 下一次 `chat` 的可用技能列表含该技能（live 验证）。
11. 作为管理员，我希望 `.agents` 这条死目录不再作为生效路径存在。
    验收：删除 `self_improvement_proposer.py:355/362-364/866-899` 的 `.agents` 写/删分支，
    改为 `data/agents/{agent_id}/` 单一真源；历史 `.agents/proposals` 提供一次性迁移或明确作废说明。
12. 作为管理员，我希望提案状态（PENDING/APPLIED/REJECTED/ROLLED_BACK）在界面上可查、可追溯。
    验收：`governance.py` 新增列表端点返回全部状态（现 `list_pending_proposals`:596-605 只出 PENDING）；
    前端新增审批页并在 `NeurUI/src/router/index.ts` 注册路由（现状 NeurUI 除 `rsi_phase` 外零 `rsi` 命中）。
13. 作为运维者，我希望 governance 端点读到的是**发起本轮对话的那个 agent** 的 RSI 实例。
    验收：端点按 agent_id 定位实例，不再依赖"最后构造者覆盖单例"的副作用
    （现状 `agent_core.py:854-855` 写全局单例、`governance.py:245` 只读单例）。
14. 作为运维者，我希望 dashboard 的 `get_rollback_history()` 不再硬编码空列表。
    验收：转调 `rollback_manager`；`metrics.py:39-45` 的 7 个规范指标有真实写入方，或该组指标连定义一并删除。
15. 作为用户，我希望 RSI 结果要么真的推给负一屏，要么这条推送代码不存在。
    验收：`notifications/negative_screen.py:335 push_rsi_result` 接入 `manager.py:232` 的派发链，或删除该方法。

### PR-4 · 技能采集与身份契约

16. 作为进化系统，我希望技能使用记账**不依赖 tool_memory 是否可用**（tool_memory 只被最后一小段用）。
    验收：把四条记账从 `agent_core.py:1582` 的 AND 门中解耦，注册门只保留其真实前置条件；
    在 `a.tool_memory is None` 的注入式故障演练下，`skill_improver.record_usage` 仍被调用（实测当前为 0 次）。
17. 作为进化系统，我希望 `SkillRegistry` 的字典键域与 `resolve_skill_identity` 的身份域**是同一个**。
    验收：注册与查询统一按 ADR 0016 选定的单一键（含向后兼容的别名索引）；
    新增回归测试用 `id != name` 的真实 Skill 断言 `apply_improvement` 返回 True
    （现状该用例被 id==name 的假注册表掩盖）。
18. 作为进化系统，我希望封装模板的去重键能真的匹配，已批准的技能不会每轮重回待审。
    验收：`skill_encapsulation.py:339` 的 `skill_{pattern_id}`（64hex）与 `:360/:379` 的
    `skill_{fingerprint[:16]}` 收敛为同一构造；连续 2 轮 observe 同一模式，`is_active` 不被重置。
19. 作为进化系统，我希望改进的最后一米有消费方：`config["improvements"]` 要么被上下文组装读取，要么删除该写入。
    验收：grep 确认有生产读取方，或该键不再产生（不允许"写了没人读"的第三态）。
20. 作为运维者，我希望技能进化史跨重启保留。
    验收：`closed_loop.py:712 bootstrap_evolution_persistence` 挂载 improver 与 builder
    （现仅挂 5 件），重启后提案台账不归零。
21. 作为运维者，我希望归因台账按真实 agent_id 建。
    验收：`post_chat_pipeline.py:2578` 传入 agent_id（现落默认 `"default"`，与 `:2572-2574` 的 ledger 建键不一致）。

### PR-5 · 净删除

22. 作为维护者，我希望参数默认只有一处定义。
    验收：删除 `agent_core.py:381-392` 的 `_NullSystem` 镜像表（6 值与两侧均冲突且零消费方），
    `_NullSystem` 退化为纯中性信号桩。
23. 作为维护者，我希望零调用方的方法面被清除。
    验收：`create_variant`、`get_variant_comparison`、`revert_last_improvement`、`get_skill_stats`、
    `get_usage_history`、`get_improvement_history`、`rollback_skill`、`get_archives`、`is_retired`、
    `deactivate_template`、`get_pattern_statistics`、`get_skill_builder`、
    `convergence_analyzer.predict_convergence_point`:153、`is_worth_continuing`:191
    经 grep 复核后删除（保留项须在提交说明里写明消费方）。
24. 作为维护者，我希望陈旧诊断脚本不再误导。
    验收：删除 `tests/manual/diagnose_rsi.py`（引用不存在的 `orch._zero_gain_streak`，已跑不通），
    或由 PR-2 的新判据重写为可执行的闭环探针。

---

## 4. 已定决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 三臂全修，按 PR-1→5 分阶段落 | 三臂互为兜底：自动通道不开时人工通道必须可用，人工通道无人看时技能臂是唯一在跑的 |
| D2 | **保留**渐进晋升，但判据改为可证伪（三态） | 既不粉饰能力，也不因噎废食取消自升级 |
| D3 | 参数事实源先立 ADR 0016 逐参数钉死 —— **已落**（`docs/adr/0016-rsi-parameter-source-of-truth.md`） | 6 参数多源冲突，拍错方向代价高于多一轮论证 |
| D4 | 修根因，禁止 consumer-only guard | 项目修复教义第 1 条；PR-4 第 16 条即反例的正修（解耦门而非在下游补 None 检查） |
| D5 | gain<0 的回滚走 `rollback_manager`，不再自行改内存 | 单一事实源；判据数据与执行动作不得两分 |
| D6 | 提案生效走 `persist_synthesized_skill`，`.agents` 作废 | 该函数已贯通 SkillService 落盘 + registry 回灌，无需新通道 |
| D7 | 净 LOC ≤ 0 由 PR-5 集中兑现 | PR-2/3/4 必然为正，删除量在 PR-5 一次性结清并在提交说明列明去向 |

ADR 0016 判定过的 6 参数（定稿期实测五源，此处摘三类代表值）：

| 参数 | SYSTEM_SETPOINTS<br>(`rsi/system_performance.py:17`) | `_NullSystem` 镜像<br>(`agent_core.py:381-392`) | 真实消费方默认 |
|---|---|---|---|
| similarity_threshold | 0.7 | **0.8** ← 错侧 | `SleepConsolidation()` 签名 0.7（`sleep.py:142`） |
| emotional_protection_factor | 0.3 | **1.0** ← 错侧 | `EmotionModule` 0.3（`emotion_module.py:103`）；`TemperatureEngine` 0.6 为被 attach 覆写的影子默认 |
| crystallize_min_success_rate | 0.6 | **0.7** ← 错侧 | `ExperienceFeedback()` 实测 0.6 |
| failure_penalty | 0.05 | **0.1** ← 错侧 | `AdaptiveToolWeights()` 签名 0.05 |
| decay_rate | 0.01 | **0.05** ← 错侧 | `AdaptiveToolWeights()` 签名 0.01 |
| muscle_memory_threshold | 0.8 | 0.85 | `ToolMemoryIntegration` 签名 0.8，**AgentConfig 实传 0.85**（`agent_core.py:234→:609`） |

ADR 0016 的结论：前五行错侧全在 `_NullSystem` 镜像表 → 判镜像表作废（删除项在工单 017），
setpoint 与真实消费方本就一致，无需改值。
第六行是**唯一有意分歧**，判为"起点 ≠ 目标是设计意图"并保留 ——
代价写进 ADR 后果段：11 个可优化参数里**只有 `muscle_memory_threshold` 一个真实存在梯度**
（其余起点即目标，`abs(delta)<1e-9` 直接零候选，`orchestrator.py:458`），
即 RSI 参数寻优臂当前只管一个旋钮。这条账正是工单 007/008
"零证据不得判收敛"必须落地的理由：否则 RSI 会以"唯一参数已到位"的名义宣称全局收敛。

---

## 5. 测试决策

**主接缝（最高可用接缝）**：`RSIOrchestrator.run_iteration()` 的返回值 + `get_status()`。
PR-2 的判据类改动一律穿过这个接缝断言，不新增内部接缝。已验证的复现基线：

```python
# 现有 4 个 MockSystem 桩即可驱动；见 tests/unit/evolution/test_rsi_ratchet_effectiveness.py:27-53
orch = RSIOrchestrator(sleep, emotion, experience, tool_memory)
orch.deployment_controller._current_phase = 0
for _ in range(60): orch.run_iteration()
# 期望（修复后）：phase 可越过 1，或明确报告 unevidenced 而非静默停在 1
```

**禁止的测试写法**（正是它们把缺陷洗成绿色）：
- 直接赋 `_current_phase` 绕过判据（现 `test_rsi_ratchet_effectiveness.py:51` 即如此）——
  必须新增一组**不碰私有字段**、只经 `load_governance_settings` 与本故事第 8 条回写链驱动的阶段测试。
- 注册表桩令 `id == name`（`tests/unit/skills/test_improvement_persistence.py:47-52`）——
  故事 17 要求 `id != name` 的用例。

**分层**：
- 单元：`tests/unit/evolution/rsi/`（新增目录）—— 判据三态、回滚留痕、控制器单一性、eval 分母剔除。
- 集成：`tests/integration/evolution/` —— 60 轮无死锁、20 轮不自停、重启后 phase 不回零。
- 端到端：`tests/e2e/` —— 批准提案 → 下一轮对话技能可见（故事 10 的 live 判据）。
- 防回归守卫：`scripts/guard-llm-tracked.cjs` 同风格新增一条静态守卫，扫描
  "定义了 OPTIMIZABLE_PARAMETERS 但未登记 PARAMETER_BOUNDS / SYSTEM_SETPOINTS" 的参数，CI 阻断。

**"完成"的判据**：`pytest tests/unit/evolution/ tests/integration/evolution/ -v` 全绿，
且上面三条复现基线由红转绿；臂二臂三各自的 live 验证脚本输出贴入 PR 描述。

---

## 6. 明确不做

- 不新建进化引擎、不引入新的 phase 分级、不改四闭环系统的成员构成（sleep/emotion/experience/tool_memory 维持）。
- 不做多 agent 的 per-agent 进化状态隔离（仅修"读到错误实例"，隔离另立项目）。
- 不改 `RecursiveRatchetPruner` 的三级剪枝算法与候选步进比例（0.05/0.10/0.15/0.20）。
- 不动 `evolution/eval/`（A-B 库、遗传变异、fitness）——那是工具基因臂，与本次三臂无交叉。
- 不做 RSI 的 LLM 参与式提案（`SelfImprovementProposer` 仍只用模板，零 LLM 调用）。
- 不改 `.agents` 历史数据的向后兼容读取（直接作废 + 一次性迁移说明，不写兼容 shim）。
- 不在前端做趋势图/告警可视化，PR-3 只补"看得见 + 能审批"。

---

## 7. 补充说明

**执行期需自行复核的行号**：spec 定稿后又补做了逐行核实，下列已**由本人 Read/Grep 确认**：
`skill_system.py:505/637/643/648/778`、`agent_core.py:1582/1624-1700`、
`rsi/dashboard.py:136-138`、`rsi/metrics.py:39-45`、`negative_screen.py:335` 的调用方集合、
`orchestrator.get_status():735` 零生产调用方、旧棘轮四方法（`_generate_optimization_for_param` 等）零生产调用方。
仍**仅有子代理审计支撑、implement 前须复核**的行号：
`self_improvement_proposer.py:372/373/596-605/682/797/875-887`、`skill_review_gate.py:35`、
`skill_experience.py:121-136/195/280/358/506`、`skill_encapsulation.py:339/360/379`、
`skill_attribution.py:152`、`post_chat_pipeline.py:2578`、`governance.py:245/260/271/289`、
`market_registry.py:127`（此项由两次独立审计交叉一致，可信度较高）。
臂一全部行号与 PR-4 第 16/17 条已逐行核实。

**环境事实**：本机 `data/governance_settings.json` 当前为 `rsi_phase=4`，
这会掩盖死锁 —— 复现臂一问题须先临时置 0，或按故事 8 让判据自证。
治理设置是**进程级单文件**，多 agent 共享一个 phase，这也是 PR-6 之外要留意的既有约束。

**工单 005 落地后该约束多了第二个写入方**（2026-09-20 追记）：`rsi_phase` 原先只由管理端
`save_governance_settings` 写，现在 `RSIOrchestrator._persist_rsi_phase` 会在自动晋升后回写。
多 agent 场景下每个编排器各持一个部署控制器，**谁最后晋升谁的阶段留在盘上**（后写者胜）；
按 agent 隔离仍属 §6"明确不做"。当前阶段的唯一真相是这个 JSON 文件，不是任一进程里的内存值
—— 后者每次启动按文件重建。口径已就地写进 `neurova/security/governance_settings.py`
的模块文档串。同单复核结论：本节原先"须复核"的 `self_improvement_proposer.py:372/373`
已实测为真（`deployment_controller or RSIDeploymentController(initial_phase=0)` 与
`rollback_manager or RSIRollbackManager()` 两行），并随 005 删除。

**审计已排除的误判**（避免 implement 时又被提出）：
`get_evolution_orchestrator()` 默认不注入 rsi_orchestrator，
但生产在 `agent_core.py:854-855` 补了注入，因此"单例 rsi_orchestrator 恒 None"这条**不成立**。
同理 `SkillRegistry._emit_event` 并非零调用点（见 §1 臂三）。

**术语**：本方案中"可证伪（falsifiable）"专指 §2 定义的三态判据；
"度量失明（measurement_blind）"专指"评测用例因参数回退 setpoint 而失去区分力"这一状态，二者不可混用。
