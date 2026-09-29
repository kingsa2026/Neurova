# G2 修正方案 —— 目标达成验收链（GoalGate 接线）

> ## 状态更新（2026-09-30 对齐至 `da843611` + `189fc321`）
>
> **本文是立项目击与判据来源，不是现状描述。** 正文中"仍开放/待落地"的判定已被实现取代：
>
> | 缺口 | 现状（逐条核实） |
> |---|---|
> | G1 递归→迭代 | 已闭合：`openai_loop.py`/`anthropic_loop.py` 自递归与 `_top_level` 归零；轮次态随调用传递；子代理深度上限有守卫用例 |
> | G2 出口验收 | 已闭合，且形状优于本文方案：**GoalGate 进默认装配**（`openai_loop.py:212-222`），出口求值点 `evaluateLoopExit`（`base.py:71`，ctx 带 `isLoopExit`）流式与非流式两路都接；续跑预算绑**独立配置键** `goal_max_continuations`——正是本文 §4.4 要求的单源约束。故 `set_goal_gate` 无生产调用方是设计结果，不是断点 |
> | G3 并发 | M1–M4 与逐工具裁决已落地（71/71）；收益判据仍 `no_data`（未否证） |
> | G4 超时即取消 | 已闭合：`TimeoutDisposition.ABORT`（`tool_coordinator.py:245`）返回 cancelled 形态并被 `is_policy_denial` 认作决策 |
> | G5 审批闭环 | 本文四断点链已由 `189fc321` / MR #339 落地；HTTP 活体三条未验 |
> | G7 缓存 | 重排已停；主动 cache marker 仍缺 |
> | G8 台账 | 15 条已处置，1 条为反向控制条目（标签口径 nit） |
>
> 引用本文行号前请对准当前 `HEAD` 复核——正文写于 `c55e1f37`，此后 loop/tool 轴有 138 个提交。


> 立项时间：2026-09-26 · 取证基线：`c55e1f37` · 关联缺口：对标文档 §5 G2
> 关联台账：`scripts/ci/toolLoopDeadlines.txt` 中 `set_goal_gate`(`no_consumer`)、
> `GoalGate` 相关条目 · 上游审计：Issue #175（工具/loop 死线台账 T-01）
>
> **本方案取代对标文档 §5/§8 中"G2 成本降级为纯接线"的判定。** 该判定有误，
> 误因与本方案 §1 即是要纠正的内容，已同步登记到对标文档 §9。

---

## 0. 一句话结论

**不是缺一个 caller。** 缺的是"模型不再调工具"这一出口的**求值点**，以及 goal 的**写入点**。
`GoalGate` 的代码是完整的，但它被挂在一个**永远不会为"假完成"发声的位置**上——
今天给它加 100 个 caller，假完成仍然一次都不拦。

---

## 1. 根因（四条，均已逐行核实）

### RC-1 · 出口无求值点：门控只在工具轮被调用

"模型不再调工具"是循环的主出口，而两条路径都在 `if tool_calls:` **块内**求值门控、
块外直接收口，出口一行都不过门：

| 路径 | 门控求值位置 | 无工具调用出口 | 出口是否受守卫 |
|------|-------------|---------------|---------------|
| 非流式 `_predict_normal` | `openai_loop.py:394-400`（在 `:374 if tool_calls:` 内） | `:437 return response` | **否** |
| 流式 `_predict_stream_once` | `openai_loop.py:673-694`（在 `:641 if pending_tool_calls:` 内） | `:746-751 yield {"type":"done"}` | **否** |

由此得到 `GoalGate` 的**实际能力边界**（`gates.py:149-189`）：

```python
if achieved:                     → TERMINATE   # 唯一新增能力：提前止损一个仍在调工具的环
if rounds >= self.max_rounds:    → TERMINATE   # 轮次预算
else:                            → BYPASS      # 未达成时"继续"＝状态 quo，且只在工具轮有意义
```

**判据**：假完成的定义是"模型停止调用工具 *且* 目标未达成"。停止调用工具时门控根本不被调用，
故 `GoalGate` 在语义上无法表达"未达成 → 续跑"。**加 caller 不改变这一点。**

### RC-2 · goal 只读不写（`AGENTS.md` 协作红线明令禁止的断点形态）

全仓 `_goal` 命中统计（排除测试与同名无关项）：

```
neurova/agent/loops/openai_loop.py:678    "goal": getattr(self.agent, "_goal", None) or {}
```

**一处，是读取点。零写入点，且 `agent` 上从未初始化该属性。**
`getattr(..., None)` + `or {}` 使缺失静默降级为空 goal，`GoalGate` 即使挂上也只能拿到 `{}`。

> **命名冲突警示**：`cognitive_layers/memory_layer/modules/self_manager_module.py:123`
> 有 `set_goal(goal: str)`，那是**心跳任务**的 goal，语义无关。
> 新落点不得沿用 `_goal` 裸名，须带域限定（见 §4.1 `turnGoal` / `sessionGoal`）。

### RC-3 · 两条路径的门控输入不对称（独立缺陷，与 goal 无关也该修）

同一个 `on_round_end`，两条路径喂的 ctx 不同：

| ctx 键 | 流式 `:673-679` | 非流式 `:394-397` | 受害门控 |
|--------|----------------|------------------|---------|
| `tool_rounds` | ✅ | ✅ | — |
| `round_signature` | ✅ | ✅ | `DoomLoopGate` |
| `round_reply` | ✅ | ❌ | `DoomLoopGate` 内容相似分支 |
| `round_usage` | ✅ | ❌ | **`TokenBudgetGate` 在非流式路径恒不可触发** |
| `goal` | ✅ | ❌ | **`GoalGate` 在非流式路径恒不可触发** |

且非流式只判 `TERMINATE`（`:398`），**丢弃 `INTERRUPT_AND_CONTINUE`**，而流式在 `:688-694`
会注入 `continuation_prompt`。即同一门控意见在两条路上一条被执行一条被扔掉。

### RC-4 · 门控装配有两份定义

`GateRunner([DoomLoopGate(), IterationGate(...), TokenBudgetGate(...)])` 在
`openai_loop.py:99-103`（`__init__`）与 `:124-135`（`_ensure_gate_runner`）**各写一遍**。
加 `GoalGate` 之前必须先收口成一处，否则第二份门控清单立刻诞生（`AGENTS.md` 修复教义第 6 条）。

---

## 2. 目标态：闭环定义

按协作红线"写入 → 读取 → 反馈 → 再写入"逐方落实，缺一即不算完成：

| 环节 | 承载 | 当前 | 目标 |
|------|------|------|------|
| **写** | 谁产生目标 | 无 | 单一写入 API，落 `agent` 会话态 + 可选持久化（D-1 决策） |
| **读** | 门控 ctx 组装 | 仅流式、仅工具轮 | 两条路径同一装配函数 + **出口也求值** |
| **反馈** | 判定结果影响行为 | `GoalGate` 能 TERMINATE | 增加"未达成 → 注入提示续跑"，且上限受控 |
| **再写** | 判定结果的可观测消费者 | 无 | verdict 入既有观测面（§4.5），并被前端可见 |

**不做**（明确排除，防范围膨胀）：不做参照式的工作流阶段驱动器、不做 graph 重开、不做
`turnControl.stopTurnAfterResult`（那是另一条权柄，另案）。本方案只把"假完成"这一条堵上。

---

## 3. 复用面（不新造平行体系）

| 需复用的 | 落点 | 为什么是它 |
|---------|------|-----------|
| 门控执行与故障隔离 | `gates.py:185-224 GateRunner` | TERMINATE 优先、异常隔离为 BYPASS，已可用 |
| "注入提示后继续"语义 | `StopAction.INTERRUPT_AND_CONTINUE` + `StopDecision.continuation_prompt`（`gates.py:30,39`） | **类型已备好、生产端已产出（`DoomLoopGate:130-134`）、只差出口侧兑现**。新增语义等于第第二套干预通路 |
| rubric 子会话纪律 | `agent/review.py:102 run_review(llm_chat, target, focus)` | 禁工具禁网（不携 tools）、强制 JSON、容错解析、**解析失败如实返回 `parse_ok=False` 不静默丢弃**。其 `llm_chat` 注入式契约同时满足"测试禁手工传 agent_id"的既有约束 |
| 成本归属 | `models/cost_tracking.py:363 set_llm_cost_context` + `llm_client.py` 上的 `@track_llm_call` | 判定调用是真实 LLM 支出，必须自动计入本轮，不得出现"游离于账本外的推理" |
| 停滞提示样式 | `openai_loop.py:736-740`（`stagnation_prompt` 以 `role:"user"` 入消息） | 同一注入范式，不新造第二种 |
| 可达性判据 | `scripts/ci/tool_loop_deadline_ledger.py` 阈值可达性轴 | 见 §4.4，本方案的硬约束 |

---

## 4. 设计

### 4.1 事实源与写入面

单一事实源定为 **`agent.sessionGoal`**（新增，帕斯卡/驼峰按 `AGENTS.md` 命名法；
**不复用 `_goal` 裸名**，避开 §1 RC-2 的心跳 goal 冲突）。

```python
# neurova/agent/loop_goal.py（新，约 70 行）
@dataclass(frozen=True)
class LoopGoal:
    """一次会话的目标声明。frozen：目标变更走整体替换而非就地改，
    使门控读到的快照与判定输入在同一时间点一致。"""
    id: str
    statement: str                       # 自然语言目标（喂 rubric）
    successCriteria: tuple[str, ...] = ()  # 可选显式条目；缺省时由 rubric 自行拆解
    sourceTurnId: Optional[str] = None
    createdAt: float = field(default_factory=time.time)

def normalizeGoal(raw: Any) -> Optional[LoopGoal]:
    """把 dict/LoopGoal/None 归一为 Optional[LoopGoal]。
    非法输入返回 None（不猜、不兜默认目标）——判定链的 fail-closed 边界。"""
```

写入 API 挂在 agent 上（装配点，供 API 层/工具层调用）：

```python
agent.setLoopGoal(goal: LoopGoal | dict | None) -> None
```

> 读侧 `openai_loop.py:678` 的 `getattr(self.agent, "_goal", None)` 收口到
> `self._resolveGoal()`（§4.2），**同一轮内只解析一次**，消除"两条路各自 getattr"的第二份读法。

### 4.2 新增出口求值点（本方案的心脏）

在**基类** `BaseAgentLoop` 落一个共享决策函数，两条路径各自消费——决策逻辑只有一份：

```python
# neurova/agent/loops/base.py
def evaluateLoopExit(self, *, reply: str, roundUsage: Any, toolRound: int) -> LoopExitDecision:
    """主出口（模型不再调用工具）的门控求值。

    与工具轮求值同一 GateRunner、同一门控集合，但 ctx 携带 isLoopExit=True，
    使 GoalGate 能区分"停在工具轮中途"与"自认为完成"——只有后者才是假完成。
    返回 LOOP_DONE | LOOP_CONTINUE(prompt) | LOOP_STOP(reason)。
    """
```

`LoopExitDecision` 三态。`LOOP_CONTINUE` 的载荷由 `StopDecision.continuation_prompt`
直译而来——**不新增 StopAction 枚举值**（否则 `gates.py` 的动词集出现第二套表达）。

`GoalGate` 相应扩展（`gates.py:149`，仍是同一个类，不新造第二门控）：

```python
def check(self, ctx):
    ...
    if ctx.get("isLoopExit") and not achieved:
        # 假完成拦截：本轮模型已自认完成，但目标未达成
        if self._continueBudgetSpent(ctx):
            return StopDecision(action=TERMINATE, reason=f"目标未达成且续跑预算耗尽（{self.maxContinuations}）")
        return StopDecision(
            action=INTERRUPT_AND_CONTINUE,
            continuation_prompt=self._buildReopenPrompt(goal, verdict),
            gate_name=self.name,
        )
```

两条路径的接入各 3~5 行：

- 非流式 `openai_loop.py:437 return response` 前：`decision = self.evaluateLoopExit(...)`；
  `CONTINUE` → `messages.append({"role":"user","content":prompt})` 后 `return await self._predict_normal(...)`。
- 流式 `:746 yield {"type":"done"}` 前：同函数；`CONTINUE` → 注入 + `yield {"type":"reasoning","data":prompt}`（复用 `:693` 的前端可见范式）后递归。

### 4.3 判定执行器 `verifyGoalCompletion`

复用 `run_review` 的完整纪律，**新文件 `neurova/agent/goal_verifier.py`（约 110 行）**：

```python
GOAL_VERIFY_SYSTEM_PROMPT = (...)  # 只输出一个 JSON 对象
# {"achieved": bool, "confidence": number, "missing": [str], "explanation": str}

async def verifyGoalCompletion(llmChat: Callable, goal: LoopGoal, evidence: str) -> Dict[str, Any]:
    """受限目标验收子会话。llmChat 由调用方注入（生产=agent.llm_client.chat，测试=替身）。
    不携带 tools——验收本身不能产生副作用（否则"判是否完成"会去推进完成，判据自我污染）。"""
```

四条硬约束，均为既有事故的同型防御：

1. **禁工具**：不传 `tools`。参照 `review.py:103-104` 的理由。
2. **`await asyncio.to_thread(llmChat, messages)`**：`LLMClient.chat` 是同步的
   （`llm_client.py:354`），不套 `to_thread` 会卡死事件循环——`review.py:108` 已踩过。
3. **解析失败即视为未判定**：`parse_ok=False` → **不拦截**（BYPASS），
   绝不因判据坏掉就阻断正常回复。这与 `AGENTS.md` 第 2 条"诚实形态暴露"一致：
   同时发一条 warn 与 verdict 观测（§4.5），不静默。
4. **成本入账**：走 `agent.llm_client.chat` → 自动过 `@track_llm_call`（`llm_client.py:315-319`），
   并继承 `set_llm_cost_context` 的 ContextVar（`chat_pipeline.py:480-482`）→ 计入本轮，无需新代码。

`evidence` 组装：本轮 reply + 已执行工具签名摘要（**不是**全量历史，避免二次 token 膨胀）。

### 4.4 阈值单源与可达性（硬约束，防重蹈 `IterationGate`）

对标文档 §9 记录了我上一轮的错判：`IterationGate` 因 `_max_tool_rounds = max_loop_rounds // 2`
与门控阈值读**同一键不同尺度**，被机器算为 `scaled_sparse`。本方案的新阈值**不得**再现这形态。

三条设计约束：

1. `GoalGate.maxContinuations` 与 `max_rounds` **绑定到两个不同的配置键**
   （`goal_max_continuations` / `max_loop_rounds`），不共享尺度来源。
2. 出口求值的**轮次预算**必须**大于**工具轮硬顶所在来源能表达的极小值，
   或干脆不参与——本方案选：**续跑预算独立于 `_max_tool_rounds`**，
   即"续跑一次"消耗的是 `goal_max_continuations` 一格，不消耗工具轮预算。
3. 落地时同步把该阈值登记进 `scripts/ci/toolLoopDeadlines.txt`，
   要求机器算出的阈值可达性为 **`single_source`**。若算出 `scaled_unreachable` 或
   `scaled_sparse`，**即视为本方案实现有误**，红着回来改，不得人填台账迎合
   （台账纪律：值与实测不符即报红）。

### 4.5 判定结果必须有消费者（防新造断点）

verdict 三处落地，缺一即验收不通过：

1. **前端可见**：`CONTINUE` 时 `yield {"type":"reasoning", ...}`（复用 `:693` 通道），
   用户看得见"系统认为还没做完，理由是 X"。**不得**只在日志里。
2. **观测面**：接入 `on_tool_executed` 之外既有扇出点——具体走
   `neurova/core/metrics.py` 新增计数器（`goal_verification_total` / `_achieved` / `_parse_failed`）
   + `agent_self.py` 的自我模型事件（若已有 verdict 类事件位则复用，不新增）。
3. **写回历史**：`reasoning_trace_manager` 已有 `final_answer` 记录位（`reasoning_trace_manager.py:39`），
   verdict 摘要并入同一条 trace，使反思链能吃到"是否真完成"这个事实。

### 4.6 与 RC-3/RC-4 的同批处理

本方案**顺手**、且在同一个提交内完成两条前置修复（否则"两条路径语义不同"会让 goal 链
在非流式路径上静默失效，等于把 RC-1 修成 RC-3）：

- **RC-4**：`GateRunner` 装配收口到 `_buildGateRunner()` 单一函数，`__init__` 与
  `_ensure_gate_runner` 同调它。
- **RC-3**：非流式 ctx 补齐 `round_reply` / `round_usage` / `goal` 三键，
  并兑现 `INTERRUPT_AND_CONTINUE`（与 `:688-694` 同一行为）。
  **这条本身就是一个独立红灯用例**，可先于 goal 链单独落地。

---

## 5. 需要你拍板的决策点

| # | 决策 | 我的推荐 | 代价账 |
|---|------|---------|-------|
| **D-1** | goal 是否跨轮持久化 | **只做会话态（不建表、不加迁移）** | 建表=零停机迁移 + 管理面 UI + 清理策略；本方案收益的 90% 在单轮内即可兑现。跨轮目标留给后续独立立项 |
| **D-2** | goal 从哪来 | **三源并行、单点归一**：① API 入参 `ctx.metadata["goal"]`；② `tool_orchestrate` 已有的 `goal` 参数（`builtin_tools.py:1032`）派生；③ 用户在会话内显式声明 | ②③ 都是既有入口，不新增暴露面；①若不做则只能被动等 ②③ |
| **D-3** | 验收模型档位 | **允许与主模型不同档（默认同档），走 `thinking_effort` 既有单源** | 降档省钱但可能误判"已完成"，误判代价是**假完成继续存在**——不建议默认降档 |
| **D-4** | 无 goal 时出口是否求值 | **不求值，直接 DONE** | 求值就得为每次普通对话多付一次 LLM 调用。这是 D-4 的全部成本，必须选"不求值" |
| **D-5** | 上限 | `goal_max_continuations` 默认 **2** | 每次续跑 ≈ 一次完整模型往返。3 次以上收益递减、且会掩盖"目标本身不可达"的问题 |

> D-1/D-4/D-5 涉及成本与存储/管理面，按你的习惯我把账放在这里而不是替你决定。
> D-2 的 ②③ 我确认可行（都是既有入口）；① 是新增暴露面，需要你点头。

---

## 6. 测试设计（先红后绿，`AGENTS.md` 教义第 3 条）

测试根：`tests/unit/agent/`（既有目录）。全部用例名走 `test_` 前缀。
**红灯文件在转绿前不得进 `scripts/ci/protected_tests.txt`。**

### 6.1 根因级红灯（证明故障真实存在，最先写）

| 用例 | 断言 | 对应 RC |
|------|------|--------|
| `test_mainExitIsGateGuardedWhenGoalUnmet_stream` | 有 goal、模型零工具调用直接收尾 → **必须**产生一次 `INTERRUPT_AND_CONTINUE` 注入而非 `{"type":"done"}` | RC-1 |
| `test_mainExitIsGateGuardedWhenGoalUnmet_nonStream` | 同上，非流式路径 | RC-1 |
| `test_nonStreamGateCtxCarriesUsageAndGoal` | 非流式 `on_round_end` 的 ctx 键集合 ⊇ 流式键集合 | RC-3 |
| `test_nonStreamHonorsInterruptAndContinue` | 非流式路径收到 INTERRUPT 时注入 `continuation_prompt` | RC-3 |
| `test_gateAssemblyIsSingleSource` | 静态断言 `GateRunner([` 在 `openai_loop.py` 中**只出现一次** | RC-4 |
| `test_sessionGoalHasWriteAndReadSites` | 静态断言 goal 存在 ≥1 写入点，且读点不裸用 `_goal` | RC-2 |

### 6.2 行为绿灯

| 用例 | 断言 |
|------|------|
| `test_goalVerifierRejectsToolBearingRequest` | 验收调用不携带 `tools`（防副作用自我污染） |
| `test_goalVerifierParseFailureDoesNotBlock` | `parse_ok=False` → 出口照常 DONE + 发观测，不吞回复 |
| `test_goalVerifierFailureIsCostAttributed` | 验收调用经过 `@track_llm_call`，计入同一 turn_id |
| `test_continuationBudgetIsHardBounded` | 第 `max+1` 次未达成 → TERMINATE，且 reason 点名预算 |
| `test_goalThresholdIsSingleSourceInLedger` | 台账机器算 = `single_source`；算出 scaled_* 即红（§4.4 约束的自证） |
| `test_noGoalSkipsVerificationCall` | D-4 落地：无 goal 时**零**额外 LLM 调用（用替身计数，不用 MagicMock 冒充业务对象） |

**禁止写法**（`AGENTS.md` 教义第 3 条点名项，本方案尤易踩）：
不得手工传 `agent_id` 绕过生产装配；不得用 `MagicMock().get("achieved", True)` 让验收恒真；
`llmChat` 替身必须返回真实响应形状对象（含 `.content`），否则"解析"这一环没被验到。

---

## 7. 落地顺序与规模预算

`AGENTS.md` 教义第 2 条：净新增 LOC 默认 ≤ 0，为正须逐条列明去向。

### 7.1 建议切片顺序

1. **C1 前置收口**（RC-4 + RC-3）：纯重构 + 补 ctx 键 + 兑现 INTERRUPT。**无新能力**，
   可独立评审、独立回退。6.1 的五条静态/对称性红灯在此片转绿。
2. **C2 出口求值点**（RC-1）：`evaluateLoopExit` + 两路接入 + `GoalGate` 出口分支。
3. **C3 验收执行器**（`goal_verifier.py`）+ **C4 goal 写入面**（RC-2）。
   这两片有依赖：C3 提供判定、C4 提供判定输入，顺序可换但需同批联调。
4. **C5 消费者接线**（§4.5 三处）+ 台账登记。

> C1 单独就有价值：它修的是"非流式路径 `TokenBudgetGate` 恒不可触发"——
> 这条与 goal 无关，是**现存的预算失控缺陷**。建议无论 G2 做不做，C1 都排进去。

### 7.2 规模

| 项 | 估算 | 说明 |
|----|------|------|
| 生产新增 | 约 +300 LOC | `loop_goal.py` 70 / `goal_verifier.py` 110 / `gates.py` GoalGate 出口分支 40 / `base.py` `evaluateLoopExit` 50 / 两路接入 30 |
| 生产净变化 | **约 +250**（扣 C1 收口掉的重复装配 −50） | 去向逐条如上，进提交说明 |
| 测试新增 | 约 +450 LOC | 不计入 LOC 门禁（教义第 2 条） |
| 文档 | 本文 + 台账条目 | 无新增架构文档 |

**运行成本增量**：仅当 goal 已设定且模型自认完成时，多一次无工具文本往返（D-4 保证普通对话零增量）。
按 D-5 上限 2，单轮最坏 +2 次验收调用 ≈ 两次短 prompt/短 output 支出。

---

## 8. 验收线（全过才算闭环）

1. **活体验证**（教义第 4 条，不接受"单测全绿"替代）：真后端起一个带 goal 的会话，
   故意给一个**必须调两次工具**才能完成的目标，观测到：
   第一次零工具收尾被拦 → 注入提示 → 续跑 → 第二次达成 → DONE。
   命令与输出原文进提交说明。
2. **反向活体**：给一个**不可能达成**的目标，必须在预算耗尽处**有理由地**终止
   （`reason` 点名"目标未达成且续跑预算耗尽"），不得无限续跑、不得静默放弃。
3. **零回归**：无 goal 的普通会话，`predict_step` 额外 LLM 调用数 **== 0**（D-4 的活体自证）。
4. **台账一致**：`test_goalThresholdIsSingleSourceInLedger` 绿；
   `set_goal_gate` 条目由 `no_consumer` 转 `consumed`（机器算，非人改）。
5. **成本可见**：验收调用在成本账本里能按 `turn_id` 查到，不游离。
6. C1 的独立价值自证：非流式路径构造一个必超 `token_budget` 的场景，`TokenBudgetGate` **能**触发
   （修前恒不触发）。

---

## 9. 风险与回退

| 风险 | 影响 | 处置 |
|------|------|------|
| 验收模型误判"已达成" | 假完成照旧，且多花了钱 | 这是**漏判**，不劣于现状；靠 D-3 保档位 + `missing` 字段留证 + §4.5 观测面看漏判率 |
| 验收模型误判"未达成" | 无谓续跑，用户觉得"它不信我" | D-5 上限 2 硬封；`CONTINUE` 前端可见，用户可感知而非被静默延长 |
| 出口求值把递归深度再抬高 | 见对标 G1（本仓 loop 是递归，`openai_loop.py:432/:741`） | 续跑上限 2 ⇒ 深度增量 ≤2 帧，可接受；**若 G1（递归→迭代）先落地，本片风险自动消失**——这也是我把 C1 排在最前的原因之一 |
| 与心跳 `set_goal` 语义撞名 | 后来人误读 | §4.1 强制 `LoopGoal` / `setLoopGoal` 命名，禁裸 `_goal`；6.1 的静态用例反证 |
| 判据本身坏掉 | 验收链静默失效 | §4.3 第 3 条：`parse_ok=False` 不拦截但**必须**发观测；§8.4 台账用例拦阈值失明 |

**回退路径**：C2 起每片独立可回退。总开关 `agent_limits_settings.goal_verification_enabled`
（默认 **false**，灰度到具体 agent 再放开）——注意这条开关本身要进台账登记，
否则又造出"只写不读的配置"。

---

## 10. 本文未做但可以立刻做的另一件事

`agent/review.py` 的 `run_review` 是**已被两处生产调用**的（`chat_pipeline.py:820`、
`console.py:1071`），其"禁工具 + 强制 JSON + 容错解析 + 失败如实返回"四件套是本轮验收链的
现成模板。若你希望进一步压缩新代码量，可以把 `goal_verifier.py` 做成
`review.py` 的**同族第二模板实例**（抽出共享的 `runStructuredSubSession(llmChat, systemPrompt, target)`），
净新增可压约 −60 LOC。**但这会把 review 域与 goal 域耦到一个抽象上**，
我倾向不抽（两者演化方向不同），留作备选。

---

*本文取证逐行对准 `c55e1f37`。§1 四条根因均可用 §10 之外的命令独立复验：*
*`grep -n "if tool_calls:" -A 3 neurova/agent/loops/openai_loop.py`、*
*`grep -rn "_goal" --include=*.py neurova/`、`grep -n "GateRunner(\[" neurova/agent/loops/openai_loop.py`。*
