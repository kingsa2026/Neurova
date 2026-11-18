# QwenPaw vs Neurova 主流 Harness 框架对照评测（2026-11-18）

> 评测对象：[agentscope-ai/QwenPaw](https://github.com/agentscope-ai/QwenPaw)（HEAD `8ac8efb8`，v2.3.0）vs 本仓 Neurova（main）。
> 方法论：**不再按 QwenPaw 产品形态定制维度**（旧版报告 v1–v5 的教训），改用主流 agent harness 评测共识的十维能力框架——任务规划与分解、工具执行可靠性、上下文工程、记忆体系、自我改进与学习、多 agent 编排、人机协作、安全与治理、工程可靠性与可观测、生态与部署。每维 10 分、等权，满分 100。两侧均以逐文件代码走读为据（QwenPaw 六路分析 + Neurova 三路补读，全部结论附文件与行号）。
> 维度依据：覆盖主流 agent 评测（ReAct/Reflexion/planning/memory/tool-use）与 harness 工程评测（恢复、门禁、编排、HITL、生态）的公共能力面；对"个人助理"与"多 agent 平台"两种定位均中立。

---

## 1. 执行摘要

**总分（十维等权，满分 100）：QwenPaw 81.5 vs Neurova 80.5。**

- 换用中立框架后，两者**几乎打平**（差 1 分），远小于旧版"QwenPaw 形态标尺"下的差距（86.5 vs 82.5）。原因：旧维度把渠道/生态/部署（QwenPaw 主场）权重放到 35%，而本仓的规划、自我演化、可靠性工程三项强项未进维度。
- **QwenPaw 领先**：工具执行可靠性（9.0 vs 8.5）、安全多平台沙箱（9.0 vs 8.0）、人机协作（8.5 vs 8.0）、生态与部署（9.5 vs 8.0）。
- **Neurova 领先**：任务规划与分解（8.0 vs 7.0）、记忆体系（9.5 vs 8.5）、自我改进与学习（9.0 vs 7.0）、多 agent 编排（9.0 vs 6.5）、工程可靠性与可观测（8.5 vs 7.5）。
- 一句话结论：**两家是不同物种的同量级选手——QwenPaw 是"渠道+生态+部署"打磨到天花板的产品化个人助理；Neurova 是"规划-演化-编排-可靠性"纵深更强的 agent 平台。中立标尺下综合实力相当，各自的主场维度差距都在 2 分以上。**

## 2. 十维逐项对照

### P1 任务规划与分解 —— Neurova 8.0 / QwenPaw 7.0

**Neurova**：三条规划链路——`plan_mode/plan_session.py:215-344`（澄清→LLM 计划→落盘→**人工审批**→execute_prompt，经 `/v1/plans` API）；`planning/planning_tool.py:256-396`（planning 工具 7 命令，SQLite `PlanStore` 持久化）；`tool_executor.py` `orchestrate_tools`（goal→DAG 步骤编排）。任务分解用结构化 `TaskUnit`（`agent/task_unit.py:21-46`：goal/expectedResult/acceptanceCriteria/dependencies/reviewMode）+ 依赖门 DAG 串并行（`swarm.py:1397-1423`）。停止控制分层完整：IterationGate/TokenBudgetGate/DoomLoopGate/GoalGate 四门 + GateRunner 优先级与故障隔离（`agent/gates.py:394-423`）+ 出口唯一求值点 `evaluateLoopExit`（`loops/base.py:127-231`）+ 相位机（`loops/turn_phase.py`）。弱点：计划是"记录/协商型"，审批后仍靠手动触发执行，无步骤级强制推进状态机；DoomLoopGate 默认逐字相等（`gates.py:167`），同义换参空转抓不到。

**QwenPaw**：`make_plan` 技能 + `omp_workflows` 插件（Autopilot/Ralph/UltraQA/Ultrawork/Team 五模式）+ 声明式停止门编译（`loop/catalog.py:155` 7 种 gate、`loop/compiler.py:11` 原子编译、互斥组校验——此项为独有亮点）+ doom loop 多阶段升级（`gates/doom_loop.py:37`）。弱点：规划靠技能文本引导，无持久化计划工具与审批流；gate 异常吞掉仅 warning（`loop/gates/handler.py:100-107`）。

### P2 工具使用与执行可靠性 —— QwenPaw 9.0 / Neurova 8.5

**QwenPaw**：ToolCoordinator 单一执行所有者（`tool_calls/_coordinator.py:55`），**offload/kill 双截止**（到 deadline 先转后台返回占位、循环继续，kill 兜底强杀，`_timeout_helper.py:16`）+ 每 tool 超时钩子与硬上限（`_hooks.py:23`）+ 流式 fan-out + 每次模型调用重建 schema 索引做输入纠偏（`react_agent.py:1116-1135`）。弱点：完成缓存仅 50 条/60s；无调用级重试/幂等。

**Neurova**：四级派发漏斗（workflow→builtin→skill→tool_router，`tool_executor.py:1896`）+ 参数闸/schema 校验失败回传 LLM 自纠（:1711-1721）+ 单调守卫恒开（:1765-1781）+ 治理四级裁决 allow/deny/ask/sandbox（:2022-2100）+ ASK 有界人工审批（:2183）+ per-tool 超时表三处置 BACKGROUND/ABORT/KILL + **诚实收尸**（未确认退出如实标注，`agent/tool_coordinator.py:296-339`）+ 大输出落盘引用 + **MCP 熔断器**（连续失败→OPEN→半开探测→stale 缓存降级，`tool_layers/mcp_resilience.py:48-160`）。弱点：无通用自动重试/幂等键；后台执行态纯内存，进程重启即失。

### P3 上下文工程 —— 平 9.0 / 9.0

**Neurova**：折叠分代 + `fold_index.py` covers 层级索引与档号（确定性下钻）+ `fold_trigger.py` 增长门（demand-side 主动折叠，默认开）+ `compression_doctrine.py` 版本化压缩教义（覆盖门禁）+ `summarizing_compressor` 防幻觉 factsheet + `token_estimator` 图像分段计价修正 + context_pool 归档语义召回。
**QwenPaw**：scroll 策略（SQLite verbatim + EvictionIndex 层级索引 + **沙箱 Python REPL 只读 ATTACH 历史库 recall**，`memoryspace.py:3-10`）+ 统一溢出恢复 + token 保证金（拒收自适应抬高基线，`scroll/manager.py:390-463`）+ decision_compaction/visual_compression 两种附加压缩。
双方各有独门：QwenPaw 的"模型可用 Python 查历史"与 Neurova 的"压缩教义+门禁"都是一流实践。

### P4 记忆体系 —— Neurova 9.5 / QwenPaw 8.5

**Neurova（类脑多层级）**：肌肉记忆三级（L1 条件反射毫秒级/L2 热缓存/L3 原始记录，连成 2 次固化、30 天降级，`muscle_memory.py`）+ NeuHebb Hebbian 可塑性（forge/curator/manager）+ 模式结晶器（Hebb 学习替代 LLM）+ **睡眠整合**（`sleep.py`：聚类合并/温度衰减/压缩归档 + writeback）+ 温度引擎（**贝叶斯遗忘曲线**+情感保护，`temperature.py`）+ 情绪记忆 + 因果/时序/缺席推理 + 联想线索族 + 记忆准入（敏感拦截+该记/不记/绝不记清单单点包层，`memory_admission.py`）+ 污染清除/版本控制/隔离共享 + MoE 向量门控与 RRF 融合检索。
**QwenPaw（三层存储）**：working context / SQLite+FTS verbatim（只读 ATTACH 防自污染）/ ReMe Markdown 自演化知识库（LLM 归纳 + auto_dream cron 蒸馏 + 向量 0.7+BM25 RRF+wikilink），人机共编 MEMORY.md + 3D 记忆图谱前端。
Neurova 深度占优；QwenPaw 胜在自演化产品化入口（人机共编）与可视化。

### P5 自我改进与学习 —— Neurova 9.0 / QwenPaw 7.0

**Neurova**：完整 **RSI 闭环**（`evolution/rsi/orchestrator.py:938` run_iteration：反馈信号→收敛分析→候选生成→**部署阶段门 0-4**（`deployment_controller.py:17-56`，晋升需无回滚天数+ROI+经验质量）→应用前快照→**确定性评测集实测 gain+配对 CI+e2e 对齐差分**（:1038-1049）→不过 `rollback_manager` 恢复快照并结清债务）+ 遗传算法工具序列演化（`genetic_engine.py`）+ PrefixSpan 频繁序列挖掘（`pattern_miner.py`）+ NL 合成工具（`nl_synthesizer.py`）+ 技能三臂沉淀链（执行证据记账 3 次→AutoSkillBuilder 封装→评审闸默认开→人工批准→registry，`creation_governance.py:303,402`）+ 生命周期 active→stale→archived。弱点：端到端评估以确定性 setpoint 代理为主（`rsi/eval_harness.py:5-18` 自述缺口）。
**QwenPaw**：make-skill 元技能 + 市场沉淀 + decision model 能力缓存；**无系统性自我演化闭环**（无候选评估/回滚/晋升机制）。

### P6 多 agent 编排 —— Neurova 9.0 / QwenPaw 6.5

**Neurova**：SwarmManager 三通道回流（直传/池归档/邮箱终态回灌，`agent/swarm.py` 头注）+ 结构化 TaskUnit + 依赖门 DAG + 团队/房间双入口 + 审批链 L0/L1/L2 + 候选制 CAS 合并与冲突升级 + run 级 JSONL 事件账本与因果链（`swarm_event_log.py`）+ 状态迁移表 + 子代理五工具（spawn/查岗/点名/改需求/叫停）+ review_gate 回炉与 acceptance_gate 验收（不达标产出不作合格结果回流，`acceptance_gate.py:138-146`）。
**QwenPaw**：spawn_subagent + git worktree fork 隔离 + **ACP 双向**（可被 Zed/OpenCode 连接、可托管外部 agent，`acp/server.py`/`service.py:303`）+ 协作技能 + omp_workflows 五模式。互操作面有独到之处，但无团队/审批/候选/账本级协作治理。

### P7 人机协作（HITL） —— QwenPaw 8.5 / Neurova 8.0

**QwenPaw**：五档执行级别（STRICT/SMART/JEV/AUTO/OFF）+ JEV 决策模型预评估 + **审批卡片直达 IM**（telegram/qq/wecom/feishu/dingtalk 内点批准）+ REST + 聊天命令三入口 + EXACT_REQUESTER 身份策略 + 审批泛化规则安全校验（`governance/generalize.py`）+ 超时即拒。
**Neurova**：审批链 L0/L1/L2（判定权单源回灌）+ hitl_surface + approval_manager/relay/continuation + parked 挂起凭 run_id 续跑（身份防越权，`console.py:318-330`）+ plan_mode 计划人工审批 + 工具 ASK 有界等待。差距：审批入口在 console/前端，未做到 QwenPaw 式"IM 内卡片即批"。

### P8 安全与治理 —— QwenPaw 9.0 / Neurova 8.0

**QwenPaw**：四平台内核沙箱（Seatbelt/Landlock/Bubblewrap/AppContainer+Job Object）+ **内核状态自证**（`runtime_boundary.py:22-79`）+ 4 guardian 工具卫兵 + 42 条中英双语技能扫描规则（安装期硬拒）+ 两层访问策略 + SQLite 审计 + Fernet/keychain。弱点：guardian fail-open、沙箱默认关、Bubblewrap 无网络隔离、决策模型云端外发脚本。
**Neurova**：44 文件安全域（tool_guard/shell_normalization/skill_scanner/tool_circuit_breaker/rbac/audit_logger/secret_store 等）+ Windows AppContainer 沙箱 + 记忆准入闸 + context_firewall + 147 条审计修复闭环。差距：macOS/Linux 内核级沙箱缺位；沙箱整体深度小于 QwenPaw。

### P9 工程可靠性与可观测 —— Neurova 8.5 / QwenPaw 7.5

**Neurova**：**完整恢复链**（哨兵崩溃检测 `shutdown_guard.py:115-153` → 会话重放 `:201-308` → run 台账启动对账与僵死清扫 `agent_run_store.py:533-664` → git 检查点事务化回滚 `checkpoints/service.py:181-223`）+ parked 非终态可续跑 + 失败轮诚实落盘（`failed_turn_landing.py`）+ **CI 十层门禁**（静态/部署配置/架构+尺寸棘轮/导入巡检/三分片单测+覆盖率 60%/e2e 冒烟/前端 audit+vue-tsc+vitest/性能/依赖审计/经验质量）+ CodeQL + cost-guards + 2,738 测试文件 + A/B 零新增纪律。弱点：遥测默认关且导出失败即丢不重试（`telemetry/client.py:28-30,121-124`）；analytics 含 mock 指标路径；后台执行态不持久。
**QwenPaw**：43 CI 工作流 + 918 单测文件 + 238 e2e 用例 + 覆盖率棘轮 50% + bundle 预算 + CodeQL；弱点：约 50 处 except-pass 静默降级、无 metrics/tracing 主线（仅 237 行 Langfuse 可选）、无崩溃恢复/对账体系、审计藏在 governance。

### P10 生态与部署 —— QwenPaw 9.5 / Neurova 8.0

**QwenPaw**：37 内置 provider + FallbackChatModel + per-model 限流隔离 + 本地模型运行时（Ollama/onnx/自家 Flash 系列）+ 五部署形态（PyPI/Docker/Tauri 桌面+PyInstaller/源码/平台托管）+ MCP 双向 + 7 源技能市场 + 41 插件 + 18 渠道。
**Neurova**：多 provider + docker/helm/compose + web/鸿蒙/安卓三端（移动原生为独有）+ MCP server（ontology）+ 技能市场多源链路 + 12+ 渠道。差距：无桌面安装包、无本地模型运行时打包、provider 数量与市场体量较小。

## 3. 评分表

| # | 维度 | QwenPaw | Neurova |
|---|------|---------|---------|
| P1 | 任务规划与分解 | 7.0 | **8.0** |
| P2 | 工具使用与执行可靠性 | **9.0** | 8.5 |
| P3 | 上下文工程 | 9.0 | 9.0 |
| P4 | 记忆体系 | 8.5 | **9.5** |
| P5 | 自我改进与学习 | 7.0 | **9.0** |
| P6 | 多 agent 编排 | 6.5 | **9.0** |
| P7 | 人机协作（HITL） | **8.5** | 8.0 |
| P8 | 安全与治理 | **9.0** | 8.0 |
| P9 | 工程可靠性与可观测 | 7.5 | **8.5** |
| P10 | 生态与部署 | **9.5** | 8.0 |
| | **合计（满分 100）** | **81.5** | **80.5** |

## 4. 与旧版（QwenPaw 形态标尺）结论的差异

- 旧版（v1–v5，`qwenpaw_vs_neurova_personal_assistant_harness_evaluation_2026-11-17.md`）维度按 QwenPaw 形态定制，渠道/生态/部署合计权重 35%，且未纳入规划、自我演化、可靠性恢复三项——对 Neurova 系统性不利。该报告保留作为"个人助理形态标尺"的视角，但**结论以本报告为准**。
- 中立框架下的新结论：综合实力 QwenPaw 81.5 ≈ Neurova 80.5；QwenPaw 的领先集中在"产品化完成度"（渠道/生态/部署/安全纵深/HITL 触达），Neurova 的领先集中在"harness 纵深能力"（规划、记忆、自我演化、编排、可靠性恢复）。

## 5. 双方改进清单（按性价比）

**Neurova 值得从 QwenPaw 借鉴**：渠道子进程隔离+握手期依赖审计；审批卡片直达 IM；macOS/Linux 内核沙箱（Seatbelt/Landlock/Bubblewrap）+内核自证；技能扫描器 42 条双语规则库；工具 offload/kill 双截止与完成缓存查询；per-model 限流隔离；覆盖率棘轮+bundle 预算门；本地模型运行时与桌面安装包。
**QwenPaw 值得从 Neurova 借鉴**：RSI 闭环（阶段晋升门+快照回滚+确定性评测+配对 CI）；run 级事件账本与因果链；崩溃哨兵→会话重放→台账对账的恢复链；goal_verifier 禁工具防自我污染的出口验收；记忆准入清单与污染清除；审批-重放-守卫的工具治理闭环；候选制 CAS 合并。

## 6. 局限性

- 双方均为静态代码走读 + 抽样深读，未做同任务实跑对比（真模型基线见 `multi_agent_bench_baseline_2026-11-17.md`，仅覆盖本仓）。
- 十维等权是简化处理；不同产品定位下权重应不同（个人助理场景 P10 权重应更高，自主 agent 场景 P5/P9 应更高）。
- Neurova 侧 P1/P2/P5/P9 为本轮三路深读新核实；P3/P4/P6/P7/P8 沿用此前逐目录核实证据；QwenPaw 侧沿用六路分析（HEAD `8ac8efb8`）。
