# 外部编码代理（ZCode）工具调用与循环机制对标 · 取证与缺口复验

> **文档性质**：研究参考 / 外部对标。按 [`docs/INDEX.md`](../INDEX.md) §2.4 归类，**不可作为事实源**。
> 本文仅记录"外部实现做了什么、本项目当前做了什么"的对照取证，**不构成设计标准**。
> 落地任何一条时，须按 [`AGENTS.md`](../../AGENTS.md) 协作红线"原创性与自主性"独立设计：
> **不得**在本仓代码注释、技术文档、提交记录中出现"对齐/参照 ZCode"一类表述。
>
> ## ⚠️ 状态更新（2026-09-30 对齐至 `da843611` + `189fc321`）—— 本文 §5/§8 的"仍开放"判定已过期
>
> 本文是**取证与判据**，不是现状。当初列的 8 条缺口，到此已基本清偿：
>
> | | 现状（逐条核实，非读提交标题） |
> |---|---|
> | G1 迭代化 | 已闭合，自递归与 `_top_level` 归零；轮次态随调用传递；子代理深度上限有守卫 |
> | G2 出口验收 | 已闭合，且优于本文方案：`evaluateLoopExit`(`base.py:71`, `isLoopExit`) 两路都接 + **GoalGate 进默认装配** + 续跑预算绑独立键 `goal_max_continuations` |
> | G3 并发 | M1–M4 + 逐工具裁决(71/71) 已落地；**收益判据仍 `no_data`（未否证，别当否证）** |
> | G4 取消 | 已闭合（`TimeoutDisposition.ABORT`） |
> | G5 审批 | `189fc321` / MR #339 落地；HTTP 活体三条未验 |
> | G6 / G7 / G8 | 如本文所记（G7 剩"主动 cache marker"半条；G8 剩一条反向控制的标签口径） |
>
> **净结论：原 8 条里只剩 G7 半条与一条台账标签 nit。** 保留正文原文是为了留判断轨迹，引用其行号前须知
> 正文取证于 `69d7f0dc`/`c55e1f37`，此后 loop/tool 轴有 138 个提交。本文 §9 的更正值仍低于正文可信度：
> 它记的是"我判断错过什么"，不是"现在是什么"。

>
> 生成时间：2026-09-26 · Neurova 取证基线：`c55e1f37` · 参照侧取证基线：`zai-org/ZCode` `872ad96`（v3.14.0）
> 本文取代同日会话中依据旧基线 `69d7f0dc` 得出的判定，差异见 §5 与 §9。

---

## 0. 本文回答的三个问题

1. 一个成熟的编码代理 harness，其**工具调用**与**迭代循环**到底是怎么装配的？（取证到 `path:line`）
2. Neurova 在同两个维度上，**当前**（而非历史上）处在什么位置？
3. 上一轮列出的 8 条缺口，在这次基线推进后**还剩几条**？

第 3 问的答案是本文最有操作价值的部分：**8 条里 3 条已闭合或已被机器接管（G6/G7/G8），真实剩余 5 条（G1、G2、G3、G4、G5）**。但四条的成本判定被后续实测推翻——G2 被**高估**（根因不是缺 caller），G1/G4 被**低估存在性、高估成本**（能力已在仓里，缺的是接线）。逐条见 §9。

---

## 1. 取证方法（可复现）

### 1.1 取源

```bash
# 落在工作树外，避免污染仓库（勿 clone 进 Neurova/ 内）
cd <工作区父目录> && git clone --depth 1 https://github.com/zai-org/ZCode.git zcode-ref
```

本次落盘 `E:\项目\zcode-ref`，122 MB。**未** 加入 Neurova 的 `.gitignore`（因为在仓库外，无需豁免）。

### 1.2 完整性核验（先证"这真是源码"再下结论）

开源仓常见的坑是"壳仓"——目录齐全但真逻辑是字节码/压缩包。三条判据全部通过：

| 判据 | 实测 |
|------|------|
| 可读性 | `packages/core/src` 495 个 `.ts`、23,953 行；CLI 全域 41,872 行 |
| 无产物壳 | `find . -name "*.js.map" -o -name "*.jsc" -o -name "*.bytecode"` → 空 |
| 提交形态 | 单提交 `872ad96 feat: open source`（squash 首投，**无历史可查**） |

**由此得出一条使用限制**：因为无提交历史、无测试（`find packages/core -name "*.test.ts"` → **0**），本文对参照侧的任何"为什么这么做"的解释都是**推断**，不是考据。例如"其沙箱被移除"只是 `packages/adapters/src/exec/node-execution-adapter-run.ts:276-277` 的注释声称，删因不可考——**不得**把这类状态读成行业趋势判断。

### 1.3 双侧取证纪律（证据强度分级）

参照侧文件量大，本次采用"主干自读 + 外围分派"的混合取证，故逐节标注强度：

- **【一手】** —— 本次会话中由执行者本人 `Read`/`sed` 读到的行。
- **【转述】** —— 由检索子代理返回、带 `path:line` 但执行者未逐行复验。**引用作决策依据前应复核。**

大致分界：循环主体、调度、收口/续跑、缓存排序 = 【一手】；工具声明与校验层、权限/Hooks/子代理层 = 【转述】。

Neurova 侧全部为【一手】，且逐条对准 `c55e1f37` 复验过——第一轮曾依据子代理报告下的结论，本次发现**两处判断有误**，见 §9。

---

## 2. 参照侧机制骨架

### 2.1 循环形态：迭代 + 显式状态机【一手】

`apps/zcode-cli/packages/core/src/runtime/methods/turn-loop.ts:47` 是 `runRegularTurnLoop` 的 `while (true)`。循环本身不管收口，只消费内层返回的 `"break" | "continue"` 信号（`:215-217`）。

状态由 `TurnMachineImpl` 承载（`agent/turn-machine.ts:68`），每个相位转移过 `canTransitionTo` 校验，非法即抛 `CoreErrorType.InvalidTurnPhase`（`:92-104`）：

```
Idle → ProcessingInput → AwaitingModelResponse → Streaming
     → SchedulingTools → [AwaitingPermission] → ExecutingTools
     → AggregatingResults → Completing | Error
```

三条值得注意的形态特征：

- **不可变状态 + 整体替换**：每次转移 `return { ...this.state, phase }`，调用方以 `state.turnMachine = new TurnMachineImpl(state.turnMachine.xxx())` 形式接管（`turn-tools.ts:146-148`）。转移历史可追溯。
- **续跑不是递归，是排队**：目标续跑经 `enqueueCancellableRuntimeCommand`（`target-continuation-loop.ts:18-42`）投入命令队列，且**有待处理命令就让路**（`:56`）——用户输入可以抢占自动续跑。
- **循环内无轮次硬顶**：`while(true)` 没有 `max_rounds` 判断（仅子代理有 `maxTurns`，默认 4，`runtime/methods/subagent.ts:269`）。止损责任在 §2.3 的四把权柄上。

### 2.2 单轮九步【一手】

每轮固定顺序（`turn-loop.ts:47-213`），顺序本身就是设计：

| # | 动作 | 位置 |
|---|------|------|
| 1 | 中止检查 | `:48` |
| 2 | 排空待处理运行时命令（后台子代理结果、workflow 通知） | `:55-65` |
| 3 | `microcompactIfNeeded`（Phase = PreRequest / MidTurn） | `:67-74` |
| 4 | `autoCompactIfNeeded` + **rapid-refill 熔断** | `:77-102` |
| 5 | `initializeMcp` | `:105-107` |
| 6 | 建本轮工具目录 + 施加 turn 级 denylist | `:109-118` |
| 7 | 注入提醒（plan_mode_exit / runtime_mode / todo / output_style） | `:120-167` |
| 8 | provider 可见消息投影 + **统一打缓存锚点** | `:168-186` |
| 9 | 记录请求元数据（不落内容）→ 跑模型步 | `:187-213` |

第 4 步值得单独记：**rapid-refill 熔断**（`turn-loop-state.ts:154-168`）。压缩后若 3 个工具轮内又打满（`RAPID_REFILL_TOOL_TURN_THRESHOLD = 3`），连续 3 次即抛错终止（`MAX_CONSECUTIVE_RAPID_REFILLS = 3`）。防的是"压缩→立刻又满→再压缩"的抖动空转——这一态在 Neurova 的 recovery 通路里没有对应物。

### 2.3 收口与续跑的四把权柄【一手】

参照侧"何时算完"不是单点判断，而是四处赋权，方向各异：

| 权柄 | 方向 | 位置 |
|------|------|------|
| **工具请求停止** | 工具 → 结束本轮 | `turn-tools.ts:424-462`，载荷 `result.turnControl.stopTurnAfterResult` |
| **Stop hook 拒绝收口** | 外延：文本已持久化后仍可把 turn 重新打开 | `turn-stop.ts:201-217`，上限 `MAX_STOP_HOOK_CONTINUATIONS = 3` |
| **Goal verifier** | 验收：独立模型调用判目标是否达成，未达成则续跑 | `target-completion-verification.ts:41` + `target-continuation-loop.ts:55-83` |
| **anomaly guard** | 只告警不断：注入 `model_anomaly` 提醒 + 发 `ModelAnomalyWarning` 事件 | `turn-tool-warnings.ts:22-79` |

第三条是**与 Neurova 哲学正相反**的一条：Neurova 的 stagnation 判据（回复相似度 ≥0.8 或调用签名重复）触发后是**终止**；参照侧在"看起来停了"的同一时刻，反而去问"你真的完成了吗"，未达成就继续。前者的失败模式是**假完成**，后者的失败模式是**过度续跑**，代价不对称。

`automation_create_limit` 是第一条权柄的一个精巧用法（`turn-tools.ts:427-441`）：定时任务创建触达全局上限后，把本轮**永久切为纯文本**（`state.automationCreateLimitReached`），并**跳过 guide 与 Stop hook**（`turn-stop.ts:176-194`），防止模型用 List/Delete/Create 循环或 Bash 绕过配额。

### 2.4 并发调度：拓扑分层【一手】

`tool/scheduler.ts`。核心是**分组而非全批二选一**：

```
canRunInParallel(tool):  destructive → false
                         concurrentSafe → true / false（显式优先）
                         readOnly → true
                         sideEffectScope === "none" → true
topologicalSort(items) → groupByParallel(按依赖层级) → 组内满 10 再切组
```

执行侧 `tool/executor/batch-runner.ts:70` 遍历 `parallelGroups`：**组间顺序、组内 `Promise.all`**。于是一个混合批次里，只读项照样并行，写项单独成组——代价只在依赖图上。

安全分级是**工具声明的一等字段**：`sideEffectScope` 为 7 元枚举 `none | workspace | git | network | system | session | userInteraction`【转述，`contracts/model/index.ts:453-460`】，另有 `readOnly / destructive / concurrentSafe / riskLevel / needsApproval / alwaysAsk`。

### 2.5 取消与超时【一手（入口）+ 转述（细节）】

- 超时**真的取消**：`abortController.abort(error)`（`tool/executor/timeout.ts:148`）、`linkAbortSignal`（`:206`）。
- **工具时钟可暂停**：等待模型请求排队期间冻结 deadline，退避不冻结（`timeout.ts:19-91`）——避免"排队 60s 被算成工具超时"。
- 取消语义在流式工具上有专门安排：assistant `tool_use` 已进历史后，Stop **不能**在 tool result 创建前直接抛出，必须把 aborted signal 交给 executor，由取消通路为每个 call 生成 `ToolCancelled` 结果，再让 loop 感知（`turn-tools.ts:142-144`）。
- checkpoint 抛出的取消**延后传播**：`deferredCheckpointCancellation` 保证所有 sibling tool result 提交完才抛（`:367-382`、`:420-422`）。
- bash 进程树中断：SIGTERM → SIGKILL 全树，Windows `taskkill /T /F`、POSIX PGID【转述，`adapters/src/exec/node-execution-adapter-process.ts:148-192`】。

### 2.6 审批：真阻塞【转述】

`call-runner.ts:289` `await resolveToolPermission`；broker 的 Promise 只在客户端调 `resolvePermission` 时 settle（`permission/broker.ts:122,128-134`）。**循环不推进，handler 随后真的执行，模型拿到正常工具结果，无 pending 哨兵。** 支持审批时改输入：`decision:"modify"` + `modifiedInput`，改完复校验再执行（`permission-flow.ts:415-430`）。

裁决枚举：静态 `allow | ask | deny`，决议 `allow | deny | escalate | modify`（无 passthrough）。优先级链约 13 级：`plan-transition > requiresUserInteraction > alwaysAsk > yolo > auto > disallowedTools > project deny > project ask > plan > project allow > preapprovals > allowedTools > edit/build 启发`【转述，`permission/service.ts:136-231`】。

**但两条硬伤**（详见 §7）：审批**无限阻塞**（`permissionTimeoutMs` 全仓无赋值），以及 hook 改输入后的授权复用漏洞。

### 2.7 Hooks【转述】

7 事件：`SessionStart / UserPromptSubmit / PreToolUse / PermissionRequest / PostToolUse / PostToolUseFailure / Stop`。`PreToolUse` 跑在权限判定**之前**（`hook-flow.ts:16-47`）。能力：阻断（`decision:"block"`）、改写输入（`updatedInput`）、注入下一步上下文（`additionalContexts`，Stop 侧入真实历史、上限 24k）。基础设施异常 **fail-open**（抛错的 hook 发 `HookRunFailed` 后继续跑）。

### 2.8 工具声明与四级前置校验【转述】

一处注册表（`ToolRegistryImpl`，`tool/registry.ts:30-130`），canonical 参数 schema 为**纯 JSON Schema**（zod 仅用于在上游推导它）。内置 40 个（`tool/handlers/index.ts:76-137`，另 2 条注释退役）。

四级校验全在执行前、全在 `call-runner.ts`：归一化 → JSON Schema（**手写校验器**约 340 行）→ 每工具语义 hook → `resolveInput` 重写；被 hook 或人工改写后**再校验**，输出亦校验。

自我纠错回执是**叙事体**【一手，`tool/input-validation-model-content.ts:12-22`】：

```
<tool_use_error>InputValidationError: read failed due to the following issues:
The required parameter `path` is missing
An unexpected parameter `flie` was provided
The parameter `limit` type is expected as `number` but provided as `string`</tool_use_error>
```

### 2.9 结果预算：声明式三策略【转述】

`ToolResultBudget` 逐工具声明，策略 `inline | truncate | artifact`，默认 100 KB / truncate。超阈落 artifact，模型看到 `Output too large (N KB). Full output saved to: <path>` + **2000 字符**预览（`tool/result-persistence-format.ts:29-42`）。9 个工具声明 `artifact`。

缺口：类型化的 artifact 再取端口存在但**无面向模型的工具消费**，回读靠模型自己 `Read` 那个路径。

### 2.10 Provider 归一与提示缓存【一手】

Provider 差异整个外包给 Vercel AI SDK（`adapters/src/model/model-execution.ts:6-9`：`@ai-sdk/anthropic` / `@ai-sdk/openai` / `openai-compatible`），自研层只做补齐（`strict-tool-schema.ts`、`tool-call-validation.ts`、`streaming-tool-call-assembler.ts` 等）。

缓存侧三条动作：

1. **稳定下发顺序**：`tool/provider-visible-order.ts:1-33` 固定 roster 排序，参照工具名在前、本地工具在后。
2. **锚点在投影之后统一打**：`turn-loop.ts:168-186` 先做 provider-visible 投影再 `applyCacheControl`，注释说明防"raw synthetic entry 抢占缓存锚点"。
3. **子代理刻意不收窄工具目录**：`memory/memory-agent-loop.ts:63-65` 注释——provider 请求必须保留 Main 的真实工具目录，执行权限只在 tool-use 边界收窄。理由是**改工具列表会打爆前缀缓存**。

第 3 条是这轮对标里信息密度最高的一条：它把"权限收窄"从**请求侧**（改目录）搬到了**执行侧**（拦调用），从而同时拿到最小权限与缓存稳定。

### 2.11 持久化与崩溃恢复【一手】

每个 tool call 落三态 part：`persistPendingToolPart`（pending）→ `onBatchStart` 里转 running（带 `time.start`）→ completed/error（带 `time.end`、`output`、`metadata.modelContent` 供冷恢复精确重放），并有 `declarationIndex` 保序、`streamRecoveryAnchor` 作重放锚（`turn-tools.ts:124-140`、`:187-230`、`:302-351`、`:386-410`）。

`declarationIndex` 的存在意味着：**模型声明顺序与执行完成顺序解耦**，展示与重放都按声明位对齐。

### 2.12 子代理与工作流【一手（边界）+ 转述（实现）】

子代理：`Agent` 声明 `readOnly + concurrentSafe + needsApproval:false`，故并发来自 scheduler。递归守卫是**结构性**的——子配置 `subagents:{enabled:false}` → port `undefined` → handler 抛 `ConfigurationError`，深度硬顶 1、`maxTurns` 默认 4。**无成本预算**，只有 120k 输出上限与不活跃看门狗，工具超时 `kind:"none"`。`SendMessage` 对已终止的子代理会**以后台生命周期复活**（`resumed_background`）。

工作流：不是第二条 loop，而是**可持久化、可续跑的阶段驱动器**——`clarify → task_analysis → arch_decompose → env_setup → meta_prompt → exec → final_critic → complete`，`exec` 由图调度器带并发信号量跑（2 loops / frontier 3 / 10 planner runs / 连续 3 错暂停），critic ≤3 轮且**会重开已完成图节点再调度**。

---

## 3. Neurova 侧现状（`c55e1f37`）

### 3.1 循环：递归，无相位状态机

`neurova/agent/loops/openai_loop.py` 两条实现均自/互递归：非流式 `:434`（`return await self._predict_normal(request_params)`，**每轮 1 帧**）、流式 `:742`（`async for event in self._predict_stream(request_params)`，经 `:438` 包装层，**每轮 2 帧**）；`AnthropicLoop` 第三条在 `anthropic_loop.py:101`——注意它**经公有 `predict_step` 自递归**，靠 `_top_level=False` 才不重置轮次计数（`:51-52`），该保护经核对**有效**（我初判"上限恒失效"已证伪）。

**栈深不是风险**（本文第一版把它当风险，见 §9 更正 #7）。实测：`recursionlimit=1000` 下，每轮约 2.03 帧，可撑 **493 轮**；轮内分派链深度 `TC` 线性抵扣（`TC=100` ⇒ 444 轮）。而合法配置上界 `MAX_ROUNDS = 200`（`security/agent_limits_settings.py:34`）⇒ 有效 `_max_tool_rounds = 100` ⇒ **仅占预算约 20%**。全仓 `RecursionError` / `setrecursionlimit` 命中数为 **0**，无历史溢出证据。

同一位置的真实缺陷另有三条，均已入 G1 修正方案：轮次态挂 per-agent 单例（并发会话互相清零预算）、子代理嵌套**无深度上限**（`MAX_ACTIVE_CHILDREN=5` 管广度不管深度）、三份 loop 各有一份终止/预算/门控语义且**已漂移**（Anthropic 侧硬编码 `> 10`、非流式门控 ctx 缺键）。

### 3.2 分派咽喉

`neurova/agent/loops/base.py:72 handle_tool_calls` → `:138 _execute_tool_call_worker` → `native_tool_dispatch.py:35` → `tool_executor.py` 的六臂回退链（workflow 特例 → `workflow:{id}` → ToolEngine → builtin → Skill → ToolRouter → `未知工具`）。前置层为 `PreToolUse` hook → `ToolParamGuard` → `validate_tool_args` → 日期接地 → MCP 持久授权 → `monotonic_guard` → `_governance_precheck` → V3 metacog 硬拦 → 沙箱作用域 → 超时。

参数处理**含别名归一与截断 JSON 括号配平**（`tool_executor.py` 的 `ToolParamGuard`），即能**救回**一次手滑调用而非仅告知——参照侧明确无 per-argument key aliasing。两条默认均需开关开启。

### 3.3 并发：仍是 all-or-nothing

`base.py:142-143`：

```python
use_parallel = len(tool_calls) > 1 and all(
    is_concurrency_safe((tc.get("function") or {}).get("name", "")) for tc in tool_calls)
```

白名单 10 项硬编码（`neurova/agent/tool_coordinator.py:60-71`）：`calculator / memory_search / recall_history / recall_context_span / web_search / web_fetch / file_parse / weather / get_time / time_now`。**任一未声明项混入 → 整轮串行**，含未知工具。

实测覆盖度：**10 / 71 内置工具 = 14%**。名字含 read/search/fetch/parse/list/get_/recall 的 20 个纯读类里只登记 6 个，**`file_read` 不在清单内**（最高频的多读场景整轮串行）。MCP / Skill / `workflow:{id}` 因命名空间不匹配恒判 `False` ⇒ **多路 MCP 检索必然串行**。仓内另有 4 份工具安全清单（并行 / 可重放 `builtin_tools.py:1074` / 桌面审批 `runtime_policy.py:43` / 命令威胁 `tool_guard.py:43`），实测 `_CONCURRENCY_SAFE ∩ _NON_REPRODUCIBLE = ∅` ⇒ **四条不同的轴，不可合并**（反例：`computer_screenshot` 副作用上只读、但抢共享设备故并行轴上须串行）。

### 3.4 门控：`GoalGate` 已实现，但主出口无守卫、goal 零写入

`neurova/agent/gates.py` 有 `DoomLoopGate`、`IterationGate`（`:59`）、`TokenBudgetGate`、`GoalGate`（`:149`）。

关键事实：`openai_loop.py:140` 有注入位

```python
def set_goal_gate(self, goal, completion_check=None, max_rounds=15) -> None:
    """goal 模式：注入 GoalGate（目标达成判定 + 轮次预算）。
    completion_check(goal, ctx) -> (achieved, summary) 由调用方提供（LLM rubric 或显式条件）。"""
```

`GoalGate` 完整可用，GateRunner 的 TERMINATE 在流式与非流式两条路径均已生效。

**但"只差一个 caller"是错的**（本文第一版原话，见 §9 更正 #6）。复验三条路径后确认两个更前置的断点：

1. **门控只在工具轮求值**。非流式在 `openai_loop.py:394-400`（位于 `:374 if tool_calls:` **块内**），
   流式在 `:673-694`（位于 `:641 if pending_tool_calls:` **块内**）；而主出口
   `:437 return response` / `:746-751 yield done` 在块外，**不过任何门控**。
   假完成的定义恰是"停止调工具且目标未达成"，故 `GoalGate` 在语义上无法表达它——
   它今天唯一的能力是**提前终止一个仍在调工具的环**。
2. **`agent._goal` 只读不写**。全仓唯一命中是读取点 `openai_loop.py:678`
   （`getattr(self.agent, "_goal", None) or {}`），零写入点、属性从未初始化，
   缺失被静默降级为空 goal。这正是 `AGENTS.md` 协作红线点名的"只读不写"断点形态。

附带发现（独立缺陷，与 goal 无关也该修）：非流式 ctx 缺 `round_reply`/`round_usage`/`goal` 三键
⇒ **`TokenBudgetGate` 在非流式路径恒不可触发**；且非流式只判 TERMINATE、
丢弃 `INTERRUPT_AND_CONTINUE`（流式在 `:688-694` 会兑现）。另 `_gate_runner`
在 `:99-103` 与 `:124-135` 各装配一遍，是第二份门控清单。

> **命名冲突**：`self_manager_module.py:123` 的 `set_goal` 是**心跳任务**goal，语义无关，
> 新落点不可沿用裸 `_goal` 名。

`IterationGate` 与硬顶读同一配置键不同尺度（`_max_tool_rounds = max_loop_rounds // 2`，`openai_loop.py:256`）。本文第一版据此判"任意配置不可达"，**该结论过强**，机器复算为 `scaled_sparse`（合法域内极少数配置可让门控出声），见 §9。

### 3.5 治理与审批：ASK 仍不阻塞

`neurova/tool_executor.py:1648-1660`：

```python
if verdict.decision == GovernanceDecision.ASK:
    approval_id = self._create_approval_request(tool_name, params, verdict)
    return {"success": False, "pending_approval": True, "approval_id": approval_id, ...}
```

Python 侧无任何 await 原语（`approval_manager.py` 里两串 `await fetch(...)` 是嵌在 HTML/JS 模板里的前端代码）。消费者只有 `api/endpoints/console.py` 与 `governance.py` 两个端点。即**模型收到的是一个失败的 tool result，会在缺人类裁决的状态下继续推理**。

### 3.6 Provider：原生协议工具通路已接通

`neurova/llm/providers/tool_transport.py`（新，126 行）为请求侧唯一转换点，其文档明确记录此前的故障形态："配了原生 provider，函数调用能力直接消失，没有日志、没有报错、没有降级提示，运维侧看到的表象是『模型就是没用工具』"。

现状：`anthropic_client.py:96-101` 真发 `tools` + `tool_choice`；`llm_client.py:259-260` 使 `tool_choice` 不再空转（先过 `compat.supports_tool_choice` 声明位）；响应侧 `protocol_thinking.py:61-68` 经 `ToolCallParser` 归一为 `toOpenAIToolCalls`；`base.py` 补发声明 `tool_calls` 的 assistant 块，注释点名严格校验网关的 `400 inference request is invalid`（商汤 400001 实测）。

转换复用 `tool_layers/openai_schema.py` 的 `ToolSchemaConverter` / `ToolCallParser`——即本文第一版误判为"死码"的模块。

### 3.7 大输出：双源已收口为职责切分

`neurova/agent/tool_output_ref.py` 文档体现在写明三条收口决定：体量折叠的**单源**是回环处的 `apply_offload_policy`（保住诊断）；本层只负责**成功结果**的引用化；成败判据不自持，由咽喉的 `ToolExecutor._result_is_success`（全仓唯一判据）传入。

### 3.8 经验反哺：本仓差异化所在，但部分休眠

`on_tool_executed` 在 `finally` 里向 6~7 个 sink 同步扇出：`tool_weights.update_weight`、`self_model_engine.record_tool_event`、`metrics`、`tool_memory.record_tool_usage`（L1/L2/L3 肌肉记忆晋升）、`tool_lifecycle.touch`、`notify_tool_result` → 熔断器。另有 `_metacog_gate_check` 可按 `avoid_tool` 课程**硬拦**工具（默认关），与 `crystallized_experience_manager` 检索侧。

---

## 4. 逐维比对矩阵

| 维度 | Neurova `c55e1f37` | 参照侧 | 判定 |
|------|--------------------|--------|------|
| 循环形态 | 递归 `openai_loop.py:432/:741`，无相位机 | 迭代 + `TurnMachine` 相位守卫 | **落后** |
| 收口判据 | "模型不调工具即完成"，硬顶 10 轮 | 四把权柄（工具停/hook 续/goal 验收/异常告警） | **落后（但骨架已在）** |
| 并发 | all-or-nothing，10 项白名单 | 拓扑分层 + 声明式安全字段 | **落后** |
| 超时/取消 | 一刀切转后台（主路不吃已有杀灭原语）；`to_thread` 从外部不可取消 | abort 贯穿 handler + 可暂停时钟 + 取消延后传播 | **执行层落后，意图层领先**（见 §6 第 7 条） |
| 审批 | 返回 pending 当失败结果 | 真阻塞 + 可改输入 | **落后（它另有无超时硬伤）** |
| 工具声明 | 5~6 面并行，含 4 处 serializer | 一处 registry + 四级校验 | **落后** |
| 参数修复 | 别名归一 + 截断 JSON 配平（默认关） | 无 key aliasing，仅告知 | **领先** |
| Provider 归一 | `tool_transport.py` 已接通 | 外包 AI SDK | **已追平** |
| 提示缓存 | 不再重排；主动锚点 0 | 稳定 roster + 投影后打锚点 + 执行侧收窄权限 | **半追平** |
| 大输出 | 职责切分完成 | 声明式三策略 + 2000 字预览 | **追平（它多 artifact）** |
| 崩溃恢复 | 内存 dict 就地 mutate | 三态 part + recovery anchor | **落后** |
| 经验反哺 | 6~7 sink + 硬拦位 | **纯观测，明确不改业务语义** | **显著领先** |
| 子代理成本 | SwarmManager 四道闸门（默认关） | 无预算 | **领先（设计）** |
| 沙箱 | 真通路 + 新 `code_sandbox.py` | 字段挂着、无消费者、注释称已移除 | **领先** |
| 测试 | 唯一测试根 + 守卫网 + 双台账 | 2.4 万行核心 **0 测试** | **显著领先** |

---

## 5. 缺口台账 G1–G8 复验状态

| 编号 | 缺口 | 第一版判定 | `c55e1f37` 复验 | 证据 |
|------|------|-----------|----------------|------|
| **G1** | 递归 → 迭代 + 相位守卫 | 开放（栈深风险） | **仍开放，但风险理由已更换** | 实测每轮约 2.03 帧、`recursionlimit=1000` 下可撑 **493 轮**，而合法配置上限 100 轮 ⇒ **栈深非风险**（全仓亦无 `RecursionError`/`setrecursionlimit` 痕迹）。真实缺陷在同一位置：轮次态挂 loop 实例（per-agent 单例）⇒ 并发会话互相清零预算；子代理嵌套**无深度上限**。见 §9 更正 #7 与 [`../04-plans/2026-09-26-tool-loop-iteration-repair-plan.md`](../04-plans/2026-09-26-tool-loop-iteration-repair-plan.md) |
| **G2** | 完成性验收缺失 | 开放（需造能力） | **仍开放，且根因不在缺 caller** | 见 §9 更正 #6。`GoalGate`(`gates.py:149`) 代码完整，但门控只在**工具轮**求值，主出口（模型不再调工具）不受任何守卫；`agent._goal` 全仓仅 1 个读取点、0 个写入点。→ 修正方案另见 [`../04-plans/2026-09-26-goal-gate-wiring-repair-plan.md`](../04-plans/2026-09-26-goal-gate-wiring-repair-plan.md) |
| **G3** | 并发 all-or-nothing | 开放 | **仍开放，量化后比原描述更糟** | `base.py:142-146` 未变；白名单 10/71 = **14%**、`file_read` 缺席、MCP/Skill/workflow 恒不可并行。→ 修正方案 [`../04-plans/2026-09-26-tool-batch-parallelism-repair-plan.md`](../04-plans/2026-09-26-tool-batch-parallelism-repair-plan.md) |
| **G4** | 超时不取消 | 开放（需新造底层能力） | **仍开放，但成本被我低估两次** | 三个原语**都已存在**：跨平台进程树杀灭 `exec_sandbox._kill_process_tree:157`（POSIX 进程组 SIGKILL / Windows `taskkill /T /F`）、会话终止 `shell_sessions.terminate:142`+`kill_all:300`、取消意图持久化 `agent_run_store.request_cancel:187`。缺的是接线与一处协作协议：① 主路 `run_code`/`git`/`exec_command`/`computer_shell` 不吃该原语；② `kill_all` **生产零调用方**（仅测试）；③ **`to_thread` 从外部不可取消**（`tool_executor.py:2604` 的既定规矩带来此后果），故必须下沉协作令牌；④ `is_policy_denial` 不认 `cancelled` ⇒ 用户取消被计为工具失败并经 `MIN(success)` 永久粘死；⑤ 取消的后台任务不投 `_pending_hints` ⇒ 终态进了台账没进反馈环。→ 方案 [`../04-plans/2026-09-26-tool-cancellation-repair-plan.md`](../04-plans/2026-09-26-tool-cancellation-repair-plan.md) |
| **G5** | 审批不阻塞 | 开放 | **仍开放** | `tool_executor.py:1648-1660` 未变 |
| **G6** | 原生协议工具静默失效 | 开放（3 子项） | **已闭合** | `tool_transport.py`(新) + `anthropic_client.py:96-101` + `llm_client.py:259-260` + `base.py` assistant 块；提交 `2028e43d`（Issue #177） |
| **G7** | 每轮重排 tools 打爆缓存 | 开放（一行止血） | **半闭合** | `orchestrator.py:1024` 重排已删、权重降为会话内冻结的裁剪优先级（`_toolClipOrder`）；主动 cache marker 仍 0 |
| **G8** | 死码与双源 | 开放（无台账） | **已被机器接管** | 新增 `scripts/ci/toolLoopDeadlines.txt` + `tool_loop_deadline_ledger.py`（T-01，Issue #175），并多出"阈值可达性"判据轴；条目均 `待处置` |

另有一条第一版列为"落后"的**已闭合**：大输出双源折叠（见 §3.7），收口方式是职责切分而非合并，且顺带把成败判据归到唯一来源。

### 台账的形态值得单独说明

`toolLoopDeadlines.txt` 行格式为七列：`符号 | 种类 | 判据类 | 阈值可达性 | 引用点数 | 处置 | 依据`。其中**两轴均为机器算、不得人填**：

- **判据类**（四值）：`absent / no_consumer / self_loop / consumed`，由 AST 可达性复算，台账值与实测不符即报红。
- **阈值可达性**（五值）：`not_a_threshold / unbound / single_source / scaled_unreachable / scaled_sparse`，回答"阈值的**值**在合法配置域内够不够得到"，需三条证据同时成立（门控构造直绑配置键、同键存在 `// d` 的更小尺度守卫、合法域内可达性可判定）。

**台账值与实测不一致即红**——这是把"人改台账去迎合实现"这条路直接堵死的设计。当前在册条目包含 `UnifiedToolRegistry`(`no_consumer`)、`CostTrackingMixin`(`no_consumer`)、`ToolExecutionPipeline`(`no_consumer`)、`IterationGate`(`consumed / scaled_sparse`)、`set_goal_gate`(`no_consumer`)、`tool_choice`(`consumed`)、`MAX_TOOL_CALL_ROUNDS`(`no_consumer`) 等 20 条。

---

## 5.1 第三次复验（基线 `008a3e2a`，距 §5 又 179 提交 / `neurova/` +6603 −3142）

**结论：G1–G5 全部闭合，G8 处置过半。§5 的"真实剩余 5 条"已失效，以下为当前事实。**
按本仓惯例保留 §5 原文不改写，本节为增量。

| 缺口 | §5 判定 | 现判 | 落地证据（均为本次亲验） |
|------|---------|------|------------------------|
| **G1** | 仍开放 | **已闭合** | 递归归零：`openai_loop.py` 内 `await self._predict_normal(` / `self._predict_stream(` **0 命中**，代之以 `while True:`（`:536`、`:736`）。`self._tool_rounds` 残留 **0 处**；`TurnRunState` 新文件 142 行，三条 loop 全改用（`anthropic_loop.py:54` `TurnRunState.forTurn(`）。`_top_level` 参数已删（仅存无关的 `_split_top_level`）。`assertRoundInvariant` 落 `turn_run_state.py:92` |
| **G1-D 深度** | — | **已闭合** | `swarm.py:164` `MAX_SUBAGENT_DEPTH` + `:220-224` 超限走 **既有 `_rejection` 通道**（`SUBAGENT_DEPTH_EXCEEDED`）。**实现优于方案**：深度用 `ContextVar`（`:46 _subagentDepthVar`）而非我提议的"塞进 `TurnRunState`"——因为 `spawn` 要跨 `chat()` 边界，state 传不过去 |
| **G2** | 仍开放（主出口无守卫） | **已闭合** | `base.py:71 evaluateLoopExit` + `LoopExitDecision{done,stop,resume}`，`:85` 注释即方案原话（"ctx 带 `isLoopExit=True`…假完成正是在这里才可被识别"）。**两条路径均调用**：`openai_loop.py:691`、`:1101`。`gates.py:160-168` GoalGate 出口分支。新文件 `loop_goal.py`(93) / `goal_verifier.py`(117) / `sub_session.py`(41) |
| **G2 goal 闭环** | 只读不写 | **四环齐** | 写：`chat_pipeline.py:619 set_turn_goal(ctx.metadata["goal"])`（= 方案 D-2 的 ①）；读：`base.py:112`；反馈：`set_turn_goal_verdict`（`base.py:117`）+ 续跑计数；再消费：`chat_pipeline.py:2867-2870` 取 goal+verdict。**命名未沿用裸 `_goal`**（方案 RC-2 的冲突警示被采纳） |
| **G3** | 仍开放 | **已闭合** | `_CONCURRENCY_SAFE_TOOLS` **全仓 0 命中**（方案 M2 要求的"物理消失"达成）。`core/tool_capability.py`：`WriteScope:56`、`isParallelEligible:200`、`planToolBatches` 被 `base.py:399-403` 消费。MCP 能力声明走 server 配置（`_resolveMcpToolCapability`），符合方案 D-4"不默认信任第三方" |
| **G4** | 成本被我低估 | **已闭合** | `core/cancel_token.py` `CancelToken` 存在。`tool_coordinator.py:225-230` 的注释把方案 RC-2 **原样写进代码**："外层取消对已进 `to_thread` 的调用无效…只有置位令牌才能让 worker 注册的进程杀灭回调真正发出…本层不吞取消"。三态处置 `resolveTimeoutDisposition:154` + `_reapCancelled`，宽限期常量有界。`kill_all` 接进 `api/app.py:1161`（含 `wait_for` 超时），`:1152` 注释直引"实现完整、生产侧零调用方"。`governance.py:64-76` 追加 `cancelled` 键（注明"与上述六键完全同构的决策"）。`_observe_background` 取消分支补投 hint，注释标 **"断链修复（G4-RC6）"** |
| **G5** | 仍开放 | **已闭合，且比方案更完整** | `security/approval_relay.py`(144) 补上跨请求通路——其文档串记下根因：`register_notification_callback` 生产侧零注册方，`_send_approval_result` 广播的是空列表。咽喉 `tool_executor.py:1726-1756` 真阻塞：**有界** `wait_for(waiter, budget)`（正是方案对参照侧"无限阻塞"硬伤的防範），超时/中断**均注销登记**并给出理由（陈旧登记会让两边都不执行，"比不阻塞更糟的静默丢单"），批准则由本调用在完整管线内执行（`return None` 续跑），拒绝回 `approval_denied` 结构化裁决 |
| **G8** | 已被机器接管 | **处置过半** | 台账 28 条：**11 已删除 / 13 已接线 / 4 待处置**。物理删除 `cli_tool.py` −414、`tool_logger.py` −286、`unified_registry.py` −238 及其 3 个测试文件。`IterationGate` 双尺度经 `T-04`（Issue #310）收口，`openai_loop.py:196-201` 注释点名"同键两尺度正是被判 `scaled_sparse` 的成因"，GoalGate 改绑独立键 `goal_max_continuations` |

### 仍然开放的（截至 `008a3e2a`）

1. **G7 后半**：主动打 cache marker 仍 **0 命中**（`cache_control`/`prompt_cache`）。前半（停止重排）早已闭合。
2. **崩溃恢复**：三态 tool part / `declarationIndex` / recovery anchor 形态 **0 命中**（方案优先级表第 8 项，尚未立项）。
3. **台账 4 条待处置**：`TokenBudgetGate`(consumed/single_source)、`notify_tool_result`、`get_pipeline_observers`(均 consumed)、`ctx_snapshot`(self_loop)——**四条都是存活符号，等的是裁定而非清理**。
4. **G4 方案文档未入库**：`docs/04-plans/2026-09-26-tool-cancellation-repair-plan.md` 仍是未跟踪状态（`4865e8c6` 只带了 G1–G3 + 本文）。代码里已出现 `G4-RC6` 这样的引用，**文档不在库里会让这个引用悬空**。

### 实现优于本目录方案的两处（引用方案前必读，否则会照做过期建议）

1. **G2**：本目录 `../04-plans/2026-09-26-goal-gate-wiring-repair-plan.md` 把"补一个 `set_goal_gate` 的 caller"当作落地动作。**真实实现走了更好的路**：GoalGate **进默认装配**（`openai_loop.py:212-222`），续跑预算绑独立键 `goal_max_continuations`。
   ⇒ **`set_goal_gate` 无生产调用方是设计结果，不是断点**——不要去"补 caller"，台账里那条 `no_consumer` 也不该按"未接线"处置。**该方案文档的 §3/§5 相应段落已过期。**
2. **G5**：本方案 §1/§5 把它记作"ASK 不阻塞"。**真根因更深一层**：审批记录里**没有回投地址**（metadata 只有 tool_name/params/governance），而批准发生在另一个 HTTP 请求里，结果无路送回原调用——所以"阻塞"只是这条断链的表现。
   ⇒ 只按"加个 await"去修，会造出一个等不到结果的死等。落地是四断点（回投地址 / `approval_relay` 由 manager 首次构造接入 / `approval_wait_seconds` 默认 **0** / 复用 `_pending_hints` 渲裁决），并靠 `hasApprovalWaiter` 保证有人在等时端点**不重放**（防双执行）。
   **注意**：HTTP 活体三条**尚未验证**（缺本地凭据）——勿以单测全绿替代教义第 4 条。
3. **G3 的收益判据按本方案 §10.1 执行后为 `no_data`，未否证**（成因是版本差：直方图指标只在较新版本存在，而承载真实流量的实例仍跑改造前代码 ⇒ 序列发不出来；**不可拿合成流量替代**）。
   一次真实驱动量到 `memory_search` 冷路径 avg **991ms**（热 83ms，**双峰高方差**）——推翻"本地读都是几毫秒、收益可忽略"的早期估法。修正方向：收益按工具分布极不均匀，判据应取**逐工具耗时门槛**（avg/P50 ≥200ms）而非统一频次占比。
   另记一处**待收新双源**：7 个工具声明 `concurrentSafe: True` 却因 `writeScopes` 含共享作用域被推导判为不可并行（`computer_screenshot`/`computer_dom_snapshot`/`computer_som_snapshot`/`browser_read`/`browser_dom_read`/`canvas_read`/`canvas_list_nodes`）——**行为对，但声明与推导信号相反，只看声明会误判为已并行**。

### 本轮最值得记下的一条方法论

四份方案里我给的**判据与约束被采纳、但落点与根因判断有多处被实现纠正**：深度与 goal 都改用了 `ContextVar`，因为要跨 `chat()` 边界，`TurnRunState` 传不过去；`sub_session.py`(41) 说明 §10 里我"倾向不抽"的那个共享抽象最终被抽了。
⇒ **方案的价值在判据与约束（哪里必须有守卫、什么必须单源、什么不许另造、默认必须保守），不在我挑的落点、也不在我挑的根因表层。** 下次写方案应把落点明确标为"待实现层决定"，并对每条"根因"追问一次"它又是哪条断链的表现"——本次三处纠正（G2 落点、G5 根因、G3 判据口径）全是这个形状。

---

## 6. Neurova 领先面（勿妄自菲薄）

1. **工具 → 经验 → 再调用的学习闭环，参照侧完全没有对应物。** 其 `recordToolUsageFromResult`（`runtime/methods/turn-tool-usage.ts`）是纯 SQLite 观测，注释写死"观测失败绝不能改变 Agent 业务语义"——无权重、无退化、无课程生成。本仓有 6~7 路 sink + 硬拦位 + 结晶经验检索。**但需诚实标注：`metacog_gate_enabled` 与肌肉记忆晋升默认关，领先项部分休眠。**
2. **测试与判据基建差距是数量级的。** 参照侧 2.4 万行核心 0 测试、单提交无历史；本仓有唯一测试根、双域死线台账（上下文域 + 工具/loop 域）、CI 棘轮、尺寸门禁。§7 会说明这意味着什么。
3. **隔离执行面**：本仓有真沙箱通路，且本批新增 `sandbox/code_sandbox.py`(+392，`CodeSandboxSession.execute` + `_Enforcer` + 显式 `SandboxBackendUnavailable`)；参照侧 `sandbox:{enabled}` 无消费者、注释称已移除。
4. **参数级修复能力**（§3.2）：救回而非告知。
5. **蜂群成本治理设计**（budget / 429 冷却 / 每模型并发 / 派生间隔），参照侧子代理无任何预算闸门。
7. **取消意图持久化**：`agent_run_store.request_cancel` 把取消写进 `cancel_requested` 列，供执行侧、审计、**重启对账**（`agent_run_store.py:12,50,187,238`）；取消端点还补了鉴权与会话归属校验，并显式处理"新会话首轮未落盘时不得打断停止按钮"（`console.py:1120-1128`）。参照侧只有一只内存 `AbortSignal`——进程重启即失忆。这是"**意图层**领先、**执行层**落后"（G4）的罕见组合，改造时**不许绕过它另起一套取消状态**。

6. **上下文池与召回体系**（池化、按需回读、溢出摘要、evicted 召回）比其"闲置 60 分钟 + 比例阈值 microcompact"层次更丰富；且本批上下文域净删 `context_compressor.py` −655、`context_facade.py` −339。

---

## 7. 参照侧自身缺陷与共性难点

### 7.1 它的硬伤（不可当作"成熟实现"照抄的部分）

- **审批无限阻塞**：`permissionTimeoutMs` 只被读三处、**全仓无赋值** → 无定时器 → 阻塞到用户回答或本轮 abort。它把本仓的"从不等待"换成了"可能永远等"，是同一枚硬币两面。
- **授权复用漏洞（审批绕过类）**：hook 改过输入后，复判**只在 `validateInput` 失败时**触发（`permission-flow.ts:248-266`）。一次 schema-valid 的 `file_path` 改写会沿用改写前那份授权——**改路径不需要非法，只需要合法**。
- **无成本闸门**：主循环无轮次顶 + 子代理无预算 → 单靠 goal verifier 与 anomaly 告警不足以止损烧钱。
- `mode.auto` 是 "not implemented" 的 deny 桩，且写了两处；`Write` 会静默满足 `Edit` 规则；规则匹配只取单一 subject 字段，忽略其它 path 键；`escalated` 把 "ask" 与 "escalate" 混为一谈。
- 幻觉工具名无 did-you-mean、无模糊匹配，且 `Tool not found` 标 `recoverable:false`、不套 `<tool_use_error>` 信封。
- artifact 再取无面向模型的工具消费者。

### 7.2 共性难点：工具安全属性天然长出第二份副本

本仓 G8 的那类毛病，参照侧**同样有**，且形态高度相似：

| 双源形态 | 参照侧落点 |
|---|---|
| 同一 7 元枚举抄两遍 | `contracts/tools/contract.ts:7-14` vs `contracts/model/index.ts:453-460` |
| 每工具安全事实 metadata/permission 双写 | `tool/types.ts:70-78` vs `contracts/tools/contract.ts:88-93`；`handlers/read.ts:467-478` 与 `:491-500` 逐字重复 |
| 名字白名单与声明字段冗余且**已分叉** | `scheduler.ts:233-243` vs `permission/service.ts:559-573`（前者缺 Agent/Task） |
| 两套 schema 表示靠 377 行对账 | `input-validation-model-content.ts:74-166` |
| 死名 roster | `provider-visible-order.ts:1-33` 中 9 个名字全仓零命中 |
| 退役后残留引用 | `tool/handlers/index.ts:80` `ApplyPatch` 注释退役但 `compat.ts:9` 仍留别名映射 |

**由此得到一条判断**：这类漂移不是"谁纪律差"，而是**这个抽象层的固有引力**。真正的差异化不在"没有双源"，而在"双源会被机器拦住"。参照侧 0 测试，这些分叉无人拦、也拦不住；本仓的双台账正是它不具备的那一环。**这个优势的价值高于任何单条功能缺口，应优先守住。**

---

## 8. 优先级与分批建议

以下每条都须按本仓独立设计落地，参照侧只作"这件事可实现"的证据。

| 序 | 项 | 为什么排这里 |
|----|----|------------|
| **1** | **G2 出口求值点 + goal 写入面** | 最要害：假完成会被当成功喂进经验反哺，污染下游输入。**但成本被本文第一版严重低估**——根因不是缺 caller，而是①主出口不过任何门控、②`agent._goal` 零写入点。详见 §9 更正 #6 与修正方案文档。 |
| **1b** | **G2 前置片：两条路径门控不对称（非流式 `TokenBudgetGate` 恒不可触发）** | 从 G2 里拆出来的**独立现存缺陷**，纯重构无新能力、可独立回退。与"预算失控"直接相关，建议无论 G2 是否推进都先落。 |
| **2** | **G5 审批真阻塞** | 用户可感知的正确性问题。落地时**必须同时定死超时语义**（参照侧就是漏了这个变成无限阻塞），并把"授权后输入被改写须复判"当设计约束而非补丁（§7.1 那条漏洞）。 |
| **3** | **G3 声明式并行分组** | 把安全分级提为工具声明一等字段，替掉 10 项白名单与一票否决。两处**不要照抄参照侧**：其 `dependsOn` 生产侧硬编码 `[]` ⇒ 拓扑排序对工具轮是装饰；其同类清单也写两份且已分叉。MCP 默认串行（不默认信任第三方）。 |
| **4** | **G4 取消下沉与超时分派** | 原话"唯一必须新造底层能力"已撤回（§9 更正 #8）——进程树杀灭、会话终止、取消意图持久化三件都在仓里且已单源。真正要新造的只有一件：**协作式取消令牌**，因为 `to_thread` 从外面取消不了。另两条（`cancelled` 计入失败、取消不投 hint）是语义漏判，改动极小。含"取消不得吞掉 sibling tool result 提交"与可暂停时钟两条子约束。 |
| **5** | **G1 轮次态归属 + 子代理深度上限** | **判据已从"栈深"换成"状态归属"（§9 更正 #7）**。栈深实测非风险，故不再作为动机；但轮次态挂 per-agent 单例、子代理嵌套无上限是真实缺陷。其切片 A 与 G2 的 C1 是同一动作，**必须合流不可并行改两处**。 |
| **6** | **G8 处置已登记的 `待处置` 条目** | 判据已建，欠账在台账里排着，**不需另列清单**——直接按台账推进即可。 |
| **7** | G7 剩余半条（cache marker） | 是否值得取决于服务商实际计费口径。建议先测不改。 |
| **8** | 崩溃恢复（三态 part + recovery anchor） | 新维度，第一版未列。价值在本仓多会话并发下丢上下文的代价，但工程量独立且大，排在缺口清偿之后。 |
> **顺序补充**：G1 修正方案主张把它的**切片 A（`TurnRunState` 抽取）提到最前**，因为它与上表 1b 是同一动作、且是 G2 出口守卫与子代理深度守卫的共同前置。故本表的 1..8 是"缺口维度"排序，不是"落地批次"排序——批次以两份修正方案的 §6 为准。


---

## 9. 本文的自我更正记录

保留错误以约束后续判断，均已在正文按更正后结论书写：

| # | 第一版结论（依据 `69d7f0dc`） | 更正 | 错因 |
|---|---|---|---|
| 1 | "`tool_layers/openai_schema.py` 整文件死码" | 其 `ToolSchemaConverter` / `ToolCallParser` 现被 `tool_transport.py`、`protocol_thinking.py` 消费 | 把**预置但未接线的正确抽象**当成死码。这类落点的正确处置是接线，而本仓正是这么做的。 |
| 2 | "`IterationGate` 对任意配置都不可达" | 机器复算为 `scaled_sparse`（合法域内极少数可达） | 只做了 `n//2 < n` 的算术推断，未穷举合法配置域，也未看流式路径的门控检查次序。**可达性判断应交给台账器械，不应由人算。** |
| 3 | 参照侧"32 个核心工具" | 实为 40 个内置；roster 32 名中 9 个全仓零命中 | 从排序 roster 反推工具集，而该 roster 本身含死名 |
| 4 | 暗示"参照侧单一事实源、本仓多源" | 参照侧双源分列 6 处（§7.2） | 未下钻其声明层即对比 |
| 5 | 大输出"两套平行落盘机制属双源缺陷" | 已收口为职责切分（成功结果引用化 vs 体量折叠，且成败判据归一） | 取证时点早于该收口 |
| **6** | **"G2 成本降级为纯接线，只差一个 caller"（§5/§8 第一版）** | **G2 仍开放，且加 caller 不解决问题**：门控只在工具轮求值、主出口无守卫，`agent._goal` 零写入点 | **只看了"能力是否存在"（`GoalGate` 代码完整 ⇒ 乐观），没看"求值点覆盖到哪条分支"。** 教训：判断一条链是否接通，必须从**触发条件所在的分支**反推，而不是从组件齐不齐正推。同类风险见 G6/G7——那两条我判"已闭合"，依据是文件与行号存在，**同样没验到分支覆盖**；已在 §8 保留其闭合判定但标注为待活体自证。 |
| **7** | **"G1 的风险是栈深度，递归 ≈ 轮数即隐患"（§3.1/§5/§8 第一版）** | **栈深非风险**：实测每轮 2.03 帧、可撑 493 轮，合法上限 100 轮仅占预算 20%，且全仓无 `RecursionError` 痕迹。真实缺陷改为轮次态归属错误 + 子代理无深度上限 + 三份语义漂移。顺带证伪了本方案初稿的子假设"`anthropic_loop` 经公有 `predict_step` 递归 ⇒ 上限恒不触发"（`_top_level=False` 保护有效） | **未测量即定性**——把"结构不优雅"直接写成了"运行风险"。这是本节记录的方法论毛病**第三次**出现（#1 看组件齐不齐、#6 看分支覆盖、#7 有无实测），已固化为纪律：**凡"某机制会失效/会出事"的断言，必须先给出量或找到反证参数** |
| **8** | **"G4 是唯一必须新造底层能力的一条"**（§8 第一版） | 进程树杀灭、会话终止、取消意图持久化**三件都在仓里且已单源**；真正要新造的只有协作式取消令牌一件，另两处是语义漏判（`cancelled` 未入 `is_policy_denial`、取消不投 hint） | 同一毛病的**第四次**出现（#1 组件齐不齐、#6 分支覆盖、#7 有无实测、#8 能力存在性）：**没查"该能力是否已存在"就按"缺失"定级**。"缺口"与"未接线的已有能力"是两类工单——后者成本低一个量级、评审强度也不该相同 |
| **9** | **G5 记作"ASK 不阻塞"；G2 方案主张"补一个 `set_goal_gate` caller"** | ① G5 真根因是**审批记录里没有回投地址**（metadata 只有 tool_name/params/governance），"不阻塞"只是断链表现；② 真实实现把 GoalGate **进默认装配**（`openai_loop.py:212-222`），`set_goal_gate` 无调用方是**设计结果而非断点**——已入库方案的 §3/§5 相应段落过期 | 同一毛病的**第五次**出现，形态也升级了：这次不是漏看分支或漏测量，而是**把"某 API 没被调用"直接当成"缺接线"**，没先问"其职责是否已被别处单装配点覆盖"。判据：**符号被判 `no_consumer` 前，先问它的职责是否已由别处覆盖**，再决定补 caller 还是改台账口径 |

---

## 10. 附录：复验命令

```bash
# —— 参照侧完整性核验 ——
find zcode-ref/apps/zcode-cli/packages/core/src -name "*.ts" | xargs wc -l | tail -1
find zcode-ref/apps/zcode-cli/packages/core -name "*.test.ts" | wc -l        # → 0

# —— 参照侧关键机制定位 ——
# 循环主体 / 状态机 / 调度 / 收口 / 缓存
sed -n '43,219p' zcode-ref/apps/zcode-cli/packages/core/src/runtime/methods/turn-loop.ts
sed -n '85,205p' zcode-ref/apps/zcode-cli/packages/core/src/tool/scheduler.ts
sed -n '157,237p' zcode-ref/apps/zcode-cli/packages/core/src/runtime/methods/turn-stop.ts

# —— Neurova 侧缺口逐条复验（对准 c55e1f37）——
grep -n "use_parallel\|is_concurrency_safe" neurova/agent/loops/base.py       # G3
grep -n "await self._predict_normal\|_predict_stream(request_params)" neurova/agent/loops/openai_loop.py  # G1
grep -n "class GoalGate" neurova/agent/gates.py; grep -n "def set_goal_gate" neurova/agent/loops/openai_loop.py  # G2
sed -n '1646,1662p' neurova/tool_executor.py                                   # G5
grep -rn "cache_control\|prompt_cache" --include=*.py neurova/ | grep -v test   # G7 剩余半条
grep -vE "^#|^$" scripts/ci/toolLoopDeadlines.txt | cut -d'|' -f1,3,4,6         # G8 台账现状

# —— 台账守卫自证 ——
# 工具/loop 域（G8 对应）
.venv/Scripts/python.exe -m pytest tests/unit/tools/test_tool_loop_deadline_ledger.py \
    tests/unit/tools/test_tool_loop_deadline_disposal.py -q
# 上下文域（§2.2 rapid-refill 之外，G7/G8 形态的 originating 域）
.venv/Scripts/python.exe -m pytest tests/unit/context/test_context_deadline_disposal.py -q
```

---

*本文取证于 2026-09-26，两侧代码均可能继续演进。任何条目被引用作决策前，按 §10 命令对准当前 `HEAD` 复验。*
