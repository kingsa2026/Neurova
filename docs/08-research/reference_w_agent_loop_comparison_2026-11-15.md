# ZCode Agent Loop 机制对照——Neurova 视角的分析与可补充候选

- 日期：2026-11-15
- 对象：zai-org/ZCode v3.18.2（克隆件 `E:/项目/_external_repos/zai-org-ZCode`，只读参照）
- 方法：代码级逐文件阅读（未依据任何文档），行号均为当日实测
- 关联：`zcode_vs_neurova_harness_code_comparison_2026-11-14.md`（总评）、
  `zcode_swarm_orchestration_comparison_2026-11-15.md`（子代理编排）、
  `zcode_tool_inventory_comparison_2026-11-15.md`（工具清单）

## 1. 总览

ZCode 的 agent loop 是**三层结构**：会话命令层（可取消命令队列＋自动续跑循环）、
Turn 层（一次用户输入的完整编排）、模型步层（`while(true)`，每次迭代＝一次
provider 请求）。核心特征是**显式相位状态机**、**提醒/公告先落盘后进历史**的
冷恢复一致性纪律、以及一条**有序的失败恢复阶梯**。

Neurova 的对应物是 `neurova/agent/loops/` 的 gate-runner 形态
（`base.py` 1064 行＋`openai_loop.py` 1112 行＋`anthropic_loop.py` 532 行）：
GoalGate / IterationGate / TokenBudgetGate / doom-loop 检测 / reasoning
degeneracy 门，出口判定为 done/stop/resume。

## 2. 三层结构（ZCode）

| 层 | 落点 | 职责 |
|---|---|---|
| 会话命令层 | `runtime/command-queue.ts`、`methods/target-continuation-loop.ts`、`runtime-command-active-loop.ts` | 可取消运行时命令队列；target 自动续跑循环——每轮重新读取 Session Selection，允许用户中途插入成为新权威（target-continuation-loop.ts:70-98） |
| Turn 层 | `methods/turn.ts`（1201 行） | 一次用户输入 → TurnComplete：模型创建、loop state 组装（turn.ts:844-907）、goal 结算、stable fork boundary 落盘、记忆提取调度、turnNumber 递增（turn.ts:986） |
| 模型步层 | `methods/turn-loop.ts`（482 行）＋`turn-model-step.ts`（981 行） | `runRegularTurnLoop` 的 `while(true)`——每次迭代＝一次 provider 请求；单步内含流式、工具调度与恢复阶梯 |

## 3. Turn 显式状态机（`agent/turn-machine.ts` 344 行＋`turn-state.ts` 266 行）

- **10 相位**：`Idle → ProcessingInput → AwaitingModelResponse → Streaming →
  SchedulingTools → AwaitingPermission / ExecutingTools → AggregatingResults →`
  （有失败 → Completing；否则**回 AwaitingModelResponse**——agent loop 的回路
  就在这一条迁移上，turn-machine.ts:328-336）`→ Completing / Error`
- `canTransitionTo` 静态合法迁移表（turn-state.ts:233-266），非法迁移抛
  `InvalidTurnPhase`；`getNextPhase()` 由当前状态推导下一相位
- 工具调用六状态：`scheduled / waiting_permission / permission_denied /
  running / completed / failed`（turn-state.ts:108-114）
- 调度形态 `ToolScheduleState` 携带 `parallelGroups + executionOrder`
  （依赖感知的并行调度，turn-state.ts:122-132）
- `TurnResultType`：`success / cancelled / error_max_turns / error_max_budget /
  error_during_execution / error_max_tool_calls`（turn-state.ts:151-158）——
  注意这些是**契约词汇**，核心循环内未见强制执行点（见 §7）

对照：Neurova 的 loop 没有显式相位机；轮次状态散在
`turn_run_state.py`（153 行）与各 loop 实现的实例字段里，相位合法性靠约定
而非迁移表。

## 4. 每步循环体固定次序（turn-loop.ts:71-267）

1. `throwIfTurnAborted`（取消检查贯穿全程每个阶段间隙）
2. 排空 pending runtime commands——steering 插话、后台子代理结果、workflow
   结果并入下一请求（turn-loop.ts:83-97）；排空过则重置重复工具调用签名计数
3. MCP init＋`tools/list_changed` 只在回合边界刷新；`getTurnTools` 给出本回合
   工具可见面
4. **输入附件收集**——时机纪律：只在轮首、完整工具批次之后、文本 guide 续接
   三种时机收集（`inputAttachmentCollectionPending` 单字段记录原因，
   turn-loop-state.ts:125）；产出 output_style、todo、plan-mode 退出、
   runtime-mode、silent-turn、total-tokens 预算倒数等 system-reminder 附件。
   **全部先落盘再进历史**（persistAnnouncements 先持久化成功再 commit），
   resume/fork 后请求前缀字节一致
5. microcompact → autoCompact，带 **rapid-refill 熔断**：连续 3 次 compact 且
   距上次 compact 不足 3 个工具轮 → 直接报错拒跑
   （`RAPID_REFILL_TOOL_TURN_THRESHOLD = 3`、`MAX_CONSECUTIVE_RAPID_REFILLS = 3`，
   turn-loop-state.ts:24-25）——防"压缩—涨回"死循环
6. 请求前公告（compaction 之后运行，不受附件跳过规则影响）→
   `prepareRuntimeProviderRequest`（ToolSearch 两段式暴露；cache-control 锚点
   在 provider 投影之后统一设置，避免合成 entry 抢占缓存锚点，turn-loop.ts:220-223）
7. `TurnMachine.startModelRequest` → `runModelBackedTurnStep` →
   `continue / output_continuation / break`

## 5. 模型步与失败恢复阶梯（turn-model-step.ts）

流式回调（reasoning/text/tool-call delta）直接喂
`streamingToolCoordinator`（438 行）——流中即可受理工具调用并先行执行。
`maxOutputTokens` 按模型上下文窗口与当前估算用量动态钳制
（turn-model-step.ts:262-270）。

**失败恢复阶梯**（按序尝试，命中即 `continue` 重入循环）：

1. **执行 Selection 声明式降级**：加速 provider 边界失败 → 退回会话模型；
   必须先于通用流恢复——否则流中断会先在加速模型上重试到预算耗尽，
   降级形同虚设（turn-model-step.ts:301-329）
2. **流恢复**：断流重试，重试计数耗尽后归一错误文案
3. **闲时接管**：off-peak 用户接管替换当前请求（turn-model-step.ts:347-369）
4. **Start Plan 准入繁忙短重试**：第二轮起可能在首 token 前被准入并发限制
   拒绝——关闭空 assistant 后短延迟重试（turn-model-step.ts:370-440）
5. **取消快照持久化**：用户 Stop 时把半截流按 blockIndex 有序落盘，
   冷恢复可回放（turn-model-step.ts:461-514）
6. **上下文超限 reactive compact**：每模型步最多一次
   （`reactiveCompactAttemptedInCurrentModelStep`），同样受 rapid-refill 熔断
   约束（turn-model-step.ts:918-980）

成功路径要点：finish reason 归一化（非标准 output-limit 归一为 length，
原始事实留在诊断日志）；output-token 续写分类（可续→续写恢复，耗尽→
诚实报错收口）；provider 内置工具轮（如 web_search）与本地工具调用分离计数；
可疑空结果与内容过滤空结果识别熔断。

## 6. 工具批执行（turn-tools.ts，326 行）

- 本地工具按 `blockIndex` 稳定排序后再调度、执行、提交——live 结果与冷恢复
  字节一致（turn-tools.ts:53-59；blockIndex 在流的 tool_input_start 分配，
  到达顺序可能与之不同）
- 流中已执行的（streamed）与常规调度分离结算；未执行的走
  `scheduleTools → executeTools`（parallelGroups 并行）
- 批开始回调逐个持久化 tool part（running 态）并发 ledger 事件；abort 时由
  executor 为每个 call 生成 ToolCancelled 结果，不在结果创建前抛出
- `turnControl.stopTurnAfterResult`：工具结果可要求终止回合——automation
  创建上限命中后，当前 turn 永久切为纯文本回复并忽略后续幻觉工具调用
  （turn-tools.ts:269-308、turn-model-step.ts:583-596）

## 7. 终止面与预算

- 无工具调用 → `finishModelStepWithoutToolCalls`（turn-stop.ts:167-254）：
  automation 上限文本收口 → **inline guide drain**（用户插话以 user-role
  续同一 active turn，不改投 future queue）→ **Stop hooks**（可携
  additionalContext 续跑同一 product turn）→ 否则 complete＋break
- **核心循环没有硬性 max-turns**：`error_max_turns / error_max_tool_calls /
  error_max_budget` 是 contracts 词汇（contracts/src/events/session.events.ts:706），
  核心运行时未见强制点；子代理有界——`maxTurns: request.maxTurns ??
  config.subagents?.maxTurns ?? 4`（runtime/methods/subagent.ts:340）
- 主循环真实终止条件：无工具调用＋无 guide＋Stop hook 不续跑＋abort

## 8. Neurova 现状（对照基准）

- `agent/loops/base.py`（1064 行）：`BaseAgentLoop`＋gate-runner——
  GoalGate（`goal_max_continuations` 默认 2，独立于工具轮预算）、
  IterationGate（`resolveToolRoundBudget()`，`turn_run_state.py:26` 单源派生
  `max_loop_rounds // 2`）、TokenBudgetGate、doom-loop 检测
  （`doom_loop_max_interrupts`）、reasoning degeneracy 门；出口判定
  `LoopExitDecision` done/stop/resume
- 工具批：`resolveParallelBudget()`（单批并行上限，单源
  `max_parallel_tools`）；批次形状记录 `_recordBatchShape`
- 已有的 ZCode 同款能力：停让/预算闸（429 退避、retry budget）、
  上下文压缩族（B 批：冻结增量折叠、增长门、微压缩）、hooks 事件族、
  子代理编排（蜂群八项已补齐）

## 9. 逐项对照

| 机制 | ZCode | Neurova | 判定 |
|---|---|---|---|
| 相位状态机 | 显式 10 相位＋迁移表＋非法迁移抛错 | 实例字段＋约定 | **差距**（可测性/审计性） |
| 提醒/公告落盘纪律 | 先持久化再进历史，冷恢复前缀字节一致 | 部分提醒走 session 落盘，口径不一 | **差距**（恢复一致性） |
| compact 防抖 | rapid-refill 熔断（3 次/3 轮阈值） | 增长门＋折叠（B 批），无"连续快速重压缩"熔断 | **差距**（小而实） |
| 模型失败恢复阶梯 | 降级→流恢复→接管→准入重试→取消快照→reactive compact，次序有据 | multi_model_client 重试/熔断/降级链（弹性包），无取消流快照 | 互有短长（**取消快照是差距**） |
| output-token 续写 | finishReason=length 分类续写/诚实收口 | 有续写处理（openai_loop），归一口径未对齐 provider 原始事实 | 接近 |
| steering 插话 | inline guide 以 user-role 续同一 active turn＋FIFO barrier 兜底 | 会话级消息队列，无 active-turn 内联语义 | **差距**（交互形态） |
| 工具批排序 | blockIndex 稳定排序，live 与冷恢复一致 | 按到达顺序 | **差距**（恢复一致性，小） |
| 工具结果终止回合 | turnControl.stopTurnAfterResult（如 automation 上限→纯文本收口） | 无此控制面 | **差距**（小） |
| 目标校验/退化检测 | 无（Stop hook 之外无 goal gate） | GoalGate＋doom-loop＋reasoning degeneracy | **Neurova 优势** |
| 循环预算 | 主循环无硬限（宿主/子代理层执行） | IterationGate max_rounds＋TokenBudgetGate 显式硬限 | **Neurova 优势**（防失控） |
| member/会话恢复 | 冷恢复 hydration＋快照回放 | 会话 JSON＋账本重放（/replay） | 各有形态 |

## 10. 可补充候选（按优先级）

**实施状态（2026-11-15，全部处置）**：

- **#1/#2 已实施**（相位状态机 `neurova/agent/loops/turn_phase.py`＋双环推进；
  六类轮内注入先落盘后进历史，`persistModelVisibleAnnouncement` 单点）；
- **#3/#4/#5 已实施**（取消流快照随失败轮落点；溢出重压缩账本化＋
  rapid-refill 熔断 `CompactRapidRefillError`；steering 入队侧——
  活跃回合注册表＋`submitSteer`＋chat 双端点插话通道，环侧排空既有）；
- **#6/#7 已实施**（分片合并保留 `_stream_index`＋工具批稳定排序；
  `turn_control` 终止回合控制面——信号经调用的 tool_call 字典回传，
  双环结算后诚实收口）；
- **#8 核实为既有能力**：`multi_model_client.chat` 的 auto-failover
  （`switch_to_next_model`/`_resolve_available_fallback`，按
  `is_fallback_eligible` 分类跨模型切换、429 累计等待预算、请求级排除集）
  已覆盖"执行模型失败按声明退回"的实质；显式指定 provider 时不静默切换
  是既有产品裁定，保持不变。

| # | 候选 | 说明 | 优先级 |
|---|---|---|---|
| 1 | **loop 相位状态机** | 把轮次相位（输入处理/等待模型/流式/工具调度/执行/聚合/完成）显式化＋静态迁移表；非法迁移出声。可测、可审计，也为分段提醒/诊断提供锚点 | **P1** |
| 2 | **提醒/公告先落盘后进历史** | 统一"持久化成功才 commit 进请求历史"的口径，resume/fork 后请求前缀字节一致；是 /replay 与会话恢复的确定性基础 | **P1** |
| 3 | **取消流快照** | 用户中断时把已收到的半截流（reasoning/text/tool call）按序落盘，恢复后可回放续写，不丢已产出内容 | **P2** |
| 4 | **rapid-refill 熔断** | 连续快速重压缩计数器：compact 后不足 N 个工具轮又触发压缩达 M 次 → 拒绝并诚实报错，防死循环烧预算 | **P2** |
| 5 | **steering 内联语义** | 用户在工具批次间插话时，以 user-role 续当前 active turn（而非开新轮排队），配合 FIFO barrier 兜底 | **P2** |
| 6 | **工具批 blockIndex 稳定排序** | 工具调用按流内序号排序后再执行/结算，live 与冷恢复字节一致 | **P3** |
| 7 | **工具结果终止回合控制面** | 工具结果可声明"结算后终止本轮"（如配额上限→纯文本收口，防模型绕行循环） | **P3** |
| 8 | **执行降级声明** | 加速 provider 失败按声明退回会话模型，且必须先于通用重试（次序纪律比机制本身更重要） | **P3** |

## 11. 结论

ZCode 的 loop 强在**确定性与可恢复性**：显式相位机、落盘纪律、取消快照、
稳定排序，全部服务于"任何时刻中断都能一致回放"。Neurova 的 loop 强在
**受控性与自检**：目标校验、退化检测、显式预算硬限。两者互补——
上表 1/2（P1）补的是可审计与恢复一致性的地基，3-5（P2）补的是长任务
体验与防烧预算，6-8（P3）是一致性细节。实施时应保持 Neurova 既有
gate-runner 的预算硬限不放松，只在其内引入相位机与落盘纪律。
