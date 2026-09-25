# 反思反哺闭环审计与链B接线修复（2026-09-19）

## 范围

回答一个问题：反思产出的东西，是否真的改变下一轮行为。仓库里存在两条独立的反思链，
结论分别是"闭环成立"与"名义闭环、消费端三处断"。本文记录审计证据、本次修复，
以及刻意不在本次修的登记项。

## 链A｜对话级反思日志（growth_log）— 闭环成立，不改动

| 环 | 位置 |
|---|---|
| 生成 | `neurova/post_chat_pipeline.py:1335` Step 8.5，触发条件 `:1358`（困惑词／不确定词／每 10 轮） |
| 落库 | `neurova/cognitive_layers/meta_cognition_layer/growth_log.py:326 generate_log` |
| 召回 | `neurova/context/orchestrator.py:36 select_reflection_logs`（≤3 条，排除 rejected/archived） ← `:499` |
| 注入 | `neurova/context/orchestrator.py:570` `:851`；`:511 mark_injected_logs` pending→applied |
| 留痕 | `neurova/context/orchestrator.py:62` → `neurova/core/turn_context.py:40` → `neurova/post_chat_pipeline.py:905` |
| 回流 | 赞踩：`neurova/api/endpoints/console.py:1587` → `growth_log.py:447/:469`；自动：用户困惑即对本轮注入降权 `post_chat_pipeline.py:1398` |
| 治理 | `growth_log.py:489 maintain_lifecycle`（重复 pending 合并 + 30 天归档），睡眠回调驱动 |

置信度变更在下一轮 `select_reflection_logs` 生效，构成可证伪闭环。

## 链B｜V3 自模型教训（SelfModelEngine → meta_records kind=lesson）

写入端一直是活的：`post_chat_pipeline.py:2701` 每 10 轮 + `should_reflect()` 门控自动
`reflect(trigger="periodic_turn")`。断的是三条出口：

1. **教训注入生产不可达**（已修）：注入器的教训分支要求 `_metacog_agent_id` 非空，
   而该值的唯一生产来源 `context/orchestrator.py:385` 构造点从未传参。
2. **调控门只读裸 env**（已修）：`tool_executor.py:413` 要求 `NEUROVA_METACOG_GATE=="1"`，
   全仓唯一设值处在测试里 → 硬拦截臂在真实部署恒关。
3. **归因臂卡在人工审批**（不修，设计如此）：`skill_experience.py:121` 评审闸默认开，
   归因记录入 `_pending_records` 等待 `skill_pool_api` 审批。该队列有界 50
   （`del self._pending_records[:-50]`），无人审批即静默丢弃——见登记项 R2。

## 本次修复

- 修复 1：`context/orchestrator.py` 生产构造点传 `metacog_agent_id`；身份取不到真串时
  维持不注入（测试替身不得被当成真实 agent_id 去建台账连接）。教训块经
  `context/envelope.py:31` 的 `lessons` 段进入末条 user 消息信封。
- 修复 2：`security/governance_settings.py` 新增 `metacog_gate_enabled`（默认 False），
  `tool_executor._metacog_gate_check` 改为与 Step9.96 成本门控同口径：
  env 显式设 0 强制关 > env 显式设 1 > 治理设置值 > 内置默认关；
  `api/endpoints/governance.py` 的 `GovernanceSettingsUpdate` 同步暴露该字段，
  否则管理面 PUT 会以"无有效更新字段"拒掉它。
- 软通道（教训进信封）不设开关，接线即生效；硬拦截（教训阻断工具）默认关。
  这条取舍是本次审计的显式决定：闭环由软通道保证，硬拦截作为管理员可选项。

## 防回归测试的位置判断

链B 原有测试全绿却漏掉断点，原因是它们在测试内手工补齐了生产缺失的接线
（`tests/unit/context/test_metacog_lessons_injection.py:36`、
`tests/unit/cognitive/test_v3_closed_loop.py:77` 手工传 `metacog_agent_id`；
`tests/unit/cognitive/test_regulation_gate.py:62` 手工设 env）。新增用例一律经生产构造点取
注入器，不再手工传参：

- `tests/unit/context/test_metacog_production_wiring.py` — 教训经
  `ContextOrchestrator.init_context_system()` 进入信封
- `tests/unit/cognitive/test_regulation_gate.py::RegulationGateGovernanceSettingTest` — 开关四态
- `tests/unit/api/test_governance_settings.py::test_put_metacog_gate_persists` — 管理面写入

## 登记项（本次刻意不修）

- **R1 同类根因未收口**：`neurova/cognitive_layers/memory_layer/reasoning_trace_manager.py:149`
  的持久化门控是同一口径的裸 env 开关（注释自称"与 NEUROVA_METACOG_GATE 同口径"），
  生产同样无配置面。本次只修反思链用到的两处，R1 待单独批次处理。
- **R2 审批队列静默丢弃**：`skill_experience._pending_records` 有界 50，超出即丢且无告警。
  归因臂依赖人工审批节奏，审批滞后时丢的是"教训落到技能层"的证据。
- **R3 有效性度量缺席**：全仓没有"反思注入后行为改善率"一类的度量回流。
  `growth_log.py:544 get_statistics` 仅 `api/endpoints/growth.py:447` 展示；
  `memory_layer/modules/self_manager_module.py:168 record_efficacy`、`:195 get_recent_reflections`、
  `:200 get_success_rate`、`memory_layer/manager.py:2464 self_record_task_run` 全仓无生产调用方。
  链A 的闭环靠赞踩与困惑信号驱动，不靠统计。
- **R4 展示环数据**：`meta_records kind="reflection"` 的读取方是
  `ledger.py:280 reflection_history` → `api/endpoints/metacognition_api.py:153` 与
  `memory_layer/manager.py:2082` 两条展示委托，不参与决策；thought 镜像同性质
  （`self_model.py:265` 自述"展示层增强"）。属有意的可见性增强，
  不得被误读为反哺通道。

## 本次改动面的预存红（非本批引入）

`tests/unit/api/` 下 `test_transfers_wave_h4`、`test_files_store_persistence`、
`test_my_skills_wave_v`、`test_public_library_wave_h3`、`test_skill_pool_api_rlock_protection`
共 15 项红。判据：这些用例不 import 本次改动的任何模块（grep 无命中），其失败内容
（404 vs 409、`KeyError: 'data'`、rlock 分层断言、Windows 临时库 WinError 32）落在
`neurova/api/app.py`、`neurova/api/endpoints/__init__.py` 与技能池在途改动面上，
且失败集合在不同次运行间不一致（文件锁抖动）。本批未修，留待该在途改动收口后复跑。
